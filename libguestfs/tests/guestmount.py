import logging
import os
from autotest.client.shared import error, utils
from virttest import data_dir, utils_test


def umount_fs(mountpoint):
    if os.path.ismount(mountpoint):
        result = utils.run("umount -l %s" % mountpoint, ignore_status=True)
        if result.exit_status:
            logging.debug("Umount %s failed", mountpoint)
            return False
    logging.debug("Umount %s successfully", mountpoint)
    return True


def run_guestmount(test, params, env):
    """
    Test libguestfs tool guestmount.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    if vm.is_alive():
        vm.destroy()

    # Create a file to vm with guestmount
    content = "This is file for guestmount test."
    path = params.get("gm_tempfile", "/home/gm_tmp")
    mountpoint = os.path.join(data_dir.get_tmp_dir(), "mountpoint")
    status_error = "yes" == params.get("status_error", "yes")
    readonly = "no" == params.get("gm_readonly", "no")
    special_mount = "yes" == params.get("gm_mount", "no")
    vt = utils_test.libguestfs.VirtTools(vm, params)

    if special_mount:
        # Get root filesystem before test
        params['libvirt_domain'] = params.get("main_vm")
        params['gf_inspector'] = True
        gf = utils_test.libguestfs.GuestfishTools(params)
        roots, rootfs = gf.get_root()
        gf.close_session()
        if roots is False:
            raise error.TestError("Can not get root filesystem "
                                  "in guestfish before test")
        logging.info("Root filesystem is:%s", rootfs)
        params['special_mountpoints'] = [rootfs]

    writes, writeo = vt.write_file_with_guestmount(mountpoint, path, content)
    if umount_fs(mountpoint) is False:
        logging.error("Umount vm's filesytem failed.")

    if status_error:
        if writes:
            if readonly:
                raise error.TestFail("Write file to readonly mounted "
                                     "filesystem successfully.Not expected.")
            else:
                raise error.TestFail("Write file with guestmount "
                                     "successfully.Not expected.")
    else:
        if not writes:
            raise error.TestFail("Write file to mounted filesystem failed.")
