"""
libvirt scsi test

@copyright: 2013 FNST Inc.
"""
import os

from autotest.client.shared import error
from virttest.utils_disk import CdromDisk
from virttest import virt_vm, qemu_storage
from virttest.libvirt_xml.vm_xml import VMXML
from virttest.libvirt_xml.devices.disk import Disk
from virttest.libvirt_xml.devices.controller import Controller


def run_libvirt_scsi(test, params, env):
    #Get variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    add_controller = ('yes' == params.get("libvirt_scsi_controller", 'yes'))
    img_type = ('yes' == params.get("libvirt_scsi_img_type", "no"))
    cdrom_type = ('yes' == params.get("libvirt_scsi_cdrom_type", "no"))
    partition_type = ('yes' == params.get("libvirt_scsi_partition_type", "no"))
    partition = params.get("libvirt_scsi_partition",
                           "ENTER.YOUR.AVAILIBLE.PARTITION")
    vm_name = params.get("main_vm", "virt-tests-vm1")
    # Init a VM instance and a VMXML instance.
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_dumpxml(vm_name)
    # Keep a backup of xml to restore it in cleanup.
    backup_xml = vmxml.copy()
    # Add a scsi controller if there is not.
    controller_devices = vmxml.get_devices("controller")
    scsi_controller_exists = False
    for device in controller_devices:
        if device.type == "scsi":
            scsi_controller_exists = True
            break
    if not scsi_controller_exists:
        scsi_controller = Controller("controller")
        scsi_controller.type = "scsi"
        scsi_controller.index = "0"
        scsi_controller.model = "virtio-scsi"
        vmxml.add_device(scsi_controller)
    # Add disk with bus of scsi into vmxml.
    if img_type:
        img_disk = Disk("disk")
        img_disk.type = "file"
        img_disk.device = "disk"
        img_disk.target_dev = "vde"
        img_disk.target_bus = "scsi"
        # Init a QemuImg instance.
        img_name = "libvirt_scsi"
        params['image_name'] = img_name
        image = qemu_storage.QemuImg(params, test.tmpdir, img_name)
        # Create a image.
        img_path, result = image.create(params)
        img_disk.source = img_path
        vmxml.add_device(img_disk)
    if cdrom_type:
        cdrom_disk = Disk("disk")
        cdrom_disk.type = "file"
        cdrom_disk.device = "cdrom"
        cdrom_disk.target_dev = "vdf"
        cdrom_disk.target_bus = "scsi"
        # Init a CdromDisk instance.
        cdrom_path = os.path.join(test.tmpdir, "libvirt_scsi")
        cdrom = CdromDisk(cdrom_path, test.tmpdir)
        cdrom.close()
        cdrom_disk.source = cdrom_path
        vmxml.add_device(cdrom_disk)
    if partition_type:
        if partition.count("ENTER.YOUR"):
            raise error.TestNAError("Partition for partition test"
                                    "is not configured.")
        partition_disk = Disk("disk")
        partition_disk.type = "block"
        partition_disk.device = "disk"
        partition_disk.target_dev = "vdg"
        partition_disk.target_bus = "scsi"
        partition_disk.source = partition
        vmxml.add_device(partition_disk)
    # sync the vmxml with VM.
    vmxml.sync()
    # Check the result of scsi disk.
    try:
        try:
            vm.start()
            # Start VM successfully.
            if status_error:
                raise error.TestFail('Starting VM successed in negative case.')
        except virt_vm.VMStartError, e:
            # Starting VM failed.
            if not status_error:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % e)
    finally:
        # clean up.
        backup_xml.sync()
