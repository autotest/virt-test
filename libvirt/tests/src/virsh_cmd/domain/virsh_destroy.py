from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run_virsh_destroy(test, params, env):
    """
    Test command: virsh destroy.

    The command can destroy (stop) a domain.
    1.Prepare test environment.
    2.When the ibvirtd == "off", stop the libvirtd service.
    3.Perform virsh destroy operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("destroy_vm_ref")
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("destroy_extra"))
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    status = virsh.destroy(vm_ref, ignore_status=True).exit_status
    output = ""

    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command! "
                                 "Output:\n%s" % output)
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command! Output:\n%s"
                                 % output)
