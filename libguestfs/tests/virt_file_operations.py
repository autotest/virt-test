import re
import os
import logging
import tarfile
from autotest.client.shared import utils, error
from virttest import data_dir, utils_test, virt_vm, remote, aexpect


def test_virt_tar_in(vm, params):
    """
    1) Write a tempfile on host
    2) Copy file to guest with virt-tar-in
    3) Delete created file
    4) Check file on guest
    """
    content = "This is file for test of virt-tar-in."
    path = params.get("vt_temp_file", "/tmp/test_virt_tar_in")
    file_dir = os.path.dirname(path)
    path_on_host = os.path.join(data_dir.get_tmp_dir(),
                                "test_virt_tar_in.tar")

    # Create a file on host
    try:
        open(path, 'w').write(content)
    except IOError, detail:
        raise error.TestNAError("Prepare file on host failed:%s" % detail)
    try:
        tar = tarfile.open(path_on_host, "w")
        tar.add(path)
        tar.close()
    except tarfile.TarError, detail:
        raise error.TestNAError("Prepare tar file on host failed:%s" % detail)

    vt = utils_test.libguestfs.VirtTools(vm, params)

    # Copy file to guest
    tar_in_result = vt.tar_in(path_on_host, '/')
    logging.debug(tar_in_result)

    # Delete file on host
    try:
        os.remove(path)
        os.remove(path_on_host)
    except OSError, detail:
        # Let it go because file maybe not exist
        logging.warning(detail)

    if tar_in_result.exit_status:
        raise error.TestFail("Tar in failed.")
    logging.info("Tar in successfully.")

    # Cat file on guest
    cat_result = vt.cat(path)
    logging.debug(cat_result)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match")

    try:
        vm.start()
        session = vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        vm.destroy()
        raise error.TestFail(str(detail))

    try:
        output = session.cmd_output("cat %s" % path, timeout=5)
        logging.debug(output)
        vm.destroy()
        vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        output = str(detail)
        logging.error(output)
        if vm.is_alive():
            vm.destroy()

    if not re.search(content, output):
        raise error.TestFail("File content is not match.")
    logging.info("Check created file on guest successfully.")


def test_virt_tar_out(vm, params):
    """
    1) Write a tempfile to guest
    2) Copy file to host with tar-out
    3) Delete created file
    """
    content = "This is file for test of virt-tar-out."
    path = params.get("vt_temp_file", "/tmp/test_virt_tar_out")
    file_dir = os.path.dirname(path)
    path_on_host = os.path.join(data_dir.get_tmp_dir(),
                                "test_virt_tar_out.tar")

    vt = utils_test.libguestfs.VirtTools(vm, params)
    mountpoint = params.get("vt_mountpoint", "/mnt")

    writes, writeo = vt.write_file_with_guestmount(mountpoint, path, content,
                                                   cleanup=False)
    if utils_test.libguestfs.umount_fs(mountpoint) is False:
        logging.error("Umount vm's filesytem failed.")

    if writes is False:
        raise error.TestFail("Write file to mounted filesystem failed.")
    logging.info("Create %s successfully.", path)

    # Copy file to host
    tar_out_result = vt.tar_out(file_dir, path_on_host)
    logging.debug(tar_out_result)
    if tar_out_result.exit_status:
        raise error.TestFail("Tar out failed.")
    logging.info("Tar out successfully.")

    # uncompress file and check file in it.
    uc_result = utils.run("cd %s && tar xf %s" % (file_dir, path_on_host))
    logging.debug(uc_result)
    try:
        os.remove(path_on_host)
    except IOError, detail:
        raise error.testfail(str(detail))
    if uc_result.exit_status:
        raise error.testfail("uncompress file on host failed.")
    logging.info("uncompress file on host successfully.")

    # Check file
    cat_result = utils.run("cat %s" % path, ignore_status=True)
    logging.debug(cat_result)
    try:
        os.remove(path)
    except IOError, detail:
        logging.error(detail)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match.")


def test_virt_copy_in(vm, params):
    """
    1) Write a tempfile on host
    2) Copy file to guest with copy-in
    3) Delete created file
    4) Check file on guest
    """
    content = "This is file for test of virt-copy-in."
    path = params.get("vt_temp_file", "/tmp/test_virt_copy_in")
    path_dir = os.path.dirname(path)

    # Create a file on host
    try:
        open(path, 'w').write(content)
    except IOError, detail:
        raise error.TestNAError("Prepare file on host failed:%s" % detail)

    vt = utils_test.libguestfs.VirtTools(vm, params)

    # Copy file to guest
    copy_in_result = vt.copy_in(path, path_dir)
    logging.debug(copy_in_result)

    # Delete file on host
    try:
        os.remove(path)
    except IOError, detail:
        logging.error(detail)

    if copy_in_result.exit_status:
        raise error.TestFail("Copy in failed.")
    logging.info("Copy in successfully.")

    # Cat file on guest
    cat_result = vt.cat(path)
    logging.debug(cat_result)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match")

    try:
        vm.start()
        session = vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        vm.destroy()
        raise error.TestFail(str(detail))

    try:
        output = session.cmd_output("cat %s" % path, timeout=5)
        logging.debug(output)
        vm.destroy()
        vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        output = str(detail)
        logging.error(output)
        if vm.is_alive():
            vm.destroy()

    if not re.search(content, output):
        raise error.TestFail("File content is not match.")
    logging.info("Check created file on guest successfully.")


def test_virt_copy_out(vm, params):
    """
    1) Write a tempfile to guest
    2) Copy file to host with copy-out
    3) Delete created file
    4) Check file on host
    """
    content = "This is file for test of virt-copy-out."
    path = params.get("vt_temp_file", "/tmp/test_virt_copy_out")
    path_dir = os.path.dirname(path)

    vt = utils_test.libguestfs.VirtTools(vm, params)
    mountpoint = params.get("vt_mountpoint", "/mnt")

    writes, writeo = vt.write_file_with_guestmount(mountpoint, path, content,
                                                   cleanup=False)
    if utils_test.libguestfs.umount_fs(mountpoint) is False:
        logging.error("Umount vm's filesytem failed.")

    if writes is False:
        raise error.TestFail("Write file to mounted filesystem failed.")
    logging.info("Create %s successfully.", path)

    # Copy file to host
    copy_out_result = vt.copy_out(path, path_dir)
    logging.debug(copy_out_result)
    if copy_out_result.exit_status:
        raise error.TestFail("Copy out failed.")
    logging.info("Copy out successfully.")

    # Check file
    cat_result = utils.run("cat %s" % path, ignore_status=True)
    logging.debug(cat_result.stdout)
    try:
        os.remove(path)
    except IOError, detail:
        logging.error(detail)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match.")


def run_virt_file_operations(test, params, env):
    """
    Test libguestfs with file commands: virt-tar-in, virt-tar-out,
                                        virt-copy-in, virt-copy-out
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("vt_file_operation")
    testcase = globals()["test_%s" % operation]
    testcase(vm, params)
