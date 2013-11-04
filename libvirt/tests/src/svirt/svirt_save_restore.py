"""
svirt guest_save_restore test.
"""
import os
import logging

from autotest.client.shared import error
from virttest import utils_selinux, virt_vm
from virttest.libvirt_xml.vm_xml import VMXML


def run_svirt_save_restore(test, params, env):
    """
    Test svirt in adding disk to VM.

    (1).Init variables for test.
    (2).Label the VM and disk with proper label.
    (3).Save VM and check the context.
    (4).Restore VM and check the context.
    """
    # Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("svirt_save_restore_host_selinux", "enforcing")
    # Get variables about seclabel for VM.
    sec_type = params.get("svirt_save_restore_vm_sec_type", "dynamic")
    sec_model = params.get("svirt_save_restore_vm_sec_model", "selinux")
    sec_label = params.get("svirt_save_restore_vm_sec_label", None)
    sec_relabel = params.get("svirt_save_restore_vm_sec_relabel", "yes")
    sec_dict = {'type': sec_type, 'model': sec_model, 'label': sec_label,
                'relabel': sec_relabel}
    # Get variables about VM and get a VM object and VMXML instance.
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_dumpxml(vm_name)
    backup_xml = vmxml.copy()

    # Get varialbles about image.
    img_label = params.get('svirt_save_restore_disk_label')
    # Label the disks of VM with img_label.
    disks = vm.get_disk_devices()
    backup_labels_of_disks = {}
    for disk in disks.values():
        disk_path = disk['source']
        backup_labels_of_disks[disk_path] = utils_selinux.get_context_of_file(
            filename=disk_path)
        utils_selinux.set_context_of_file(filename=disk_path,
                                          context=img_label)
    # Set selinux of host.
    backup_sestatus = utils_selinux.get_status()
    utils_selinux.set_status(host_sestatus)
    # Set the context of the VM.
    vmxml.set_seclabel(sec_dict)
    vmxml.sync()

    # Init a path to save VM.
    save_path = os.path.join(test.tmpdir, "svirt_save")
    try:
        # Start VM to check the VM is able to access the image or not.
        try:
            vm.start()
            vm.save_to_file(path=save_path)
            vm.restore_from_file(path=save_path)
            # Save and restore VM successfully.
            if status_error:
                raise error.TestFail("Test successed in negative case.")
        except virt_vm.VMError, e:
            if not status_error:
                error_msg = "Test failed in positive case.\n error: %s\n" % e
                if str(e).count("getfd"):
                    error_msg += ("More info pleass refer to"
                                  " https://bugzilla.redhat.com/show_bug.cgi?id=976632")
                raise error.TestFail(error_msg)
    finally:
        # clean up
        for path, label in backup_labels_of_disks.items():
            utils_selinux.set_context_of_file(filename=path, context=label)
        backup_xml.sync()
        utils_selinux.set_status(backup_sestatus)
