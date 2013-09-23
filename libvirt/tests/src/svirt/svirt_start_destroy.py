"""
svirt guest_start_destroy test.
"""
from autotest.client.shared import error
from virttest import utils_selinux, virt_vm
from virttest.libvirt_xml.vm_xml import VMXML


def run_svirt_start_destroy(test, params, env):
    """
    Test svirt in adding disk to VM.

    (1).Init variables for test.
    (2).Label the VM and disk with proper label.
    (3).Start VM and check the context.
    (4).Destroy VM and check the context.
    """
    # Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("svirt_start_destroy_host_selinux", "enforcing")
    # Get variables about seclabel for VM.
    sec_type = params.get("svirt_start_destroy_vm_sec_type", "dynamic")
    sec_model = params.get("svirt_start_destroy_vm_sec_model", "selinux")
    sec_label = params.get("svirt_start_destroy_vm_sec_label", None)
    sec_relabel = params.get("svirt_start_destroy_vm_sec_relabel", "yes")
    sec_dict = {'type': sec_type, 'model': sec_model, 'label': sec_label,
                'relabel': sec_relabel}
    # Get variables about VM and get a VM object and VMXML instance.
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_dumpxml(vm_name)
    backup_xml = vmxml.copy()

    # Get varialbles about image.
    img_label = params.get('svirt_start_destroy_disk_label')
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

    try:
        # Start VM to check the VM is able to access the image or not.
        try:
            vm.start()
            # Start VM successfully.
            # VM with seclabel can access the image with the context.
            if status_error:
                raise error.TestFail("Test successed in negative case.")
            # Check the label of VM and image when VM is running.
            vm_context = utils_selinux.get_context_of_process(vm.get_pid())
            if (sec_type == "static") and (not vm_context == sec_label):
                raise error.TestFail("Label of VM is not expected after starting.\n"
                                     "Detail: vm_context=%s, sec_label=%s"
                                     % (vm_context, sec_label))
            disk_context = utils_selinux.get_context_of_file(
                filename=disks.values()[0]['source'])
            if (sec_relabel == "no") and (not disk_context == img_label):
                raise error.TestFail("Label of disk is not expected after VM "
                                     "starting.\n"
                                     "Detail: disk_context=%s, img_label=%s."
                                     % (disk_context, img_label))
            if sec_relabel == "yes":
                vmxml = VMXML.new_from_dumpxml(vm_name)
                imagelabel = vmxml.get_seclabel()['imagelabel']
                if not disk_context == imagelabel:
                    raise error.TestFail("Label of disk is not relabeled by VM\n"
                                         "Detal: disk_context=%s, imagelabel=%s"
                                         % (disk_context, imagelabel))
            # Check the label of disk after VM being destroyed.
            vm.destroy()
            img_label_after = utils_selinux.get_context_of_file(
                filename=disks.values()[0]['source'])
            if (not img_label_after == img_label):
                raise error.TestFail("Bug: Label of disk is not restored in VM "
                                     "shuting down.\n"
                                     "Detail: img_label_after=%s, "
                                     "img_label_before=%s.\n"
                                     # pylint: disable=C0301
                                     "Reference: https://bugzilla.redhat.com/show_bug.cgi?id=547546"
                                     % (img_label_after, img_label))
        except virt_vm.VMStartError, e:
            # Starting VM failed.
            # VM with seclabel can not access the image with the context.
            if not status_error:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % e)
    finally:
        # clean up
        for path, label in backup_labels_of_disks.items():
            utils_selinux.set_context_of_file(filename=path, context=label)
        backup_xml.sync()
        utils_selinux.set_status(backup_sestatus)
