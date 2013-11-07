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


def primary_disk_virtio(vm):
    """
    To verify if system disk is virtio.

    :param vm: Libvirt VM object.
    """
    vmdisks = vm.get_disk_devices()
    if "vda" in vmdisks.keys():
        return True
    return False


def attach_additional_disk(vm, disksize, targetdev):
    """
    Create a disk with disksize, then attach it to given vm.

    :param vm: Libvirt VM object.
    :param disksize: size of attached disk
    :param targetdev: target of disk device
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

    def get_root(self):
        """
        Get root filesystem w/ guestfish
        """
        getroot_result = self.inspect_os()
        roots_list = getroot_result.stdout.splitlines()
        if getroot_result.exit_status or not len(roots_list):
            logging.error("Get root failed:%s", getroot_result)
            return (False, getroot_result)
        return (True, roots_list[0].strip())

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

    def get_bootable_part(self, device="/dev/sda"):
        status, partitions = self.get_partitions_info(device)
        if status is False:
            return (False, partitions)
        for partition in partitions.values():
            num = partition.get("num")
            ba_result = self.part_get_bootable(device, num)
            if ba_result.stdout.strip() == "true":
                return (True, "%s%s" % (device, num))
        return (False, partitions)

    def get_mbr_id(self, device="/dev/sda"):
        status, partitions = self.get_partitions_info(device)
        if status is False:
            return (False, partitions)
        for partition in partitions.values():
            num = partition.get("num")
            mbr_id_result = self.part_get_mbr_id(device, num)
            if mbr_id_result.exit_status == 0:
                return (True, mbr_id_result.stdout.strip())
        return (False, partitions)

    def get_part_type(self, device="/dev/sda"):
        part_type_result = self.part_get_parttype(device)
        if part_type_result.exit_status:
            return (False, part_type_result)
        return (True, part_type_result.stdout.strip())

    def get_md5(self, path):
        """
        Get files md5 value.
        """
        logging.info("Computing %s's md5...", path)
        md5_result = self.checksum("md5", path)
        if md5_result.exit_status:
            logging.error("Check %s's md5 failed:%s", path, md5_result)
            return (False, md5_result)
        return (True, md5_result.stdout.strip())

    def create_msdos_part(self, device, start="1", end="-1"):
        """
        Create a msdos partition in given device.
        Default partition section is whole disk(1~-1).
        And return its part name if part add succeed.
        """
        logging.info("Creating a new partition on %s...", device)
        init_result = self.part_init(device, "msdos")
        if init_result.exit_status:
            logging.error("Init disk failed:%s", init_result)
            return (False, init_result)
        add_result = self.part_add(device, "p", start, end)
        if add_result.exit_status:
            logging.error("Add a partition failed:%s", add_result)
            return (False, add_result)

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

        return (True, part_num)

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

        return (True, part_num)


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
    if primary_disk_virtio(vm):
        device_in_vm = add_device
    else:
        device_in_vm = "/dev/vda"
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)

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

    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)

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
    if primary_disk_virtio(vm):
        device_in_vm = add_device
    else:
        device_in_vm = "/dev/vda"

    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    # Get root filesystem before test
    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)

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
    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)

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

    vt = VirtTools(vm, params)
    # Create a new vm with additional disk
    vt.update_vm_disk()

    params['libvirt_domain'] = vt.newvm.name
    params['gf_inspector'] = True
    gf = GuestfishTools(params)

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
        cleanup_vm(vt.newvm.name)
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
        define_new_vm(vm_name, new_vm_name)
        testcase(vm, params)
    finally:
        disk_path = os.path.join(data_dir.get_tmp_dir(),
                                 params.get("gf_updated_target_dev"))
        cleanup_vm(new_vm_name, disk_path)
