import re
import os
import logging
import commands
from autotest.client.shared import error, utils
from virttest import virsh, virt_vm, libvirt_vm, data_dir, utils_net
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


def primary_disk_virtio(vm):
    """
    To verify if system disk is virtio.

    :param vm: Libvirt VM object.
    """
    vmdisks = vm.get_disk_devices()
    if "vda" in vmdisks.keys():
        return True
    return False


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

    def clone_vm_filesystem(self, newname=None):
        """
        Clone a new vm with only its filesystem disk.

        @param newname:if newname is None,
                       create a new name with clone added.
        """
        logging.info("Cloning...")
        # Init options for virt-clone
        options = {}
        autoclone = bool(self.params.get("autoclone", False))
        new_filesystem_path = self.params.get("new_filesystem_path")
        cloned_files = []
        if new_filesystem_path:
            self.outdisk = new_filesystem_path
        elif self.indisk is not None:
            self.outdisk = "%s-clone" % self.indisk
        cloned_files.append(self.outdisk)
        options['files'] = cloned_files
        # cloned_mac can be CREATED, RANDOM or a string.
        cloned_mac = self.params.get("cloned_mac", "CREATED")
        if cloned_mac == "CREATED":
            options['mac'] = utils_net.generate_mac_address_simple()
        else:
            options['mac'] = cloned_mac

        options['ignore_status'] = True
        options['debug'] = True
        options['timeout'] = int(self.params.get("timeout", 240))
        if newname is None:
            newname = "%s-virtclone" % self.oldvm.name
        result = lgf.virt_clone_cmd(self.oldvm.name, newname,
                                    autoclone, **options)
        if result.exit_status:
            error_info = "Clone %s to %s failed." % (self.oldvm.name, newname)
            logging.error(error_info)
            return (False, result)
        else:
            self.newvm.name = newname
            cloned_mac = vm_xml.VMXML.get_first_mac_by_name(newname)
            if cloned_mac is not None:
                self.newvm.address_cache[cloned_mac] = None
            return (True, result)

    def sparsify_disk(self):
        """
        Sparsify a disk
        """
        logging.info("Sparsifing...")
        if self.indisk is None:
            logging.error("No disk can be sparsified.")
            return (False, "Input disk is None.")
        if self.outdisk is None:
            self.outdisk = "%s-sparsify" % self.indisk
        timeout = int(self.params.get("timeout", 240))
        result = lgf.virt_sparsify_cmd(self.indisk, self.outdisk,
                                       ignore_status=True, debug=True,
                                       timeout=timeout)
        if result.exit_status:
            error_info = "Sparsify %s to %s failed." % (self.indisk,
                                                        self.outdisk)
            logging.error(error_info)
            return (False, result)
        return (True, result)

    def define_vm_with_newdisk(self):
        """
        Define the new vm with old vm's configuration

        Changes:
        1.replace name
        2.delete uuid
        3.replace disk
        """
        logging.info("Define a new vm:")
        old_vm_name = self.oldvm.name
        new_vm_name = "%s-vtnewdisk" % old_vm_name
        self.newvm.name = new_vm_name
        old_disk = self.indisk
        new_disk = self.outdisk
        try:
            vmxml = vm_xml.VMXML.new_from_dumpxml(old_vm_name)
            vmxml.vm_name = new_vm_name
            vmxml.uuid = ""
            vmxml.set_xml(re.sub(old_disk, new_disk,
                                 str(vmxml.__dict_get__('xml'))))
            logging.debug(vmxml.__dict_get__('xml'))
            vmxml.define()
        except xcepts.LibvirtXMLError, detail:
            logging.debug(detail)
            return (False, detail)
        return (True, vmxml.xml)

    def expand_vm_filesystem(self, resize_part_num=2, resized_size="+1G",
                             new_disk=None):
        """
        Expand vm's filesystem with virt-resize.
        """
        logging.info("Resizing vm's disk...")
        options = {}
        options['resize'] = "/dev/sda%s" % resize_part_num
        options['resized_size'] = resized_size
        if new_disk is not None:
            self.outdisk = new_disk
        elif self.outdisk is None:
            self.outdisk = "%s-resize" % self.indisk

        options['ignore_status'] = True
        options['debug'] = True
        options['timeout'] = int(self.params.get("timeout", 480))
        result = lgf.virt_resize_cmd(self.indisk, self.outdisk, **options)
        if result.exit_status:
            logging.error(result)
            return (False, result)
        return (True, self.outdisk)

    def guestmount(self, mountpoint, disk_or_domain=None):
        """
        Mount filesystems in a disk or domain to host mountpoint.

        @param disk_or_domain: if it is None, use default vm in params
        """
        logging.info("Mounting filesystems...")
        if disk_or_domain is None:
            disk_or_domain = self.oldvm.name
        if not os.path.isdir(mountpoint):
            os.mkdir(mountpoint)
        if os.path.ismount(mountpoint):
            utils.run("umount -l %s" % mountpoint, ignore_status=True)
        inspector = "yes" == self.params.get("gm_inspector", "yes")
        readonly = "yes" == self.params.get("gm_readonly", "no")
        special_mountpoints = self.params.get("special_mountpoints", [])
        options = {}
        options['ignore_status'] = True
        options['debug'] = True
        options['timeout'] = int(self.params.get("timeout", 240))
        options['special_mountpoints'] = special_mountpoints
        result = lgf.guestmount(disk_or_domain, mountpoint,
                                inspector, readonly, **options)
        if result.exit_status:
            error_info = "Mount %s to %s failed." % (disk_or_domain,
                                                     mountpoint)
            logging.error(result)
            return (False, str(result))
        return (True, mountpoint)

    def write_file_with_guestmount(self, mountpoint, path,
                                   content=None, vm_ref=None):
        """
        Write content to file with guestmount
        """
        logging.info("Creating file...")
        gms, gmo = self.guestmount(mountpoint, vm_ref)
        if gms is True:
            mountpoint = gmo
        else:
            logging.error("Create file %s failed.", path)
            return (False, gmo)

        # file's path on host's mountpoint
        file_path = "%s/%s" % (mountpoint, path)
        if content is None:
            content = "This is a temp file with guestmount."
        try:
            fd = open(file_path, "w")
            fd.write(content)
            fd.close()
        except IOError, detail:
            logging.error(detail)
            return (False, detail)
        logging.info("Create file %s successfully", path)
        # Cleanup created file
        utils.run("rm -f %s" % file_path, ignore_status=True)
        return (True, file_path)


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful Tools for Guestfish class."""

    __slots__ = ('params', )

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = bool(params.get("gf_ro_mode", False))
        libvirt_domain = params.get("libvirt_domain")
        inspector = bool(params.get("gf_inspector", False))
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

    def analyse_release(self):
        """
        Analyse /etc/redhat-release
        """
        logging.info("Analysing /etc/redhat-release...")
        release_result = self.cat("/etc/redhat-release")
        logging.debug(release_result)
        if release_result.exit_status:
            logging.error("Cat /etc/redhat-release failed")
            return (False, release_result)

        release_type = {'rhel': "Red Hat Enterprise Linux",
                        'fedora': "Fedora"}
        for key in release_type:
            if re.search(release_type[key], release_result.stdout):
                return (True, key)


    def write_file(self, path, content):
        """
        Create a new file to vm with guestfish
        """
        logging.info("Creating file %s in vm...", path)
        write_result = self.write(path, content)
        if write_result.exit_status:
            logging.error("Create '%s' with content '%s' failed:%s",
                          path, content, write_result)
            return False
        return True

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

    def get_part_size(self, part_num):
        status, partitions = self.get_partitions_info()
        if status is False:
            return None
        for partition in partitions.values():
            if str(partition.get("num")) == str(part_num):
                return partition.get("size")

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

    def reset_interface(self, iface_mac):
        """
        Check interface through guestfish.Fix mac if necessary.
        """
        # disk or domain
        vm_ref = self.params.get("libvirt_domain")
        if not vm_ref:
            vm_ref = self.params.get("disk_img")
            if not vm_ref:
                logging.error("No object to edit.")
                return False
        logging.info("Resetting %s's mac to %s", vm_ref, iface_mac)

        # Fix file which includes interface devices information
        # Default is /etc/udev/rules.d/70-persistent-net.rules
        devices_file = "/etc/udev/rules.d/70-persistent-net.rules"
        # Set file which binds mac and IP-address
        ifcfg_files = ["/etc/sysconfig/network-scripts/ifcfg-p1p1",
                       "/etc/sysconfig/network-scripts/ifcfg-eth0"]
        # Fix devices file
        mac_regex = (r"\w.:\w.:\w.:\w.:\w.:\w.")
        edit_expr = "s/%s/%s/g" % (mac_regex, iface_mac)
        file_ret = self.is_file(devices_file)
        if file_ret.stdout.strip() == "true":
            self.close_session()
            try:
                result = lgf.virt_edit_cmd(vm_ref, devices_file,
                                           expr=edit_expr, debug=True,
                                           ignore_status=True)
                if result.exit_status:
                    logging.error("Edit %s failed:%s", devices_file, result)
                    return False
            except lgf.LibguestfsCmdError, detail:
                logging.error("Edit %s failed:%s", devices_file, detail)
                return False
            self.new_session()
            # Just to keep output looking better
            self.is_ready()
            logging.debug(self.cat(devices_file))

        # Fix interface file
        for ifcfg_file in ifcfg_files:
            file_ret = self.is_file(ifcfg_file)
            if file_ret.stdout.strip() == "false":
                continue
            self.close_session()
            self.params['ifcfg_file'] = ifcfg_file
            try:
                result = lgf.virt_edit_cmd(vm_ref, ifcfg_file,
                                           expr=edit_expr, debug=True,
                                           ignore_status=True)
                if result.exit_status:
                    logging.error("Edit %s failed:%s", ifcfg_file, result)
                    return False
            except lgf.LibguestfsCmdError, detail:
                logging.error("Edit %s failed:%s", ifcfg_file, detail)
                return False
            self.new_session()
            # Just to keep output looking better
            self.is_ready()
            logging.debug(self.cat(ifcfg_file))
        return True

    def copy_ifcfg_back(self):
        # This function must be called after reset_interface()
        ifcfg_file = self.params.get("ifcfg_file")
        bak_file = "%s.bak" % ifcfg_file
        if ifcfg_file:
            self.is_ready()
            is_need = self.is_file(ifcfg_file)
            if is_need.stdout.strip() == "false":
                cp_result = self.cp(bak_file, ifcfg_file)
                if cp_result.exit_status:
                    logging.warn("Recover ifcfg file failed:%s", cp_result)
                    return False
        return True


