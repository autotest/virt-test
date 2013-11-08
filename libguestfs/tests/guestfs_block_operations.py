import re
import os
import logging
import commands
from autotest.client.shared import error, utils
from virttest import virsh, virt_vm, libvirt_vm, data_dir, remote, aexpect
from virttest.libvirt_xml import vm_xml, xcepts
from virttest import utils_libguestfs as lgf


class VTError(Exception):
    pass


class VTAttachError(VTError):

    def __init__(self, cmd, output):
        super(VTAttachError, self).__init__(cmd, output)
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return ("Attach command failed:%s\n%s" % (self.cmd, self.output))


def cleanup_vm(vm_name=None, disk=None):
    """
    Cleanup the vm with its disk deleted.
    """
    try:
        if vm_name is not None:
            virsh.undefine(vm_name)
    except error.CmdError:
        pass
    try:
        if disk is not None:
            os.remove(disk)
    except IOError:
        pass


def get_primary_disk(vm):
    """
    Get primary disk source.

    @param vm: Libvirt VM object.
    """
    vmdisks = vm.get_disk_devices()
    if len(vmdisks):
        pri_target = ['vda', 'sda']
        for target in pri_target:
            try:
                return vmdisks[target]['source']
            except KeyError:
                pass
    return None


def attach_additional_disk(vm, disksize, targetdev):
    """
    Create a disk with disksize, then attach it to given vm.

    @param vm: Libvirt VM object.
    @param disksize: size of attached disk
    @param targetdev: target of disk device
    """
    logging.info("Attaching disk...")
    disk_path = os.path.join(data_dir.get_tmp_dir(), targetdev)
    cmd = "qemu-img create %s %s" % (disk_path, disksize)
    status, output = commands.getstatusoutput(cmd)
    if status:
        return (False, output)

    # To confirm attached device do not exist.
    virsh.detach_disk(vm.name, targetdev, extra="--config")

    attach_result = virsh.attach_disk(vm.name, disk_path, targetdev,
                                      extra="--config", debug=True)
    if attach_result.exit_status:
        return (False, attach_result)
    return (True, disk_path)


def define_new_vm(vm_name, new_name):
    """
    Just define a new vm from given name
    """
    try:
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
        vmxml.vm_name = new_name
        del vmxml.uuid
        logging.debug(str(vmxml))
        vmxml.define()
        return True
    except xcepts.LibvirtXMLError, detail:
        logging.error(detail)
        return False


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


