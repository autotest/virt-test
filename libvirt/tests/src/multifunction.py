import logging
import os
import commands
from autotest.client.shared import error
from virttest import libvirt_vm, virsh, data_dir
from virttest.libvirt_xml import xcepts, vm_xml
from virttest.libvirt_xml.devices import disk


class MFError(Exception):
    pass


class MFCheckDiskError(MFError):

    def __init__(self, output):
        super(MFCheckDiskError, self).__init__(output)
        self.output = output

    def __str__(self):
        return ("Check disk in vm failed:\n%s" % self.output)


def cleanup_vm(vm_name=None, disk_removed=None):
    """
    Cleanup the vm with its disk deleted.
    """
    try:
        if vm_name is not None:
            virsh.undefine(vm_name)
    except error.CmdError:
        pass
    try:
        if disk_removed is not None:
            os.remove(disk_removed)
    except IOError:
        pass


def prepare_disk_params(target_list, params):
    """
    Prepare params lists for creating disk xml.

    :param target_list: devices which need disk xml.
    :param params: base slot/func value in config file.
    """
    addr_multifunction = params.get("mf_addr_multifunction")
    addr_type = params.get("mf_addr_type")
    base_domain = params.get("mf_addr_domain", "0x0000")
    base_bus = params.get("mf_addr_bus", "0x00")
    base_slot = params.get("mf_addr_slot", "0x0a")
    base_function = params.get("mf_addr_function", "0x0")
    # slot_metric: the metric which slot will increase.
    # func_metric: the metric which func will increase.
    try:
        slot_metric = int(params.get("mf_slot_metric", 0))
    except ValueError, detail:    # illegal metric
        logging.warn(detail)
        slot_metric = 0
    try:
        func_metric = int(params.get("mf_func_metric", 0))
    except ValueError, detail:    # illegal metric
        logging.warn(detail)
        func_metric = 0

    disk_params_dict = {}
    for target_dev in target_list:
        disk_params = {}
        disk_params['addr_multifunction'] = addr_multifunction
        disk_params['addr_type'] = addr_type
        # Do not support increated metric of domain and bus yet
        disk_params['addr_domain'] = base_domain
        disk_params['addr_bus'] = base_bus
        disk_params['addr_slot'] = base_slot
        disk_params['addr_function'] = base_function

        # Convert string hex to number hex for operation
        try:
            base_slot = int(base_slot, 16)
            base_function = int(base_function, 16)
        except ValueError:
            pass  # Can not convert, use original string

        # Increase slot/func for next target_dev
        if slot_metric:
            try:
                base_slot += slot_metric
            except TypeError, detail:
                logging.warn(detail)
        if func_metric:
            try:
                base_function += func_metric
            except TypeError, detail:
                logging.warn(detail)

        # Convert number hex back to string hex if necessary
        try:
            base_slot = hex(base_slot)
            base_function = hex(base_function)
        except TypeError:
            pass   # Can not convert, directly pass

        disk_params_dict[target_dev] = disk_params
    return disk_params_dict


def create_disk_xml(params):
    """
    Create a disk configuration file.

    :param params: a dict contains values of disk
                   {'device_type': "file",
                    'source_file': ...,
                    'target_dev': ...,
                    'target_bus': "virtio",
                    'addr_type': ...,
                    'addr_domain': ...,
                    'addr_bus':...,
                    'addr_slot': ...,
                    'addr_function': ...,
                    'addr_multifunction': ...}
    """
    # Create attributes dict for disk's address element
    addr_attr = {}
    addr_type = params.get("addr_type", "pci")
    addr_attr['domain'] = params.get("addr_domain", "0x0000")
    addr_attr['bus'] = params.get("addr_bus", "0x00")
    addr_attr['slot'] = params.get("addr_slot", "0x0a")
    addr_attr['function'] = params.get("addr_function", "0x0")
    if params.get("addr_multifunction") is not None:
        addr_attr['multifunction'] = params.get("addr_multifunction")

    type_name = params.get("type_name", "file")
    source_file = params.get("source_file")
    target_dev = params.get("target_dev", "vdb")
    target_bus = params.get("target_bus", "virtio")
    diskxml = disk.Disk(type_name)
    diskxml.device = params.get("device_type", "disk")
    diskxml.source = diskxml.new_disk_source(attrs={'file': source_file})
    diskxml.target = {'dev': target_dev, 'bus': target_bus}
    diskxml.address = diskxml.new_disk_address(addr_type, attrs=addr_attr)
    logging.debug("Disk XML:\n%s", str(diskxml))
    return diskxml.xml


def device_exists(vm, target_dev):
    """
    Check if given target device exists on vm.
    """
    targets = vm.get_blk_devices().keys()
    if target_dev in targets:
        return True
    return False


