import os
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh domjobinfo.

    The command returns information about jobs running on a domain.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh domjobinfo operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    pre_vm_state = params.get("domjobinfo_pre_vm_state", "null")
    vm_ref = params.get("domjobinfo_vm_ref")
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")
    tmp_file = os.path.join(test.tmpdir, '%s.tmp' % vm_name)

    # prepare the state of vm
    if pre_vm_state == "dump":
        virsh.dump(vm_name, tmp_file)
    elif pre_vm_state == "save":
        virsh.save(vm_name, tmp_file)
    elif pre_vm_state == "restore":
        virsh.save(vm_name, tmp_file)
        virsh.restore(tmp_file)
    elif pre_vm_state == "managedsave":
        virsh.managedsave(vm_name)

    # run test case
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("domjobinfo_extra"))
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    status = virsh.domjobinfo(vm_ref, ignore_status=True).exit_status

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
