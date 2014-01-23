import re
import logging
from autotest.client.shared import error, utils
from virttest import virt_vm, remote, aexpect
from virttest import utils_test


def prepare_attached_device(guestfs, device):
    """
    Prepare attached device for block test.

    :param guestfs: instance of GuestfishTools
    :param device: attached device
    """
    # List devices
    list_dev_result = guestfs.list_devices()
    logging.debug(list_dev_result)
    if list_dev_result.exit_status:
        guestfs.close_session()
        raise error.TestFail("List devices failed")
    else:
        if not re.search(device, list_dev_result.stdout):
            guestfs.close_session()
            raise error.TestFail("Did not find additional device.")
    logging.info("List devices successfully.")

    creates, createo = guestfs.create_whole_disk_msdos_part(device)
    if creates is False:
        guestfs.close_session()
        raise error.TestFail(createo)
    logging.info("Create partition successfully.")
    return createo


def test_blockdev_info(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Get block information
    5) Login guest to check
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

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    prepare_attached_device(gf, device_in_gf)

    # Get sectorsize of block device
    getss_result = gf.blockdev_getss(device_in_gf)
    logging.debug(getss_result)
    if getss_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get sectionsize failed")
    sectorsize = str(getss_result.stdout.strip())
    logging.info("Get sectionsize successfully.")

    # Get total size of device in 512-byte sectors
    getsz_result = gf.blockdev_getsz(device_in_gf)
    logging.debug(getsz_result)
    if getsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get device size failed.")
    total_size = str(getsz_result.stdout.strip())
    logging.info("Get device size successfully.")

    # Get blocksize of device
    getbsz_result = gf.blockdev_getbsz(device_in_gf)
    logging.debug(getbsz_result)
    if getbsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get blocksize failed.")
    blocksize = str(getbsz_result.stdout.strip())
    logging.info("Get blocksize successfully.")

    # Get total size in bytes
    getsize64_result = gf.blockdev_getsize64(device_in_gf)
    gf.close_session()
    logging.debug(getsize64_result)
    if getsize64_result.exit_status:
        raise error.TestFail("Get device size in bytes failed.")
    total_size_in_bytes = str(getsize64_result.stdout.strip())
    logging.info("Get device size in bytes successfully")

    logging.info("Block device information in guestfish:\n"
                 "Sectorsize:%s\n"
                 "Totalsize:%s\n"
                 "Blocksize:%s\n"
                 "Totalsize_bytes:%s"
                 % (sectorsize, total_size, blocksize, total_size_in_bytes))

    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        sectorsize2 = session.cmd_output("blockdev --getss %s" % device_in_vm,
                                         timeout=10).strip()
        total_size2 = session.cmd_output("blockdev --getsz %s" % device_in_vm,
                                         timeout=5).strip()
        blocksize2 = session.cmd_output("blockdev --getbsz %s" % device_in_vm,
                                        timeout=5).strip()
        total_size_in_bytes2 = session.cmd_output(
            "blockdev --getsize64 %s" % device_in_vm,
            timeout=5).strip()
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    logging.info("Blockdev information in vm:\n"
                 "Sectorsize:%s\n"
                 "Totalsize:%s\n"
                 "Blocksize:%s\n"
                 "Totalsize_bytes:%s"
                 % (sectorsize2, total_size2, blocksize2,
                    total_size_in_bytes2))

    fail_info = []
    if sectorsize != sectorsize2:
        fail_info.append("Sectorsize do not match.")
    if total_size != total_size2:
        fail_info.append("Total size do not match.")
    if blocksize != blocksize2:
        fail_info.append("Blocksize do not match.")
    if total_size_in_bytes != total_size_in_bytes2:
        fail_info.append("Total size in bytes do not match.")
    if len(fail_info):
        raise error.TestFail(fail_info)
    logging.info("Check blockdev information on guest successfully.")


def test_blocksize(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Get blocksize and set blocksize
    5) Login guest to check
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

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    prepare_attached_device(gf, device_in_gf)

    # Get blocksize of device
    getbsz_result = gf.blockdev_getbsz(device_in_gf)
    logging.debug(getbsz_result)
    if getbsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get blocksize failed.")
    blocksize = str(getbsz_result.stdout.strip())
    logging.info("Get blocksize successfully.")

    # Set blocksize of device to half
    setbsz_result = gf.blockdev_setbsz(device_in_gf, int(blocksize) / 2)
    logging.debug(setbsz_result)
    gf.close_session()
    if setbsz_result.exit_status:
        raise error.TestFail("Set blocksize failed.")
    logging.info("Set blocksize successfully.")

    # Login in guest
    attached_vm = vt.newvm
    try:
        attached_vm.start()
        session = attached_vm.wait_for_login()
    except (virt_vm.VMError, remote.LoginError), detail:
        attached_vm.destroy()
        raise error.TestFail(str(detail))

    try:
        blocksize2 = session.cmd_output("blockdev --getbsz %s" % device_in_vm,
                                        timeout=5).strip()
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        raise error.TestFail(str(detail))

    if blocksize2.isdigit():
        if blocksize != int(blocksize2) * 2:
            raise error.TestFail("\nSet blocksize failed:\n"
                                 "Original:%s\n"
                                 "Current:%s" % (blocksize, blocksize2))
    else:
        raise error.TestFail(blocksize2)
    logging.info("Check blocksize in guest successfully.")


