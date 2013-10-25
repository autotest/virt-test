import logging
import os
import re
from autotest.client.shared import error, utils
from virttest import utils_libguestfs as lgf
from virttest import virt_vm, aexpect, virsh, libvirt_vm, utils_net
from virttest.libvirt_xml import vm_xml, xcepts


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


def truncate_from_file(ref_file, new_file, resize=0):
    """
    Truncate a new file reference given file's size.
    Then change its size if resize is not zero.

    @param resize: it can be +x or -x.
    """
    cmd = "truncate -r %s %s" % (ref_file, new_file)
    result = utils.run(cmd, ignore_status=True, timeout=15)
    logging.debug(result)
    if result.exit_status:
        return False
    if resize:
        cmd = "truncate -s %s %s" % (resize, new_file)
        result = utils.run(cmd, ignore_status=True, timeout=15)
        logging.debug(result)
        if result.exit_status:
            logging.error(result)
            return False
    return True


def get_primary_disk(vm):
    """Get primary disk source"""
    vmdisks = vm.get_disk_devices()
    if len(vmdisks):
        pri_target = ['vda', 'sda']
        for target in pri_target:
            try:
                return vmdisks[target]['source']
            except KeyError:
                pass
    return None


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
                                 str(vmxml.dict_get('xml'))))
            logging.debug(vmxml.dict_get('xml'))
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
        options['timeout'] = int(self.params.get("timeout", 240))
        result = lgf.virt_resize_cmd(self.indisk, self.outdisk, **options)
        if result.exit_status:
            logging.error(result)
            return (False, result)
        return (True, self.outdisk)


