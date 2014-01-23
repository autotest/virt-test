import logging
import os
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh desc.

    This command allows to show or modify description or title of a domain.
    1). For running domain, get/set description&title with options.
    2). For shut off domian, get/set description&title with options.
    3). For persistent/transient domain, get/set description&title with options.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    options = params.get("desc_option", "")
    persistent_vm = params.get("persistent_vm", "yes")

    def run_cmd(name, options, desc_str, status_error):
        """
        Run virsh desc command

        :return: cmd output
        """
        cmd_result = virsh.desc(name, options, desc_str, ignore_status=True,
                                debug=True)
        output = cmd_result.stdout.strip()
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
        if status_error == "no" and status:
            raise error.TestFail(err)
        elif status_error == "yes" and status == 0:
            raise error.TestFail("Expect fail, but run successfully.")
        return output

    def vm_state_switch():
        """
        Switch the vm state
        """
        if vm.is_dead():
            vm.start()
        if vm.is_alive():
            vm.destroy()

    def desc_check(name, desc_str, state_switch):
        """
        Check the domain's description or title
        """
        ret = False
        if state_switch:
            vm_state_switch()
        output = run_cmd(name, "", "", "no")
        if desc_str == output:
            logging.debug("Domain desc check successfully.")
            ret = True
        else:
            logging.error("Domain desc check fail.")
        if state_switch:
            vm_state_switch()
        return ret

    def run_test():
        """
        Get/Set vm desc by running virsh desc command.
        """
        status_error = params.get("status_error", "no")
        desc_str = params.get("desc_str", "")
        state_switch = False
        # Test 1: get vm desc
        run_cmd(vm_name, options, "", status_error)
        # Test 2: set vm desc
        if options.count("--config") and vm.is_persistent():
            state_switch = True
        if options.count("--live") and vm.state() == "shut off":
            status_error = "yes"
        if len(desc_str) == 0:
            desc_str = "New Description/title for the %s vm" % vm.state()
            logging.debug("Use the default desc message: %s", desc_str)
        run_cmd(vm_name, options, desc_str, status_error)
        desc_check(vm_name, desc_str, state_switch)

    # Prepare transient/persistent vm
    original_xml = vm.backup_xml()
    if persistent_vm == "no" and vm.is_persistent():
        vm.undefine()
    elif persistent_vm == "yes" and not vm.is_persistent():
        vm.define(original_xml)
    try:
        if vm.is_dead():
            vm.start()
        run_test()
        # Recvoer the vm and shutoff it
        if persistent_vm == "yes":
            vm.define(original_xml)
            vm.destroy()
            run_test()
    finally:
        vm.destroy()
        virsh.define(original_xml)
        os.remove(original_xml)
