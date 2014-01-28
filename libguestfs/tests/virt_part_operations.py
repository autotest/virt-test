import re
import os
import logging
import commands
from autotest.client.shared import error, utils
from virttest import virt_vm, data_dir, remote, aexpect
from virttest import utils_test, utils_misc


def test_unformatted_part(vm, params):
    """
    1) Do some necessary check
    2) Format additional disk without filesystem type
    3) Try to mount device
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_lgf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                              ignore_status=True).stdout.strip()

    device_part = "%s1" % device_in_lgf
    # Mount specific partition
    params['special_mountpoints'] = [device_part]
    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    # Default vm_ref is oldvm, so switch it.
    vm_ref = vt.newvm.name

    # Format disk
    format_result = vt.format_disk()
    if format_result.exit_status:
        raise error.TestFail("Format added disk failed.")
    logging.info("Format added disk successfully.")

    # List filesystems detail
    list_fs_detail = vt.get_filesystems_info(vm_ref)
    if list_fs_detail.exit_status:
        raise error.TestFail("List filesystems detail failed:"
                             "%s" % list_fs_detail)
    logging.info("List filesystems detail successfully.")

    mountpoint = params.get("vt_mountpoint", "/mnt")
    mounts, mounto = vt.guestmount(mountpoint, vm_ref)
    if utils_misc.umount("", mountpoint, "") and mounts:
        raise error.TestFail("Mount vm's filesytem successfully, "
                             "but not expected.")
    logging.info("Mount vm's filesystem failed as expected.")


def test_formatted_part(vm, params):
    """
    1) Do some necessary check
    2) Format additional disk with specific filesystem
    3) Try to write a file to mounted device and get md5
    4) Login to check writed file and its md5
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_lgf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                              ignore_status=True).stdout.strip()
    if utils_test.libguestfs.primary_disk_virtio(vm):
        device_in_vm = add_device
    else:
        device_in_vm = "/dev/vda"

    device_part = "%s1" % device_in_lgf
    device_part_in_vm = "%s1" % device_in_vm
    # Mount specific partition
    params['special_mountpoints'] = [device_part]
    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    # Default vm_ref is oldvm, so switch it.
    vm_ref = vt.newvm.name

    # Format disk
    format_result = vt.format_disk(filesystem="ext3", partition="mbr")
    if format_result.exit_status:
        raise error.TestFail("Format added disk failed.")
    logging.info("Format added disk successfully.")

    # List filesystems detail
    list_fs_detail = vt.get_filesystems_info(vm_ref)
    if list_fs_detail.exit_status:
        raise error.TestFail("List filesystems detail failed.")
    logging.info("List filesystems detail successfully.")

    content = "This is file for formatted part test."
    path = params.get("temp_file", "formatted_part")
    mountpoint = params.get("vt_mountpoint", "/mnt")

    writes, writeo = vt.write_file_with_guestmount(mountpoint, path,
                                                   content, vm_ref,
                                                   cleanup=False)
    if writes is False:
        utils_misc.umount("", mountpoint, "")
        raise error.TestFail("Write file to mounted filesystem failed.")
    logging.info("Create %s successfully.", writeo)

    # Compute new file's md5
    if os.path.isfile(writeo):
        md5s, md5o = commands.getstatusoutput("md5sum %s" % writeo)
        utils_misc.umount("", mountpoint, "")
        if md5s:
            raise error.TestFail("Compute %s's md5 failed." % writeo)
        md5 = md5o.split()[0].strip()
        logging.debug("%s's md5 in newvm is:%s", writeo, md5)
    else:
        utils_misc.umount("", mountpoint, "")
        raise error.TestFail("Can not find %s." % writeo)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
    except Exception, detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        file_path = os.path.join(mountpoint, path)
        mounts = session.cmd_status("mount %s %s" % (device_part_in_vm,
                                    mountpoint), timeout=10)
        if mounts:
            logging.error("Mount device in vm failed.")
        md51 = session.cmd_output("md5sum %s" % file_path)
        logging.debug(md51)
        if not re.search(md5o, md51):
            attached_vm.destroy()
            attached_vm.wait_for_shutdown()
            raise error.TestFail("Got a different md5.")
        logging.info("Got matched md5.")
        session.cmd_status("cat %s" % file_path, timeout=5)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        if not re.search(content, str(detail)):
            raise error.TestFail(str(detail))
    logging.info("Check file on guest successfully.")


def run(test, params, env):
    """
    Test partition operations with virt-format.
    """
    vm_name = params.get("main_vm")
    new_vm_name = params.get("gf_updated_new_vm")
    vm = env.get_vm(vm_name)

    # To make sure old vm is down
    if vm.is_alive():
        vm.destroy()

    operation = params.get("vt_part_operation")
    testcase = globals()["test_%s" % operation]
    try:
        # Create a new vm for editing and easier cleanup :)
        utils_test.libguestfs.define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        disk_path = os.path.join(data_dir.get_tmp_dir(),
                                 params.get("gf_updated_target_dev"))
        utils_test.libguestfs.cleanup_vm(new_vm_name, disk_path)