def test_blockdev_ro(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Get disk readonly status and set it.
    5) Try to write a file to readonly disk
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
    part_num = prepare_attached_device(gf, device_in_gf)
    part_name = "%s%s" % (device_in_gf, part_num)

    mkfs_result = gf.mkfs("ext3", part_name)
    logging.debug(mkfs_result)
    if mkfs_result.exit_status:
        gf.close_session()
        raise error.TestFail("Format %s Failed" % part_name)
    logging.info("Format %s successfully.", part_name)

    # Get readonly status
    getro_result = gf.blockdev_getro(part_name)
    logging.debug(getro_result)
    if getro_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get readonly status failed.")
    logging.info("Get readonly status successfully.")

    if getro_result.stdout.strip() == "true":
        logging.info("Partition %s is readonly already.", part_name)
    else:
        setro_result = gf.blockdev_setro(part_name)
        logging.debug(setro_result)
        if setro_result.exit_status:
            gf.close_session()
            raise error.TestFail("Set readonly status failed.")
        logging.info("Set readonly status successfully.")

        # Check readonly status
        getro_result = gf.blockdev_getro(part_name)
        logging.debug(getro_result)
        if getro_result.stdout.strip() == "false":
            gf.close_session()
            raise error.TestFail("Check readonly status failed.")

    mountpoint = params.get("mountpoint", "/mnt")
    mount_result = gf.mount(part_name, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % part_name)
    logging.info("Mount %s successfully.", part_name)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(part_name, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    # Write file
    path = "%s/gf_block_test" % mountpoint
    content = "This is file for test_blockdev_ro."
    write_result = gf.write(path, content)
    gf.close_session()
    logging.debug(write_result)
    if write_result.exit_status == 0:
        raise error.TestFail("Create file to readonly disk successfully!")
    logging.info("Create %s failed as expected.", path)


def test_blockdev_rw(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Get partition readonly status and set it.
    5) Set rw for disk
    6) Write file to rw device
    7) Login vm to check file
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

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = utils_test.libguestfs.GuestfishTools(params)
    part_num = prepare_attached_device(gf, device_in_gf)
    part_name = "%s%s" % (device_in_gf, part_num)
    part_name_in_vm = "%s%s" % (device_in_vm, part_num)

    mkfs_result = gf.mkfs("ext3", part_name)
    logging.debug(mkfs_result)
    if mkfs_result.exit_status:
        gf.close_session()
        raise error.TestFail("Format %s Failed" % part_name)
    logging.info("Format %s successfully.", part_name)

    # Get readonly status
    getro_result = gf.blockdev_getro(part_name)
    logging.debug(getro_result)
    if getro_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get readonly status failed.")
    logging.info("Get readonly status successfully.")

    if getro_result.stdout.strip() == "true":
        logging.info("Paritition %s is readonly already.", part_name)
    else:
        setro_result = gf.blockdev_setro(part_name)
        logging.debug(setro_result)
        if setro_result.exit_status:
            gf.close_session()
            raise error.TestFail("Set readonly status failed.")
        logging.info("Set readonly status successfully.")

        # Check readonly status
        getro_result = gf.blockdev_getro(part_name)
        logging.debug(getro_result)
        if getro_result.stdout.strip() == "false":
            gf.close_session()
            raise error.TestFail("Check readonly status failed.")

    # Reset device to r/w
    setrw_result = gf.blockdev_setrw(part_name)
    logging.debug(setrw_result)
    if setrw_result.exit_status:
        gf.close_session()
        raise error.TestFail("Set read-write status failed.")
    logging.info("Set read-write status successfully.")

    # Check read-write status
    getro_result = gf.blockdev_getro(part_name)
    logging.debug(getro_result)
    if getro_result.stdout.strip() == "true":
        gf.close_session()
        raise error.TestFail("Check read-write status failed.")

    mountpoint = params.get("mountpoint", "/mnt")
    mount_result = gf.mount(part_name, mountpoint)
    logging.debug(mount_result)
    if mount_result.exit_status:
        gf.close_session()
        raise error.TestFail("Mount %s Failed" % part_name)
    logging.info("Mount %s successfully.", part_name)

    # List mounts
    list_df_result = gf.df()
    logging.debug(list_df_result)
    if list_df_result.exit_status:
        gf.close_session()
        raise error.TestFail("Df failed")
    else:
        if not re.search(part_name, list_df_result.stdout):
            gf.close_session()
            raise error.TestFail("Did not find mounted device.")
    logging.info("Df successfully.")

    # Write file
    path = "%s/gf_block_test" % mountpoint
    content = "This is file for test_blockdev_rw."
    write_result = gf.write(path, content)
    gf.close_session()
    logging.debug(write_result)
    if write_result.exit_status:
        raise error.TestFail("Create file to read-write disk failed.")
    logging.info("Create %s successfully.", path)

    # Login in guest
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
        # Delete file
        session.sendline("rm -f %s" % path)
        attached_vm.destroy()
        attached_vm.wait_for_shutdown()
    except (virt_vm.VMError, remote.LoginError, aexpect.ShellError), detail:
        if attached_vm.is_alive():
            attached_vm.destroy()
        if not re.search(content, str(detail)):
            raise error.TestFail(str(detail))


def run(test, params, env):
    """
    Test guestfs with block commands.
    """
    vm_name = params.get("main_vm")
    new_vm_name = params.get("gf_updated_new_vm")
    vm = env.get_vm(vm_name)

    # To make sure old vm is down
    if vm.is_alive():
        vm.destroy()

    operation = params.get("gf_block_operation")
    testcase = globals()["test_%s" % operation]
    try:
        # Create a new vm for editing and easier cleanup :)
        utils_test.libguestfs.define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        utils_test.libguestfs.cleanup_vm(new_vm_name)
