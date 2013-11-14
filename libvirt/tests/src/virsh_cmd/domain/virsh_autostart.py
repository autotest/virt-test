import logging
import os
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh autostart

    Set(or disable) autostart for a domain
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    persistent_vm = "yes" == params.get("persistent_vm", "yes")
    readonly_mode = "yes" == params.get("readonly_mode", "no")
    autostart_vm = "yes" == params.get("autostart_vm", "no")
    autostart_extra = params.get("autostart_extra", "")
    status_error = "yes" == params.get("status_error", "no")

    # Prepare transient/persistent vm
    original_xml = vm.backup_xml()
    if not persistent_vm and vm.is_persistent():
        vm.undefine()
    elif persistent_vm and not vm.is_persistent():
        vm.define(original_xml)

    original_autost = vm.is_autostart()
    logging.debug("Original VM %s autostart: %s", vm_name, original_autost)
    options = " "
    if not autostart_vm:
        options = "--disable "
    if autostart_extra:
        options += autostart_extra
    # Readonly mode
    ro_flag = False
    if readonly_mode:
        ro_flag = True

    # Result check
    def autostart_check():
        """
        Check if the VM autostart
        """
        res = False
        if autostart_vm and vm.is_autostart() and vm.is_alive():
            logging.debug("VM autostart as expected")
            res = True
        if not autostart_vm and not vm.is_autostart() and vm.is_dead():
            logging.debug("VM not autostart as expected")
            res = True
        return res

    # Run test
    try:
        # Make sure the VM is inactive(except transient VM)
        if vm.is_persistent() and vm.is_alive():
            vm.destroy()
        cmd_result = virsh.autostart(vm_name, options, ignore_status=True,
                                     debug=True, readonly=ro_flag)
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
        # Restart libvirtd and sleep 2
        utils_libvirtd.libvirtd_restart()
        if not status_error:
            if status:
                raise error.TestFail(err)
            elif not autostart_check():
                raise error.TestFail("Autostart check fail")
        elif status_error and status == 0:
            raise error.TestFail("Expect fail, but run successfully.")
    finally:
        # Recover env
        vm.destroy()
        if not vm.is_persistent():
            virsh.define(original_xml)
            os.remove(original_xml)
        if original_autost and not vm.is_autostart():
            virsh.autostart(vm_name, "")
        elif not original_autost and vm.is_autostart():
            virsh.autostart(vm_name, "--disable")
