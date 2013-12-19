import logging
import os
import re
from autotest.client.shared import error
from virttest import libvirt_vm, virsh
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test command: virsh domif-setlink and domif-getlink.

    The command   set and get link state of a virtual interface
    1. Prepare test environment.
    2. Perform virsh domif-setlink and domif-getlink operation.
    3. Recover test environment.
    4. Confirm the test result.
    """

    def domif_setlink(vm, device, operation, options):
        """
        Set the domain link state

        :param vm : domain name
        :param device : domain virtual interface
        :param opration : domain virtual interface state
        :param options : some options like --config

        """

        return virsh.domif_setlink(vm, device, operation, options, debug=True)

    def domif_getlink(vm, device, options):
        """
        Get the domain link state

        :param vm : domain name
        :param device : domain virtual interface
        :param options : some options like --config

        """

        return virsh.domif_getlink(vm, device, options,
                                   ignore_status=True, debug=True)

    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm = env.get_vm(vm_name)
    options = params.get("if_options", "--config")
    start_vm = params.get("start_vm", "no")
    if_device = params.get("if_device", "net")
    if_name = params.get("if_name", "vnet0")
    if_operation = params.get("if_operation", "up")
    if_name_re = params.get("if_ifname_re",
                            r"\s*\d+:\s+([[a-zA-Z]+\d+):")
    status_error = params.get("status_error", "no")
    mac_address = vm.get_virsh_mac_address(0)
    device = "vnet0"

    # Back up xml file.
    vm_xml_file = os.path.join(test.tmpdir, "vm.xml")
    virsh.dumpxml(vm_name, extra="--inactive", to_file=vm_xml_file)

    # Vm status
    if start_vm == "yes" and vm.is_dead():
        vm.start()

    elif start_vm == "no" and vm.is_alive():
        vm.destroy()

    # Test device net or mac address
    if if_device == "net" and vm.is_alive():
        device = if_name
        # Get all vm's interface device
        device = vm_xml.VMXML.get_net_dev(vm_name)[0]

    elif if_device == "mac":
        device = mac_address

    # Setlink opertation
    result = domif_setlink(vm_name, device, if_operation, options)
    status = result.exit_status
    logging.info("Setlink done")

    # Getlink opertation
    get_result = domif_getlink(vm_name, device, options)
    getlink_output = get_result.stdout.strip()

    # Check the getlink command output
    if not re.search(if_operation, getlink_output) and status_error == "no":
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

    error_msg = None
    if status_error == "no":
        # Serial login the vm to check link status
        # Start vm check the link statue
        session = vm.wait_for_serial_login()
        cmd = ("ip add |grep -i '%s' -B1|grep -i 'state %s' "
               % (mac_address, if_operation))
        cmd_status, output = session.cmd_status_output(cmd)
        logging.info("====%s==%s===", cmd_status, output)
        # Set the link up make host connect with vm
        domif_setlink(vm_name, device, "up", "")
        # Bring up referenced guest nic
        guest_if_name = re.search(if_name_re, output).group(1)
        # Ignore status of this one
        cmd_status = session.cmd_status('ifdown %s' % guest_if_name)
        cmd_status = session.cmd_status('ifup %s' % guest_if_name)
        if cmd_status != 0:
            error_msg = ("Could not bring up interface %s inside guest"
                         % guest_if_name)
    else:  # negative test
        # stop guest, so state is always consistent on next start
        vm.destroy()

    # Recover VM.
    if vm.is_alive():
        vm.destroy(gracefully=False)
    virsh.undefine(vm_name)
    virsh.define(vm_xml_file)
    os.remove(vm_xml_file)

    if error_msg:
        raise error.TestFail(error_msg)

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
