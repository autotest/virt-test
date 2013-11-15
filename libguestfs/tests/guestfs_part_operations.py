import re
import os
import logging
from autotest.client.shared import error, utils
from virttest import virt_vm, data_dir, remote, aexpect
from virttest import utils_test


def test_formatted_part(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk
    4) Try to write a file to mounted device
    5) Login to check written file
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()
    if utils_test.libguestfs.primary_disk_virtio(vm):
        device_in_vm = add_device
    else:
        device_in_vm = "/dev/vda"
    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device_in_gf, list_dev_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = gf.create_msdos_part(device_in_gf)
    if creates is False:
        gf.close_session()
        raise error.TestFail(createo)
    part_name_in_vm = "%s%s" % (device_in_vm, createo)
    part_name_in_gf = "%s%s" % (device_in_gf, createo)
    logging.info("Create partition successfully.")

    mkfs_result = gf.mkfs("ext3", part_name_in_gf)
    logging.debug(mkfs_result)
    if mkfs_result.exit_status:
        gf.close_session()
        raise error.TestFail("Format %s Failed" % part_name_in_gf)
    logging.info("Format %s successfully.", part_name_in_gf)

    mountpoint = params.get("gf_mountpoint", "/mnt")
    mount_result = gf.mount(part_name_in_gf, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % part_name_in_gf)
    logging.info("Mount %s successfully.", part_name_in_gf)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(part_name_in_gf, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    # Write file
    path = "%s/gf_part_test" % mountpoint
    content = "This is file for test_formatted_part."
    write_result = gf.write(path, content)
    gf.close_session()
    logging.debug(write_result)
    if write_result.exit_status:
        raise error.TestFail("Create file failed.")
    logging.info("Create %s successfully.", path)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        session.cmd_status("mount %s %s" % (part_name_in_vm, mountpoint),
                           timeout=10)
        session.cmd_status("cat %s" % path, timeout=5)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        if not re.search(content, str(detail)):
            raise error.TestFail(str(detail))
    logging.info("Check file on guest successfully.")


def test_unformatted_part(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Init but not format additional disk
    4) Try to mount device
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device_in_gf, list_dev_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = gf.create_msdos_part(device_in_gf)
    if creates is False:
        gf.close_session()
        raise error.TestFail(createo)
    part_name_in_gf = "%s%s" % (device_in_gf, createo)
    logging.info("Create partition successfully.")

    mountpoint = params.get("gf_mountpoint", "/mnt")
    mount_result = gf.mount(part_name_in_gf, mountpoint)
    gf.close_session()
    logging.debug(mount_result)
    if mount_result.exit_status == 0:
        raise error.TestFail("Mount %s successfully." % part_name_in_gf)
    else:
        if not re.search("[filesystem|fs] type", mount_result.stdout):
            raise error.TestFail("Unknown error.")


def test_formatted_disk(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Try to write a file to mounted device
    5) Login to check writed file
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()
    if utils_test.libguestfs.primary_disk_virtio(vm):
        device_in_vm = add_device
    else:
        device_in_vm = "/dev/vda"

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device_in_gf, list_dev_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = gf.create_whole_disk_msdos_part(device_in_gf)
    if creates is False:
        gf.close_session()
        raise error.TestFail(createo)
    part_name_in_vm = "%s%s" % (device_in_vm, createo)
    part_name_in_gf = "%s%s" % (device_in_gf, createo)
    logging.info("Create partition successfully.")

    mkfs_result = gf.mkfs("ext3", part_name_in_gf)
    logging.debug(mkfs_result)
    if mkfs_result.exit_status:
        gf.close_session()
        raise error.TestFail("Format %s Failed" % part_name_in_gf)
    logging.info("Format %s successfully.", part_name_in_gf)

    mountpoint = params.get("gf_mountpoint", "/mnt")
    mount_result = gf.mount(part_name_in_gf, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % part_name_in_gf)
    logging.info("Mount %s successfully.", part_name_in_gf)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(part_name_in_gf, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    # Write file
    path = "%s/gf_part_test" % mountpoint
    content = "This is file for test_formatted_disk."
    write_result = gf.write(path, content)
    gf.close_session()
    logging.debug(write_result)
    if write_result.exit_status:
        raise error.TestFail("Create file failed.")
    logging.info("Create %s successfully.", path)

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        session.cmd_status("mount %s %s" % (part_name_in_vm, mountpoint),
                           timeout=10)
        session.cmd_status("cat %s" % path, timeout=5)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        if not re.search(content, str(detail)):
            raise error.TestFail(str(detail))
    logging.info("Check file on guest successfully.")


def test_partition_info(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Get part info with part-get-bootable and part-get-parttype
    """
    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # List partitions
    list_part_result = gf.list_partitions()
    if list_part_result.exit_status:
        gf.close_session()
        raise error.TestFail("List partitions failed:%s" % list_part_result)
    logging.info("List partitions successfully.")

    getbas, getbao = gf.get_bootable_part()
    logging.debug("Bootable info:%s", getbao)
    if getbas is False:
        gf.close_session()
        raise error.TestFail("Get bootable failed.")

    getmbrids, getmbrido = gf.get_mbr_id()
    logging.debug("Get mbr id:%s", getmbrido)
    if getmbrids is False:
        gf.close_session()
        raise error.TestFail("Get mbr id failed.")

    getpts, getpto = gf.get_part_type()
    logging.debug("Get parttype:%s", getpto)
    gf.close_session()
    if getpts is False:
        raise error.TestFail("Get parttype failed.")


def test_fscked_partition(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Try to write a file to mounted device and get its md5
    5) Do fsck to new added partition
    """
    add_device = params.get("gf_additional_device", "/dev/vdb")
    device_in_gf = utils.run("echo %s | sed -e 's/vd/sd/g'" % add_device,
                             ignore_status=True).stdout.strip()

    vt = utils_test.libguestfs.VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)

    # List devices
    list_dev_result = gf.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        gf.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device_in_gf, list_dev_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = gf.create_whole_disk_msdos_part(device_in_gf)
    if creates is False:
        gf.close_session()
        raise error.TestFail(createo)
    part_name_in_gf = "%s%s" % (device_in_gf, createo)
    logging.info("Create partition successfully.")

    mkfs_result = gf.mkfs("ext3", part_name_in_gf)
    logging.debug(mkfs_result)
    if mkfs_result.exit_status:
        gf.close_session()
        raise error.TestFail("Format %s Failed" % part_name_in_gf)
    logging.info("Format %s successfully.", part_name_in_gf)

    mountpoint = params.get("gf_mountpoint", "/mnt")
    mount_result = gf.mount(part_name_in_gf, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % part_name_in_gf)
    logging.info("Mount %s successfully.", part_name_in_gf)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(part_name_in_gf, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    # Write file
    path = "%s/gf_part_test" % mountpoint
    content = "This is file for test_fscked_partition."
    write_result = gf.write(path, content)
    logging.debug(write_result)
    if write_result.exit_status:
        gf.close_session()
        raise error.TestFail("Create file failed.")
    logging.info("Create %s successfully.", path)

    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    md5_old = md5o.strip()
    logging.debug("%s's md5 in oldvm is:%s", path, md5_old)

    # Do fsck
    fsck_result = gf.fsck("ext3", part_name_in_gf)
    logging.debug(fsck_result)
    if fsck_result.exit_status:
        raise error.TestFail("Do fsck to %s failed." % part_name_in_gf)
    logging.info("Do fsck to %s successfully.", part_name_in_gf)

    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_new = md5o.strip()
    logging.debug("%s's md5 in newvm is:%s", path, md5_new)

    if md5_old != md5_new:
        raise error.TestFail("Md5 of new vm is not match with old one.")


def run_guestfs_part_operations(test, params, env):
    """
    Test guestfs with partition commands.
    """
    vm_name = params.get("main_vm")
    new_vm_name = params.get("gf_updated_new_vm")
    vm = env.get_vm(vm_name)

    # To make sure old vm is down
    if vm.is_alive():
        vm.destroy()

    operation = params.get("gf_part_operation")
    testcase = globals()["test_%s" % operation]
    try:
        # Create a new vm for editing and easier cleanup :)
        utils_test.libguestfs.define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        disk_path = os.path.join(data_dir.get_tmp_dir(),
                                 params.get("gf_updated_target_dev"))
        utils_test.libguestfs.cleanup_vm(new_vm_name, disk_path)
