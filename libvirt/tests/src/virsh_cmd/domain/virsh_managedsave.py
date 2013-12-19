import re
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh managedsave.

    This command can save and destroy a
    running domain, so it can be restarted
    from the same state at a later time.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])

    # define function
    def vm_recover_check(guest_name):
        """
        Check if the vm can be recovered correctly.

        :param guest_name : Checked vm's name.
        """
        ret = virsh.dom_list()
        # This time vm should not be in the list
        if re.search(guest_name, ret.stdout):
            raise error.TestFail("virsh list output invalid")
        virsh.start(guest_name)
        if params.get("paused_after_start_vm") == "yes":
            virsh.resume(guest_name, ignore_status=True)
        # This time vm should be in the list
        ret = virsh.dom_list()
        if not re.search(guest_name, ret.stdout):
            raise error.TestFail("virsh list output invalid")

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    libvirtd = params.get("managedsave_libvirtd", "on")

    # run test case
    vm_ref = params.get("managedsave_vm_ref")
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "managedsave_invalid_id" or\
            vm_ref == "managedsave_invalid_uuid":
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name" or vm_ref == "extra_parame":
        vm_ref = "%s %s" % (vm_name, params.get("managedsave_extra_parame"))

    # stop the libvirtd service
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # Ignore exception with "ignore_status=True"
    ret = virsh.managedsave(vm_ref, ignore_status=True)
    status = ret.exit_status

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    status_error = params.get("status_error")
    if status_error == "yes":
        if status == 0:
            if not virsh.has_command_help_match('managedsave', r'\s+--running\s+'):
                # Older libvirt does not have --running parameter
                raise error.TestNAError(
                    "Older libvirt does not handle arguments consistently")
            else:
                raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        vm_recover_check(vm_name)
