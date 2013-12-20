import re
import logging
from virttest.utils_test.libvirt import cpus_parser
from autotest.client.shared import error, utils
from virttest import libvirt_xml, virsh, utils_libvirtd
from virttest.libvirt_xml.xcepts import LibvirtXMLAccessorError
try:
    from virttest.staging import utils_cgroup
except ImportError:
    # TODO: Obsoleted path used prior autotest-0.15.2/virttest-2013.06.24
    from autotest.client.shared import utils_cgroup


def num_numa_nodes():
    """
    Return the number of available numa nodes
    """
    output = utils.run('numactl -H').stdout.strip()
    mobj = re.match(r'available:\s+(\d+)\s+nodes\s+.*', output)
    if mobj is not None:
        return int(mobj.group(1))
    else:
        return 0


def check_numatune_xml(params):
    """
    Compare mode and nodeset value with guest XML configuration
    :params: the parameter dictionary
    """
    vm_name = params.get("vms")
    mode = params.get("numa_mode", "")
    nodeset = params.get("numa_nodeset", "")
    options = params.get("options", "")
    #--config option will act after vm shutdown.
    if options == "config":
        virsh.shutdown(vm_name)
    # The verification of the numa params should
    # be done when vm is running.
    if not virsh.is_alive(vm_name):
        virsh.start(vm_name)

    try:
        numa_params = libvirt_xml.VMXML.get_numa_params(vm_name)
    # VM XML omit numa entry when the placement is auto and mode is strict
    # So we need to set numa_params manually when exception happens.
    except LibvirtXMLAccessorError:
        numa_params = {'placement': 'auto', 'mode': 'strict'}

    if not numa_params:
        logging.error("Could not get numa parameters for %s", vm_name)
        return False

    mode_from_xml = numa_params['mode']
    # if the placement is auto, there is no nodeset in numa param.
    try:
        nodeset_from_xml = numa_params['nodeset']
    except KeyError:
        nodeset_from_xml = ""

    if mode and mode != mode_from_xml:
        logging.error("To expect %s: %s", mode, mode_from_xml)
        return False

    # The actual nodeset value is different with guest XML configuration,
    # so need to compare them via a middle result, for example, if you
    # set nodeset is '0,1,2' then it will be a list '0-2' in guest XML
    nodeset = cpus_parser(nodeset)
    nodeset_from_xml = cpus_parser(nodeset_from_xml)

    if nodeset and nodeset != nodeset_from_xml:
        logging.error("To expect %s: %s", nodeset, nodeset_from_xml)
        return False

    return True


def get_numa_parameter(params):
    """
    Get the numa parameters
    :params: the parameter dictionary
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
    :params: the parameter dictionary
    """
    vm_name = params.get("vms")
    mode = params.get("numa_mode")
    nodeset = params.get("numa_nodeset")
    options = params.get("options", None)
    start_vm = params.get("start_vm", "yes")

    # Don't use libvirt_xml here because testing numatune command
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
            if len(cpus_parser(nodeset)) > num_numa_nodes():
                raise error.TestNAError("Host does not support requested"
                                        " nodeset")
            else:
                raise error.TestFail(result.stderr)
        else:
            if check_numatune_xml(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The 'mode' or/and 'nodeset' are"
                                     " inconsistent with numatune XML")


def run(test, params, env):
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
    original_vm_xml = libvirt_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    cgconfig_service = utils_cgroup.CgconfigService()
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")
    cgconfig = params.get("cgconfig", "on")
    start_vm = params.get("start_vm", "no")
    change_parameters = params.get("change_parameters", "no")

    # Make sure vm is down if start not requested
    if start_vm == "no" and vm.is_alive():
        vm.destroy()

    # positive and negative testing #########

    try:
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
            if cgconfig_service.cgconfig_is_running():
                cgconfig_service.cgconfig_stop()
        # Refresh libvirtd service to get latest cgconfig service change
        if libvirtd == "restart":
            utils_libvirtd.libvirtd_restart()
        # Recover previous running guest
        if (cgconfig == "off" and libvirtd == "restart"
                and not vm.is_alive() and start_vm == "yes"):
            vm.start()
        if status_error == "yes":
            if change_parameters == "no":
                get_numa_parameter(params)
            else:
                set_numa_parameter(params)
    finally:
        # Recover cgconfig and libvirtd service
        if not cgconfig_service.cgconfig_is_running():
            cgconfig_service.cgconfig_start()
            utils_libvirtd.libvirtd_restart()
        # Restore guest
        original_vm_xml.sync()