def attach_additional_device(vm_name, disksize, targetdev, params):
    """
    Create a disk with disksize, then attach it to given vm.

    @param vm: Libvirt VM name.
    @param disksize: size of attached disk
    @param targetdev: target of disk device
    """
    logging.info("Attaching disk...")
    disk_path = os.path.join(data_dir.get_tmp_dir(), targetdev)
    cmd = "qemu-img create %s %s" % (disk_path, disksize)
    status, output = commands.getstatusoutput(cmd)
    if status:
        return (False, output)

    # Update params for source file
    params['source_file'] = disk_path
    params['target_dev'] = targetdev

    # Create a file of device
    xmlfile = create_disk_xml(params)

    # To confirm attached device do not exist.
    virsh.detach_disk(vm_name, targetdev, extra="--config")

    return virsh.attach_device(domain_opt=vm_name, file_opt=xmlfile,
                               flagstr="--config", debug=True)


def define_new_vm(vm_name, new_name):
    """
    Just define a new vm from given name
    """
    try:
        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
        vmxml.vm_name = new_name
        del vmxml.uuid
        vmxml.define()
        return True
    except xcepts.LibvirtXMLError, detail:
        logging.error(detail)
        return False


def check_disk(vm, target_dev, part_size):
    """
    Check disk on vm.
    Create a new partition and mount it.
    """
    if not vm.is_alive():
        vm.start()
    session = vm.wait_for_login()
    device = "/dev/%s" % target_dev
    if session.cmd_status("ls %s" % device):
        raise MFCheckDiskError("Can not find '%s' in guest." % device)
    else:
        if session.cmd_status("which parted"):
            logging.error("Did not find command 'parted' in guest, SKIP...")
            return
    ret1, output1 = session.cmd_status_output("parted %s \"mklabel msdos\""
                                              % device, timeout=5)
    ret2, output2 = session.cmd_status_output("parted %s \"mkpart p 1M %s\""
                                              % (device, part_size), timeout=5)
    logging.debug("Create part:\n:%s\n%s", output1, output2)
    if ret1 or ret2:
        raise MFCheckDiskError("Create partition for '%s' failed." % device)

    if session.cmd_status("mkfs.ext3 %s1" % device):
        raise MFCheckDiskError("Format created partition failed.")

    if session.cmd_status("mount %s1 /mnt" % device):
        raise MFCheckDiskError("Can not mount '%s' to /mnt." % device)


def run(test, params, env):
    """
    Test multi function of vm devices.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    # To avoid dirty after starting new vm
    if vm.is_alive():
        vm.destroy()
    new_vm_name = params.get("mf_updated_new_vm")
    define_new_vm(vm_name, new_vm_name)
    # Create a new vm object for convenience
    new_vm = libvirt_vm.VM(new_vm_name, vm.params, vm.root_dir,
                           vm.address_cache)
    try:
        # Get parameters
        disk_count = int(params.get("mf_added_devices_count", 1))
        disk_size = params.get("mf_added_devices_size", "50M")
        status_error = "yes" == params.get("status_error", "no")
        check_disk_error = "yes" == params.get("mf_check_disk_error", "no")
        target_list = []
        index = 0
        while len(target_list) < disk_count:
            target_dev = "vd%s" % chr(ord('a') + index)
            if not device_exists(new_vm, target_dev):
                target_list.append(target_dev)
            index += 1

        disk_params_dict = prepare_disk_params(target_list, params)
        # To record failed attach
        fail_info = []
        for target_dev in target_list:
            result = attach_additional_device(new_vm_name, disk_size,
                                              target_dev,
                                              disk_params_dict[target_dev])
            if result.exit_status:
                if status_error:
                    # Attach fail is expected.
                    # TODO: check output of fail info
                    logging.info("Failed as expected.")
                    return
                else:
                    raise error.TestFail("Attach device %s failed."
                                         % target_dev)
            else:
                if status_error and not check_disk_error:
                    fail_info.append("Attach %s successfully "
                                     "but not expected." % target_dev)
        if len(fail_info):
            raise error.TestFail(fail_info)
        logging.debug("New VM XML:\n%s", new_vm.get_xml())

        # Login to check attached devices
        for target_dev in target_list:
            try:
                check_disk(new_vm, target_dev, disk_size)
            except MFCheckDiskError, detail:
                if check_disk_error:
                    logging.debug("Check disk failed as expected:\n%s", detail)
                    return
                else:
                    raise
            if check_disk_error:
                raise error.TestFail("Check disk didn't fail as expected.")
    finally:
        if new_vm.is_alive():
            new_vm.destroy()
        cleanup_vm(new_vm_name)
