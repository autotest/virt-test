"""
svirt guest_attach_disk test.
"""
from autotest.client.shared import error
from virttest import qemu_storage, data_dir, utils_selinux, virt_vm, virsh
from virttest.libvirt_xml.vm_xml import VMXML


def run(test, params, env):
    """
    Test svirt in adding disk to VM.

    (1).Init variables for test.
    (2).Create a image to attached to VM.
    (3).Attach disk.
    (4).Start VM and check result.
    """
    # Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("svirt_attach_disk_host_selinux", "enforcing")
    # Get variables about seclabel for VM.
    sec_type = params.get("svirt_attach_disk_vm_sec_type", "dynamic")
    sec_model = params.get("svirt_attach_disk_vm_sec_model", "selinux")
    sec_label = params.get("svirt_attach_disk_vm_sec_label", None)
    sec_relabel = params.get("svirt_attach_disk_vm_sec_relabel", "yes")
    sec_dict = {'type': sec_type, 'model': sec_model, 'label': sec_label,
                'relabel': sec_relabel}
    # Get variables about VM and get a VM object and VMXML instance.
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_inactive_dumpxml(vm_name)
    backup_xml = vmxml.copy()
    # Get varialbles about image.
    img_label = params.get('svirt_attach_disk_disk_label')
    img_name = "svirt_disk"
    # Default label for the other disks.
    # To ensure VM is able to access other disks.
    default_label = params.get('svirt_attach_disk_disk_default_label', None)

    # Set selinux of host.
    backup_sestatus = utils_selinux.get_status()
    utils_selinux.set_status(host_sestatus)
    # Set the default label to other disks of vm.
    disks = vm.get_disk_devices()
    for disk in disks.values():
        utils_selinux.set_context_of_file(filename=disk['source'],
                                          context=default_label)
    # Init a QemuImg instance.
    params['image_name'] = img_name
    tmp_dir = data_dir.get_tmp_dir()
    image = qemu_storage.QemuImg(params, tmp_dir, img_name)
    # Create a image.
    img_path, result = image.create(params)
    # Set the context of the image.
    utils_selinux.set_context_of_file(filename=img_path, context=img_label)
    # Set the context of the VM.
    vmxml.set_seclabel(sec_dict)
    vmxml.sync()

    # Do the attach action.
    try:
        virsh.attach_disk(vm_name, source=img_path, target="vdf",
                          extra="--persistent", ignore_status=False)
    except error.CmdError:
        raise error.TestFail("Attach disk %s to vdf on VM %s failed."
                             % (img_path, vm.name))

    # Check result.
    try:
        # Start VM to check the VM is able to access the image or not.
        try:
            vm.start()
            # Start VM successfully.
            # VM with set seclabel can access the image with the
            # set context.
            if status_error:
                raise error.TestFail('Test successed in negative case.')
        except virt_vm.VMStartError, e:
            # Starting VM failed.
            # VM with set seclabel can not access the image with the
            # set context.
            if not status_error:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % e)
    finally:
        # clean up
        try:
            virsh.detach_disk(vm_name, target="vdf", extra="--persistent",
                              ignore_status=False)
        except error.CmdError:
            raise error.TestFail("Detach disk 'vdf' from VM %s failed."
                                 % vm.name)
        image.remove()
        backup_xml.sync()
        utils_selinux.set_status(backup_sestatus)
