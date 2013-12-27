import re
import os
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh restore.

    Restore a domain from a saved state in a file
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Run virsh restore command with assigned option.
    4.Recover test environment.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    os_type = params.get("os_type")
    status_error = params.get("restore_status_error")
    libvirtd = params.get("restore_libvirtd")
    extra_param = params.get("restore_extra_param")
    pre_status = params.get("restore_pre_status")
    vm_ref = params.get("restore_vm_ref")

    # run test
    if vm_ref == "" or vm_ref == "xyz":
        status = virsh.restore(vm_ref, extra_param, debug=True,
                               ignore_status=True).exit_status
    else:
        if os_type == "linux":
            cmd = "cat /proc/cpuinfo"
            try:
                status, output = session.cmd_status_output(cmd, timeout=10)
            finally:
                session.close()
            if not re.search("processor", output):
                raise error.TestFail("Unable to read /proc/cpuinfo")
        tmp_file = os.path.join(test.tmpdir, "save.file")
        virsh.save(vm_name, tmp_file)
        if vm_ref == "saved_file":
            vm_ref = tmp_file
        elif vm_ref == "empty_new_file":
            tmp_file = os.path.join(test.tmpdir, "new.file")
            open(tmp_file, 'w').close()
            vm_ref = tmp_file
        if vm.is_alive():
            vm.destroy()
        if pre_status == "start":
            virsh.start(vm_name)
        if libvirtd == "off":
            utils_libvirtd.libvirtd_stop()
        status = virsh.restore(vm_ref, extra_param, debug=True,
                               ignore_status=True).exit_status
    if status_error == "no":
        list_output = virsh.dom_list().stdout.strip()

    session.close()

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()
    if vm.is_alive():
        vm.destroy()

    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        else:
            if not re.search(vm_name, list_output):
                raise error.TestFail("Run failed with right command")
