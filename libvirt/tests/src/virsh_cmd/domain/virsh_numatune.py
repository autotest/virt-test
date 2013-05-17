import re, logging
from autotest.client.shared import error
from virttest import libvirt_vm, libvirt_xml, virsh
from virttest import utils_cgroup


def nodeset_parser(nodeset):
    """
    Parse a list of numa nodes, its syntax is a comma separated list,
    with '-' for ranges and '^' for excluding a node.
    @param nodeset: NUMA node selections to set
    """
    hyphens = []
    carets = []
    commas = []
    others = []

    if nodeset is None:
        return None

    else:
        if "," in nodeset:
            nodeset_list = re.split(",", nodeset)
            for nodeset in nodeset_list:
                if "-" in nodeset:
                    tmp = re.split("-", nodeset)
                    hyphens = hyphens + range(int(tmp[0]), int(tmp[-1])+1)
                elif "^" in nodeset:
                    tmp = re.split("\^", nodeset)[-1]
                    carets.append(int(tmp))
                else:
                    try:
                        commas.append(int(nodeset))
                    except ValueError:
                        logging.error("The nodeset has to be an "
                                      "integer. (%s)", nodeset)
        elif "-" in nodeset:
            tmp = re.split("-", nodeset)
            hyphens = range(int(tmp[0]), int(tmp[-1])+1)
        elif "^" in nodeset:
            tmp = re.split("^", nodeset)[-1]
            carets.append(int(tmp))
        else:
            try:
                others.append(int(nodeset))
                return others
            except ValueError:
                logging.error("The nodeset has to be an "
                              "integer. (%s)", nodeset)

        return list(set(hyphens).union(set(commas)).difference(set(carets)))

def check_numatune_xml(params):
    """
    Compare mode and nodeset value with guest XML configuration
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    mode = params.get("numa_mode", "")
    nodeset = params.get("numa_nodeset", "")

    virt_xml_obj = libvirt_xml.VMXML(virsh_instance=virsh)

    numa_params = virt_xml_obj.get_numa_params(vm_name)
    if not numa_params:
        logging.error("Could not get numa parameters for %s" % vm_name)
        return False

    mode_from_xml = numa_params['mode']
    nodeset_from_xml = numa_params['nodeset']

    if mode and mode != mode_from_xml:
        logging.error("To expect %s: %s", mode, mode_from_xml)
        return False

    # The actual nodeset value is different with guest XML configuration,
    # so need to compare them via a middle result, for example, if you
    # set nodeset is '0,1,2' then it will be a list '0-2' in guest XML
    nodeset = nodeset_parser(nodeset)
    nodeset_from_xml = nodeset_parser(nodeset_from_xml)

    if nodeset and nodeset != nodeset_from_xml:
        logging.error("To expect %s: %s", nodeset, nodeset_from_xml)
        return False

    return True

def get_numa_parameter(params):
    """
    Get the numa parameters
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    options = params.get("options", None)
    result = virsh.numatune(vm_name, options=options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error")
        else:
            raise error.TestFail("Unexpected return code %d" % status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            logging.info(result.stdout)

def set_numa_parameter(params):
    """
    Set the numa parameters
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    mode = params.get("numa_mode")
    nodeset = params.get("numa_nodeset")
    options = params.get("options", None)
    start_vm = params.get("start_vm", "yes")

    result = virsh.numatune(vm_name, mode, nodeset, options, debug=True)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    # For a running domain, the mode can't be changed, and the nodeset can
    # be changed only the domain was started with a mode of 'strict'
    if mode == "strict" and start_vm == "yes":
        status_error = "no"

    # TODO, the '--config' option will affect next boot, and if the guest
    # is shutoff status, the '--current' option will be equivalent to
    # '--config', if users give a specified nodeset range is more than
    # host NUMA nodes, and use virsh numatune with '--config' or '--current'
    # option to set the invalid nodeset to a guest with shutoff status, and
    # then virsh numatune will return 0 rather than 1, because the libvirt just
    # check it when starting the guest, however, the current virsh.start()
    # can't meet this requirement.

    if status_error == "yes":
        if status:
            logging.info("It's an expected error")
        else:
            raise error.TestFail("Unexpected return code %d" % status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_numatune_xml(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The 'mode' or/and 'nodeset' are"
                                     " inconsistent with numatune XML")

def run_virsh_numatune(test, params, env):
    """
    Test numa tuning

    1) Positive testing
       1.1) get the current numa parameters for a running/shutoff guest
       1.2) set the current numa parameters for a running/shutoff guest
           1.2.1) set valid 'mode' parameters
           1.2.2) set valid 'nodeset' parameters
    2) Negative testing
       2.1) get numa parameters
           2.1.1) invalid options
           2.1.2) stop cgroup service
       2.2) set numa parameters
           2.2.1) invalid 'mode' parameters
           2.2.2) invalid 'nodeset' parameters
           2.2.3) change 'mode' for a running guest and 'mode' is not 'strict'
           2.2.4) change 'nodeset' for running guest with mode of 'interleave'
                  'interleave' or 'preferred' numa mode
           2.2.5) stop cgroup service
    """

    # Run test case
    vm_name = params.get("vms")
    vm = env.get_vm(vm_name)
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")
    cgconfig = params.get("cgconfig", "on")
    start_vm = params.get("start_vm", "no")
    change_parameters = params.get("change_parameters", "no")

    ########## positive and negative testing #########

    if status_error == "no":
        if change_parameters == "no":
            get_numa_parameter(params)
        else:
            set_numa_parameter(params)

    if cgconfig == "off":
        # Need to shutdown a running guest before stopping cgconfig service
        # and will start the guest after restarting libvirtd service
        if vm.is_alive():
            vm.destroy()
        if utils_cgroup.service_cgconfig_control("status"):
            utils_cgroup.service_cgconfig_control("stop")

    # Refresh libvirtd service to get latest cgconfig service change
    if libvirtd == "restart":
        libvirt_vm.service_libvirtd_control("restart")

    # Recover previous running guest
    if cgconfig == "off" and libvirtd == "restart" \
        and not vm.is_alive() and start_vm == "yes":
        vm.start()

    if status_error == "yes":
        if change_parameters == "no":
            get_numa_parameter(params)
        else:
            set_numa_parameter(params)

    # Recover cgconfig and libvirtd service
    if not utils_cgroup.service_cgconfig_control("status"):
        utils_cgroup.service_cgconfig_control("start")
        libvirt_vm.service_libvirtd_control("restart")