class GuestfishTools(lgf.GuestfishPersistent):

    """Useful methods for guestfish operations"""

    __slots__ = lgf.GuestfishPersistent.__slots__ + ('params',)

    def __init__(self, params):
        """
        Init a persistent guestfish shellsession.
        """
        self.params = params
        disk_img = params.get("disk_img")
        ro_mode = bool(params.get("ro_mode", False))
        libvirt_domain = params.get("libvirt_domain")
        inspector = bool(params.get("inspector", False))
        super(GuestfishTools, self).__init__(disk_img, ro_mode,
                                             libvirt_domain, inspector)

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

    def get_partitions_info(self, device="/dev/sda"):
        """
        Get disk partition's infomation.
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


def test_cloned_vm(vm, params):
    """
    1) Clone a new vm with virt-clone
    2) Use guestfish to set new vm's network(accroding mac)
    3) Start new vm to check its network
    """
    new_vm_name = "%s_vtclone" % vm.name
    vt = VirtTools(vm, params)
    clones, cloneo = vt.clone_vm_filesystem(new_vm_name)
    if clones is False:
       # Clean up:remove newvm and its storage
        cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail(cloneo)
    new_vm = vt.newvm

    params['libvirt_domain'] = new_vm_name
    new_vm_mac = vm_xml.VMXML.get_first_mac_by_name(new_vm_name)
    if new_vm_mac is None:
        cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail("Can not get new vm's mac address.")
    gf = GuestfishTools(params)
    gf.reset_interface(new_vm_mac)
    gf.close_session()

    # This step for the reason:
    # virt-clone will move ifcfg-xxx to a file with suffix ".bak"
    # So we need start vm then shutdown it to copy it back
    try:
        new_vm.start()
        new_vm.wait_for_login(timeout=120)
    except (virt_vm.VMStartError, aexpect.ShellError):
        pass
    finally:
        new_vm.destroy()
    gf.new_session()
    gf.copy_ifcfg_back()
    gf.close_session()

    logging.info("Checking cloned vm' IP...")
    try:
        new_vm.start()
        new_vm.wait_for_login()
    except (virt_vm.VMStartError, aexpect.ShellError), detail:
        new_vm.destroy(gracefully=False)
        cleanup_vm(new_vm_name, vt.outdisk)
        raise error.TestFail("Check cloned vm's network failed:%s" % detail)

    new_vm.destroy()
    cleanup_vm(new_vm_name, vt.outdisk)
    logging.info("###############PASS##############")


def test_sparsified_vm(vm, params):
    """
    1) Write a file to oldvm
    2) Sparsify the oldvm to a newvm
    3) Check file's md5 in newvm
    """
    # Create a file to oldvm with guestfish
    content = "This is file for sparsified vm."
    path = params.get("temp_file", "/home/test_sparsified_vm")
    vt = VirtTools(vm, params)

    params['libvirt_domain'] = vt.oldvm.name
    gf = GuestfishTools(params)
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")

    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_old = md5o.strip()
    logging.debug("%s's md5 in oldvm is:%s", path, md5_old)

    sparsifys, sparsifyo = vt.sparsify_disk()
    if sparsifys is False:
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(sparsifyo)

    defines, defineo = vt.define_vm_with_newdisk()
    if defines is False:
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(defineo)

    params['libvirt_domain'] = vt.newvm.name
    gf = GuestfishTools(params)
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_new = md5o.strip()
    logging.debug("%s's md5 in newvm is:%s", path, md5_new)

    if md5_old != md5_new:
        cleanup_vm(vt.newvm.name, vt.outdisk)
        raise error.TestFail("Md5 of new vm is not match with old one.")

    cleanup_vm(vt.newvm.name, vt.outdisk)
    logging.info("###############PASS##############")


def test_resized_vm(vm, params):
    """
    1) Write a file to oldvm
    2) Resize the olddisk to a newdisk
    3) Check file's md5 in newvm
    """
    # Create a file to oldvm with guestfish
    content = "This is file for resized vm."
    path = params.get("temp_file", "/home/test_resized_vm")
    resize_part_num = params.get("resize_part_num", "2")
    #resized_size = params.get("resized_size", "+1G")
    increased_size = params.get("increased_size", "+5G")
    resized_size = "+2G"
    vt = VirtTools(vm, params)

    params['libvirt_domain'] = vt.oldvm.name
    gf = GuestfishTools(params)
    old_disk_size = gf.get_part_size(resize_part_num)
    if old_disk_size is None:
        gf.close_session()
        raise error.TestFail("Get part %s size failed." % resize_part_num)
    else:
        old_disk_size = int(old_disk_size)
    if gf.write_file(path, content) is False:
        gf.close_session()
        raise error.TestFail("Create file failed.")
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        raise error.TestFail(md5o)
    gf.close_session()
    md5_old = md5o.strip()
    logging.debug("%s's md5 in oldvm is:%s", path, md5_old)

    # Create a new file with 2G bigger than old vm's disk
    if vt.indisk is None:
        raise error.TestFail("No disk found for %s" % vt.oldvm.name)
    vt.outdisk = "%s-resize" % vt.indisk
    truncate_from_file(vt.indisk, vt.outdisk, increased_size)

    resizes, resizeo = vt.expand_vm_filesystem(resize_part_num,
                                               resized_size)
    if resizes is False:
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(resizeo)

    params['disk_img'] = vt.outdisk
    params['libvirt_domain'] = None
    gf = GuestfishTools(params)

    # Check disk's size
    new_disk_size = gf.get_part_size(resize_part_num)
    if new_disk_size is None:
        gf.close_session()
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Get part %s size failed." % resize_part_num)
    else:
        new_disk_size = int(new_disk_size)

    real_increased_size = abs(new_disk_size - old_disk_size)
    delta = (real_increased_size - 2147483648) / 2147483648
    if delta > 0.1:
        gf.close_session()
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Disk size is not increased to expected value:\n"
                             "Original:%s\n"
                             "New:%s" % (old_disk_size, new_disk_size))

    # Check file's md5 after resize
    md5s, md5o = gf.get_md5(path)
    if md5s is False:
        gf.close_session()
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail(md5o)
    gf.close_session()
    md5_new = md5o.strip()
    logging.debug("%s's md5 in newvm is:%s", path, md5_new)

    if md5_old != md5_new:
        cleanup_vm(disk=vt.outdisk)
        raise error.TestFail("Md5 of new vm is not match with old one.")

    cleanup_vm(disk=vt.outdisk)
    logging.info("###############PASS##############")


def run_guestfs_operated_disk(test, params, env):
    """
    Test guestfs with operated disk: cloned, spasified, resized
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    operation = params.get("disk_operation")
    eval("test_%s(vm, params)" % operation)
