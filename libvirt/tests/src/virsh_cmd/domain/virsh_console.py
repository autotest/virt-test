import re
import logging
from autotest.client.shared import error
from virttest import aexpect, utils_test
from virttest.libvirt_xml import vm_xml, xcepts


def xml_console_config(vm_name, serial_type='pty',
                       serial_port='0', serial_path=None):
    """
    Check the primary serial and set it to pty.
    """
    vm_xml.VMXML.set_primary_serial(vm_name, serial_type,
                                    serial_port, serial_path)


def xml_console_recover(vmxml):
    """
    Recover older xml config with backup vmxml.
    """
    vmxml.undefine()
    if vmxml.define():
        return True
    else:
        logging.error("Recover older serial failed:%s.", vmxml.get('xml'))
        return False


def vm_console_config(vm, device='ttyS0', speed='115200'):
    """
    Login to config vm for virsh console.
    Three step:
    1)Add dev to /etc/securetty to support 'root' for virsh console
    2)Add kernel console:
      e.g. console=ttyS0,115200
    3)Config init process for RHEL5,4,3 and others.
      e.g. S0:2345:respawn:/sbin/mingetty ttyS0
    """
    if not vm.is_alive():
        vm.start(autoconsole=False)
        vm.wait_for_login()

    # Step 1
    vm.set_root_serial_console(device)

    # Step 2
    if not vm.set_kernel_console(device, speed):
        raise error.TestFail("Config kernel for console failed.")

    # Step 3
    if not vm.set_console_getty(device):
        raise error.TestFail("Config getty for console failed.")

    vm.destroy()
    # Confirm vm is down
    vm.wait_for_shutdown()
    return True


def run(test, params, env):
    """
    Test command: virsh console.
    """
    os_type = params.get("os_type")
    if os_type == "windows":
        raise error.TestNAError("SKIP:Do not support Windows.")

    # Get parameters for test
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    vm_ref = params.get("virsh_console_vm_ref", "domname")
    vm_state = params.get("virsh_console_vm_state", "running")
    login_user = params.get("console_login_user", "root")
    if login_user == "root":
        login_passwd = params.get("password")
    else:
        login_passwd = params.get("console_password_not_root")
    status_error = "yes" == params.get("status_error", "no")
    domuuid = vm.get_uuid()
    domid = ""

    # A backup of original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    if vm.is_alive():
        vm.destroy()
    xml_console_config(vm_name)

    try:
        # Guarantee cleanup after config vm console failed.
        vm_console_config(vm)

        # Prepare vm state for test
        if vm_state != "shutoff":
            vm.start(autoconsole=False)
            vm.wait_for_login()
            domid = vm.get_id()
        if vm_state == "paused":
            vm.pause()

        if vm_ref == "domname":
            vm_ref = vm_name
        elif vm_ref == "domid":
            vm_ref = domid
        elif vm_ref == "domuuid":
            vm_ref = domuuid
        elif domid and vm_ref == "hex_id":
            vm_ref = hex(int(domid))

        # Run command
        command = "virsh console %s" % vm_ref
        console_session = aexpect.ShellSession(command)

        status = utils_test.libvirt.verify_virsh_console(
            console_session, login_user, login_passwd, timeout=10, debug=True)
        console_session.close()

    finally:
        # Recover state of vm.
        if vm_state == "paused":
            vm.resume()

        # Recover vm
        if vm.is_alive():
            vm.destroy()
        xml_console_recover(vmxml_backup)

    # Check result
    if status_error:
        if status:
            raise error.TestFail("Run successful with wrong command!")
    else:
        if not status:
            raise error.TestFail("Run failed with right command!")
