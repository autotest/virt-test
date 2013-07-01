import os, logging
from autotest.client.shared import error
from virttest import libvirt_vm, utils_cgroup, virsh
from virttest.libvirt_xml import vm_xml
from virttest.utils_misc import get_dev_major_minor


def check_blkiotune(params):
    """
    To compare weight and device-weights value with guest XML
    configuration, virsh blkiotune output and corresponding
    blkio.weight and blkio.weight_device value from cgroup.
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    vm = params.get("vm")
    options = params.get("options", None)
    weight = params.get("blkio_weight", "")
    cgconfig = params.get("cgconfig", "on")
    device_weights = params.get("blkio_device_weights", "")
    result = virsh.blkiotune(vm_name)
    dicts = {}
    # Parsing command output and putting them into python dictionary.
    cmd_output = result.stdout.strip().splitlines()
    for l in cmd_output:
        k, v = l.split(':')
        dicts[k.strip()] = v.strip()

    logging.debug(dicts)

    virt_xml_obj = vm_xml.VMXML(virsh_instance=virsh)

    # To change a running guest with 'config' option, which will affect
    # next boot, if don't shutdown the guest, we need to run virsh dumpxml
    # with 'inactive' option to get guest XML changes.
    if options == "config" and vm and vm.is_alive():
        blkio_params = virt_xml_obj.get_blkio_params(vm_name, "--inactive")
    else:
        blkio_params = virt_xml_obj.get_blkio_params(vm_name)

    device_weights_from_xml = ""
    weight_from_cgroup = ""
    device_weight_from_cgroup = ""
    blkio_params_from_cgroup = {}

    weight_from_xml = blkio_params.get("weight", "")
    device_weights_path_from_xml = blkio_params.get("device_weights_path")
    device_weights_weight_from_xml = blkio_params.get("device_weights_weight")
    weight_from_cmd_output = dicts['weight']
    device_weights_from_cmd_output = dicts['device_weight']

    # To get guest corresponding blkio.weight and blkio.weight_device value
    # from blkio controller of the cgroup.
    if cgconfig == "on" and vm and vm.is_alive():
        blkio_params_from_cgroup = get_blkio_params_from_cgroup(params)
        weight_from_cgroup = blkio_params_from_cgroup.get('weight')
        device_weight_from_cgroup = \
            blkio_params_from_cgroup.get('weight_device')

    # The device-weights is a single string listing, in the format
    # of /path/to/device,weight
    if device_weights_path_from_xml and device_weights_weight_from_xml:
        device_weights_from_xml = device_weights_path_from_xml + "," + \
                                 device_weights_weight_from_xml

    if device_weights:
        dev = device_weights.split(',')[0]
        (major, minor) = get_dev_major_minor(dev)
        device_weights_tmp = str(major) + ":" + str(minor) + "," + \
                             device_weights.split(',')[1]

    # To check specified weight and device_weight value with virsh command
    # output and/or blkio.weight and blkio.weight_device value from blkio
    # controller of the cgroup.
    if vm and vm.is_alive() and options != "config":
        if weight and weight != weight_from_cmd_output or \
            weight and weight != weight_from_cgroup:
            logging.error("To expect weight %s: %s",
                          (weight, weight_from_cmd_output))
            return False
        if device_weights and \
            device_weights != device_weights_from_cmd_output or \
            device_weights and \
            device_weights_tmp != device_weight_from_cgroup:
            # The value 0 to remove that device from per-device listings.
            if device_weights.split(',')[-1] == '0' and not \
                device_weights_from_cmd_output:
                return True
            else:
                logging.error("To expect device_weights %s: %s",
                              (device_weights, device_weights_from_cmd_output))
                return False
    else:
        if weight and weight != weight_from_xml:
            logging.error("To expect weight %s: %s", (weight, weight_from_xml))
            return False
        if device_weights and device_weights_from_xml and \
            device_weights != device_weights_from_xml:
            logging.error("To expect device_weights %s: %s", (device_weights,
                           device_weights_from_xml))
            return False

    return True


def get_blkio_params_from_cgroup(params):
    """
    Get a list of domain-specific per block stats from cgroup blkio controller.
    @param domain: Domain name
    @param qemu_path: Default: "/libvirt/qemu/".
    """

    vm_name = params.get("vms")
    qemu_path = params.get("qemu_path")

    if not qemu_path:
        # qemu_path defaults as follows for RHEL7.y or F19
        qemu_path = "/machine/%s.libvirt-qemu" % vm_name
        blkio_path = utils_cgroup.get_cgroup_mountpoint("blkio") + \
                      qemu_path
    else:
        # qemu_path defaults "/libvirt/qemu/" on RHEL6.y, and requires tester
        # to add the parameter into test configuration
        blkio_path = utils_cgroup.get_cgroup_mountpoint("blkio") + \
                     qemu_path + vm_name

    blkio_weight_file = os.path.join(blkio_path, "blkio.weight")
    blkio_device_weights_file = os.path.join(blkio_path, "blkio.weight_device")

    blkio_params_from_cgroup = {}

    for f in blkio_weight_file, blkio_device_weights_file:
        try:
            f_blkio_params = open(f, "rU")
            val = f_blkio_params.readline().split()
            if len(val) > 1:
                blkio_params_from_cgroup[f.split('.')[-1]] = \
                val[0] + "," + val[1]
            elif len(val) == 1:
                blkio_params_from_cgroup[f.split('.')[-1]] = val[0]
            f_blkio_params.close()
        except IOError:
            raise error.TestError("Failed to get blkio params from %s" % f)

    logging.debug(blkio_params_from_cgroup)
    return blkio_params_from_cgroup


def get_blkio_parameter(params):
    """
    Get the blkio parameters
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    options = params.get("options")

    result = virsh.blkiotune(vm_name, options=options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            logging.info(result.stdout)


def set_blkio_parameter(params):
    """
    Set the blkio parameters
    @params: the parameter dictionary
    """
    vm_name = params.get("vms")
    weight = params.get("blkio_weight")
    device_weights = params.get("blkio_device_weights")
    options = params.get("options")

    result = virsh.blkiotune(vm_name, weight, device_weights, options)
    status = result.exit_status

    # Check status_error
    status_error = params.get("status_error", "no")

    if status_error == "yes":
        if status:
            logging.info("It's an expected error: %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            if check_blkiotune(params):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The 'weight' or/and 'device-weights' are"
                                     " inconsistent with blkiotune XML or/and"
                                     " blkio.weight and blkio.weight_device"
                                     " value from cgroup blkio controller")


def run_virsh_blkiotune(test, params, env):
    """
    Test blkio tuning

    1) Positive testing
       1.1) get the current blkio parameters for a running/shutoff guest
       1.2) set the current blkio parameters for a running/shutoff guest
    2) Negative testing
       2.1) get blkio parameters for a running/shutoff guest
       2.2) set blkio parameters running/shutoff guest
    """

    # Run test case
    vm_name = params.get("vms")
    vm = env.get_vm(vm_name)
    cgconfig = params.get("cgconfig", "on")
    start_vm = params.get("start_vm", "yes")
    status_error = params.get("status_error", "no")
    change_parameters = params.get("change_parameters", "no")

    if start_vm == "no" and vm and vm.is_alive():
        vm.destroy()

    test_dict = dict(params)
    test_dict['vm'] = vm

    ########## positive and negative testing #########

    if status_error == "no":
        if change_parameters == "no":
            get_blkio_parameter(test_dict)
        else:
            set_blkio_parameter(test_dict)

    if cgconfig == "off":
        if utils_cgroup.service_cgconfig_control("status"):
            utils_cgroup.service_cgconfig_control("stop")

    if status_error == "yes":
        if change_parameters == "no":
            get_blkio_parameter(test_dict)
        else:
            set_blkio_parameter(test_dict)

    # Recover cgconfig and libvirtd service
    if not utils_cgroup.service_cgconfig_control("status"):
        utils_cgroup.service_cgconfig_control("start")
        libvirt_vm.service_libvirtd_control("restart")