class VirtTools(object):

    """
    Useful functions for virt-commands.

    Some virt-tools need an input disk and output disk.
    Main for virt-clone, virt-sparsify, virt-resize.
    """

    def __init__(self, vm, params):
        self.params = params
        self.oldvm = vm
        # Many command will create a new vm or disk, init it here
        self.newvm = libvirt_vm.VM("VTNEWVM", vm.params, vm.root_dir,
                                   vm.address_cache)
        # Preapre for created vm disk
        self.indisk = get_primary_disk(vm)
        self.outdisk = None

    def update_vm_disk(self):
        """
        Update oldvm's disk, and then create a newvm.
        """
        target_dev = self.params.get("gf_updated_target_dev", "vdb")
        device_size = self.params.get("gf_updated_device_size", "50M")
        self.newvm.name = self.params.get("gf_updated_new_vm")
        if self.newvm.is_alive():
            self.newvm.destroy()
            self.newvm.wait_for_shutdown()

        attachs, attacho = attach_additional_disk(self.newvm,
                                                  disksize=device_size,
                                                  targetdev=target_dev)
        if attachs:
            # Restart vm for guestfish command
            # Otherwise updated disk is not visible
            try:
                self.newvm.start()
                self.newvm.wait_for_login()
                self.newvm.destroy()
                self.newvm.wait_for_shutdown()
                self.params['added_disk_path'] = attacho
            except virt_vm.VMError, detail:
                raise VTAttachError("", str(detail))
        else:
            raise VTAttachError("", attacho)


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful Tools for Guestfish class."""

    __slots__ = ('params', )

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = params.get("gf_ro_mode", False)
        libvirt_domain = params.get("libvirt_domain")
        inspector = params.get("gf_inspector", False)
        mount_options = params.get("mount_options")
        super(GuestfishTools, self).__init__(disk_img, ro_mode,
                                             libvirt_domain, inspector,
                                             mount_options=mount_options)

    def get_partitions_info(self, device="/dev/sda"):
        """
        Get disk partition's information.
        """
        list_result = self.part_list(device)
        if list_result.exit_status:
            logging.error("List partition info failed:%s", list_result)
            return (False, list_result)
        list_lines = list_result.stdout.splitlines()
        # This dict is a struct like this: {key:{a dict}, key:{a dict}}
        partitions = {}
        # This dict is a struct of normal dict, for temp value of a partition
        part_details = {}
        index = -1
        for line in list_lines:
            # Init for a partition
            if re.search("\[\d\]\s+=", line):
                index = line.split("]")[0].split("[")[-1]
                part_details = {}
                partitions[index] = part_details

            if re.search("part_num", line):
                part_num = int(line.split(":")[-1].strip())
                part_details['num'] = part_num
            elif re.search("part_start", line):
                part_start = int(line.split(":")[-1].strip())
                part_details['start'] = part_start
            elif re.search("part_end", line):
                part_end = int(line.split(":")[-1].strip())
                part_details['end'] = part_end
            elif re.search("part_size", line):
                part_size = int(line.split(":")[-1].strip())
                part_details['size'] = part_size

            if index != -1:
                partitions[index] = part_details
        logging.info(partitions)
        return (True, partitions)

    def create_whole_disk_msdos_part(self, device):
        """
        Create only one msdos partition in given device.
        And return its part name if part add succeed.
        """
        logging.info("Creating one partition of whole %s...", device)
        init_result = self.part_init(device, "msdos")
        if init_result.exit_status:
            logging.error("Init disk failed:%s", init_result)
            return (False, init_result)
        disk_result = self.part_disk(device, "msdos")
        if disk_result.exit_status:
            logging.error("Init disk failed:%s", disk_result)
            return (False, disk_result)

        # Get latest created part num to return
        status, partitions = self.get_partitions_info(device)
        if status is False:
            return (False, partitions)
        part_num = -1
        for partition in partitions.values():
            cur_num = partition.get("num")
            if cur_num > part_num:
                part_num = cur_num

        if part_num == -1:
            return (False, partitions)

        part_name = "%s%s" % (device, part_num)
        return (True, part_name)


def test_blockdev_info(vm, params):
    """
    1) Fall into guestfish session w/ inspector
    2) Do some necessary check
    3) Format additional disk with part-disk
    4) Get block information
    5) Login guest to check
    """
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    device = params.get("gf_additional_device", "/dev/vdb")

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)
    prepare_attached_device(gf, device)

    # Get sectorsize of block device
    getss_result = gf.blockdev_getss(device)
    logging.debug(getss_result)
    if getss_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get sectionsize failed")
    sectorsize = str(getss_result.stdout.strip())
    logging.info("Get sectionsize successfully.")

    # Get total size of device in 512-byte sectors
    getsz_result = gf.blockdev_getsz(device)
    logging.debug(getsz_result)
    if getsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get device size failed.")
    total_size = str(getsz_result.stdout.strip())
    logging.info("Get device size successfully.")

    # Get blocksize of device
    getbsz_result = gf.blockdev_getbsz(device)
    logging.debug(getbsz_result)
    if getbsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get blocksize failed.")
    blocksize = str(getbsz_result.stdout.strip())
    logging.info("Get blocksize successfully.")

    # Get total size in bytes
    getsize64_result = gf.blockdev_getsize64(device)
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
        sectorsize2 = session.cmd_output("blockdev --getss %s" % device,
                                         timeout=10).strip()
        total_size2 = session.cmd_output("blockdev --getsz %s" % device,
                                         timeout=5).strip()
        blocksize2 = session.cmd_output("blockdev --getbsz %s" % device,
                                        timeout=5).strip()
        total_size_in_bytes2 = session.cmd_output(
            "blockdev --getsize64 %s" % device,
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
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    device = params.get("gf_additional_device", "/dev/vdb")

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)
    prepare_attached_device(gf, device)

    # Get blocksize of device
    getbsz_result = gf.blockdev_getbsz(device)
    logging.debug(getbsz_result)
    if getbsz_result.exit_status:
        gf.close_session()
        raise error.TestFail("Get blocksize failed.")
    blocksize = str(getbsz_result.stdout.strip())
    logging.info("Get blocksize successfully.")

    # Set blocksize of device to half
    setbsz_result = gf.blockdev_setbsz(device, int(blocksize) / 2)
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
        blocksize2 = session.cmd_output("blockdev --getbsz %s" % device,
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
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    device = params.get("gf_additional_device", "/dev/vdb")

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)
    part_name = prepare_attached_device(gf, device)

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
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()
    device = params.get("gf_additional_device", "/dev/vdb")

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)
    part_name = prepare_attached_device(gf, device)

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
    gf = GuestfishTools(params)
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
        session.cmd_status("mount %s %s" % (part_name, mountpoint),
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


def run_guestfs_block_operations(test, params, env):
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
        define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        cleanup_vm(new_vm_name)
