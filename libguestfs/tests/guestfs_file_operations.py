import re
import os
import logging
import tarfile
from autotest.client.shared import utils, error
from virttest import data_dir, utils_test


def test_tar_in(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Write a tempfile on host
    3) Copy file to guest with tar-in
    4) Delete created file
    5) Check file on guest
    """
    content = "This is file for test of tar-in."
    path = params.get("gf_temp_file", "/tmp/test_tar_in")
    path_on_host = os.path.join(data_dir.get_tmp_dir(), "test_tar_in.tar")

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

    params['libvirt_domain'] = vm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # Copy file to guest
    tar_in_result = gf.tar_in(path_on_host, "/")
    logging.debug(tar_in_result)

    # Delete file on host
    try:
        os.remove(path)
        os.remove(path_on_host)
    except OSError, detail:
        # Let it go because file maybe not exist
        logging.warning(detail)

    if tar_in_result.exit_status:
        gf.close_session()
        raise error.TestFail("Tar in failed.")
    logging.info("Tar in successfully.")

    # Cat file on guest
    cat_result = gf.cat(path)
    rm_result = gf.rm(path)
    gf.close_session()
    logging.debug(cat_result)
    logging.debug(rm_result)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match")
    if rm_result.exit_status:
        raise error.TestFail("Rm file failed.")
    logging.info("Rm %s successfully.", path)


def test_tar_out(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Write a tempfile to guest
    3) Copy file to host with tar-out
    4) Delete created file
    5) Check file on host
    """
    content = "This is file for test of tar-out."
    path = params.get("gf_temp_file", "/tmp/test_tar_out")
    file_dir = os.path.dirname(path)
    path_on_host = os.path.join(data_dir.get_tmp_dir(), "test_tar_out.tar")

    params['libvirt_domain'] = vm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # Create file
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")
    logging.info("Create file successfully.")

    # Copy file to host
    tar_out_result = gf.tar_out(file_dir, path_on_host)
    logging.debug(tar_out_result)
    if tar_out_result.exit_status:
        gf.close_session()
        raise error.TestFail("Tar out failed.")
    logging.info("Tar out successfully.")

    # Delete temp file
    rm_result = gf.rm(path)
    logging.debug(rm_result)
    gf.close_session()
    if rm_result.exit_status:
        raise error.TestFail("Rm %s failed." % path)
    logging.info("Rm %s successfully.", path)

    # Uncompress file and check file in it.
    uc_result = utils.run("cd %s && tar xf %s" % (file_dir, path_on_host))
    logging.debug(uc_result)
    try:
        os.remove(path_on_host)
    except IOError, detail:
        raise error.TestFail(str(detail))
    if uc_result.exit_status:
        raise error.TestFail("Uncompress file on host failed.")
    logging.info("Uncompress file on host successfully.")

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


def test_copy_in(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Write a tempfile on host
    3) Copy file to guest with copy-in
    4) Delete created file
    5) Check file on guest
    """
    content = "This is file for test of copy-in."
    path = params.get("gf_temp_file", "/tmp/test_copy_in")
    path_dir = os.path.dirname(path)

    # Create a file on host
    try:
        open(path, 'w').write(content)
    except IOError, detail:
        raise error.TestNAError("Prepare file on host failed:%s" % detail)

    params['libvirt_domain'] = vm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # Copy file to guest
    copy_in_result = gf.copy_in(path, path_dir)
    logging.debug(copy_in_result)

    # Delete file on host
    try:
        os.remove(path)
    except IOError, detail:
        logging.error(detail)

    if copy_in_result.exit_status:
        gf.close_session()
        raise error.TestFail("Copy in failed.")
    logging.info("Copy in successfully.")

    # Cat file on guest
    cat_result = gf.cat(path)
    rm_result = gf.rm(path)
    gf.close_session()
    logging.debug(cat_result)
    logging.debug(rm_result)
    if cat_result.exit_status:
        raise error.TestFail("Cat file failed.")
    else:
        if not re.search(content, cat_result.stdout):
            raise error.TestFail("Catted file do not match")
    if rm_result.exit_status:
        raise error.TestFail("Rm file failed.")
    logging.info("Rm %s successfully.", path)


def test_copy_out(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Write a tempfile to guest
    3) Copy file to host with copy-out
    4) Delete created file
    5) Check file on host
    """
    content = "This is file for test of copy-out."
    path = params.get("gf_temp_file", "/tmp/test_copy_out")
    path_dir = os.path.dirname(path)

    params['libvirt_domain'] = vm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # Create file
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")
    logging.info("Create file successfully.")

    # Copy file to host
    copy_out_result = gf.copy_out(path, path_dir)
    logging.debug(copy_out_result)
    if copy_out_result.exit_status:
        gf.close_session()
        raise error.TestFail("Copy out failed.")
    logging.info("Copy out successfully.")

    # Delete temp file
    rm_result = gf.rm(path)
    logging.debug(rm_result)
    gf.close_session()
    if rm_result.exit_status:
        raise error.TestFail("Rm %s failed." % path)
    logging.info("Rm %s successfully.", path)

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


def run(test, params, env):
    """
    Test guestfs with file commands: tar-in, tar-out, copy-in, copy-out
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("gf_file_operation")
    testcase = globals()["test_%s" % operation]
    testcase(vm, params)
