import os
from autotest.client.shared import error
from virttest import libvirt_vm, virsh


def run_virsh_save(test, params, env):
    """
    Test command: virsh save.

    The command can save the RAM state of a running domain.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Run virsh save command with assigned options.
    4.Recover test environment.(If the libvirtd service is stopped ,start
      the libvirtd service.)
    5.Confirm the test result.

    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    domid = virsh.domid(vm_name).strip()
    domuuid = virsh.domuuid(vm_name).strip()

    savefile = params.get("save_file")
    pre_vm_state = params.get("save_pre_vm_state", "null")
    libvirtd = params.get("save_libvirtd")
    extra_param = params.get("save_extra_param")
    vm_ref = params.get("save_vm_ref")

    # prepare the environment
    if vm_ref == "name" and pre_vm_state == "paused":
        virsh.suspend(vm_name)
    elif vm_ref == "name"  and pre_vm_state == "shut off":
        virsh.destroy(vm_name)

    # set the option
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "save_invalid_id" or vm_ref == "save_invalid_uuid":
        vm_ref = params.get(vm_ref)
    elif vm_ref.find("name") != -1 or vm_ref == "extra_param":
        savefile =  "%s %s" % (savefile, extra_param)
        if vm_ref == "only_name":
            savefile = " "
        vm_ref = vm_name

    if libvirtd == "off":
        libvirt_vm.libvirtd_stop()
    status = virsh.save(vm_ref, savefile, ignore_status=True).exit_status

    # recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()

    # cleanup
    if os.path.exists(savefile):
        virsh.restore(savefile)
        os.remove(savefile)

    # check status_error
    status_error = params.get("save_status_error")
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
