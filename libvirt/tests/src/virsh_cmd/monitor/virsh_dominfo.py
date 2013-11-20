from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run_virsh_dominfo(test, params, env):
    """
    Test command: virsh dominfo.

    The command returns basic information about the domain.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh dominfo operation.
    4.Recover test environment.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(vm_name)
    if vm.is_alive() and params.get("start_vm") == "no":
        vm.destroy()

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("dominfo_vm_ref")
    extra = params.get("dominfo_extra", "")
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")

    # run test case
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, extra)
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    result = virsh.dominfo(vm_ref, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
