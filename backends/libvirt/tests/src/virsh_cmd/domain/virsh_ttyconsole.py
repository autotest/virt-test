import logging
from autotest.client.shared import error
from virttest import libvirt_vm, virsh
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


def run(test, params, env):
    """
    Test command: virsh ttyconsole.

    1) Config console in xml file.
    2) Run test for virsh ttyconsole.
    3) Result check.
    """
    os_type = params.get("os_type")
    if os_type == "windows":
        raise error.TestNAError("SKIP:Do not support Windows.")

    # Get parameters
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    vm_ref = params.get("virsh_ttyconsole_vm_ref", "domname")
    vm_state = params.get("vm_state", "running")
    option_suffix = params.get("virsh_ttyconsole_option_suffix", "")
    vm_uuid = vm.get_uuid()
    vm_id = ""
    virsh_dargs = {'ignore_status': True, 'uri': uri}

    # A backup of original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    if vm.is_alive():
        vm.destroy()
    # Config vm for tty console
    xml_console_config(vm_name)
    vm.destroy()

    # Prepare vm state for test
    if vm_state != "shutoff":
        vm.start()
        vm.wait_for_login()
        vm_id = vm.get_id()
    if vm_state == "paused":
        vm.pause()

    # Prepare options
    if vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domuuid":
        vm_ref = vm_uuid
    elif vm_ref == "domid":
        vm_ref = vm_id
    elif vm_id and vm_ref == "hex_id":
        vm_ref = hex(int(vm_id))

    if option_suffix:
        vm_ref += " %s" % option_suffix

    # Run test command
    result = virsh.ttyconsole(vm_ref, **virsh_dargs)
    status = result.exit_status
    logging.debug(result)

    # Recover state of vm.
    if vm_state == "paused":
        vm.resume()

    # Recover vm
    if vm.is_alive():
        vm.destroy()
    xml_console_recover(vmxml_backup)

    # check status_error
    status_error = params.get("status_error")
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successful with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command.")
