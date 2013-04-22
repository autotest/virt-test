import logging, re
from autotest.client.shared import error
from virttest import libvirt_vm, virsh
from virttest.libvirt_xml import vm_xml

def run_virsh_domif_setlink_getlink(test, params, env):
    """
    Test command: virsh domif-setlink and domif-getlink.

    The command   set and get link state of a virtual interface
    1. Prepare test environment.
    2. When the libvirtd == "off", stop the libvirtd service.
    3. Perform virsh domif-setlink and domif-getlink operation.
    4. Recover test environment.
    5. Confirm the test result.
    """

    def domif_setlink(vm, device, operation, options):
        """
        """

        return virsh.domif_setlink(vm, device, operation, options, debug=True)

    def domif_getlink(vm, device, options):
        """
        """

        return virsh.domif_getlink(vm, device, options,
                                   ignore_status=True, debug=True)

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    options = params.get("options")
    start_vm = params.get("start_vm")
    libvirtd = params.get("libvirtd", "on")
    if_device = params.get("if_device")
    if_name = params.get("if_name")
    operation = params.get("operation")
    status_error = params.get("status_error")
    mac_address = vm.get_virsh_mac_address(0)
    device = "vnet0"
    # Vm status
    if start_vm == "yes" and vm.is_dead():
        vm.start()

    elif start_vm == "no" and vm.is_alive():
        vm.destroy()

    if libvirtd == "off":
        libvirt_vm.libvirtd_stop()

    # Test device net or mac address
    if if_device == "net" and vm.is_alive():
        device = if_name
        # Get all vm's interface device
        net_dev = vm_xml.VMXML.get_net_dev(vm_name)
        device = net_dev[0]

    elif if_device == "mac":
        device = mac_address

    # Setlink opertation
    result = domif_setlink(vm_name, device, operation, options)
    status = result.exit_status
    logging.info("Setlink done")

    # Getlink opertation
    get_result = domif_getlink(vm_name, device, options)
    getlink_output = get_result.stdout.strip()

    # Check the getlink command output
    if not re.search(operation, getlink_output) and status_error == "no":
        raise error.TestFail("Getlink result should "
                             "equal with setlink operation ", getlink_output)

    logging.info("Getlink done")
    # If --config is given should restart the vm then test link status
    if options == "--config" and vm.is_alive():
        vm.destroy()
        vm.start()
        logging.info("Restart VM")

    elif start_vm == "no":
        vm.start()

    if status_error == "no":
        # Serial login the vm to check link status
        # Start vm check the link statue
        session = vm.wait_for_serial_login()
        cmd = "ip add |grep -i '%s' -B1|grep -i 'state %s' " \
        % (mac_address, operation)
        cmd_status, output = session.cmd_status_output(cmd)
        logging.info("====%s==%s===", cmd_status, output )
        # Set the link up make host connect with vm
        domif_setlink(vm_name, device, "up", "")
        session.cmd("service network restart")

    # Recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()

    # Check status_error

    if status_error == "yes":
        if status:
            logging.info("Expected error (negative testing). Output: %s",
                         result.stderr.strip())

        else:
            raise error.TestFail("Unexpected return code %d "
                                 "(negative testing)" % status)
    elif status_error == "no":
        status = cmd_status
        if status:
            raise error.TestFail("Unexpected error (positive testing). "
                                 "Output: %s" % result.stderr.strip())

    else:
        raise error.TestError("Invalid value for status_error '%s' "
                              "(must be 'yes' or 'no')" % status_error)
