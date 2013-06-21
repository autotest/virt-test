"""
svirt guest_attach_disk test.
"""
from autotest.client.shared import error
from virttest import qemu_storage, data_dir, utils_selinux, virt_vm, virsh
from virttest.libvirt_xml.vm_xml import VMXML


def run_svirt_attach_disk(test, params, env):
    """
    Test svirt in adding disk to VM.

    (1).Init variables for test.
    (2).Create a image to attached to VM.
    (3).Attach disk.
    (4).Start VM and check result.
    """
    #Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("host_selinux", "enforcing")
    #Get variables about seclabel for VM.
    sec_type = params.get("sec_type", "dynamic")
    sec_model = params.get("sec_model", "selinux")
    sec_label = params.get("sec_label", None)
    sec_relabel = params.get("sec_relabel", "yes")
    sec_dict = {'type':sec_type, 'model':sec_model, 'label':sec_label, 'relabel':sec_relabel}
    #Get variables about VM and get a VM object and VMXML instance.
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_dumpxml(vm_name)
    #Get varialbles about image.
    img_label = params.get('img_label')
    img_name = "svirt_disk"

    #Set selinux of host.
    backup_sestatus = utils_selinux.get_status()
    utils_selinux.set_status(host_sestatus)
    #Init a QemuImg instance.
    params['image_name'] = img_name
    tmp_dir = data_dir.get_tmp_dir()
    image = qemu_storage.QemuImg(params, tmp_dir, img_name)
    #Create a image.
    img_path, result = image.create(params)
    #Set the context of the image.
    utils_selinux.set_context_of_file(filename = img_path, context=img_label)
    #Set the context of the VM.
    backup_seclabel = vmxml.get_seclabel()
    vmxml.set_seclabel(sec_dict)

    #Do the attach action.
    vm.attach_disk(source=img_path, target="vdf", extra="--persistent")

    #Check result.
    try:
        #Start VM to check the VM is able to access the image or not.
        try:
            vm.start()
            #Start VM success.
            #VM with setted seclabel can access the image with the
            #setted context.
            if status_error:
                raise error.TestFail('Test successed in negative case.')
            else:
                pass
        except virt_vm.VMStartError, e:
            #Start VM failed.
            #VM with setted seclabel can not access the image with the
            #setted context.
            if status_error:
                pass
            else:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % e)
    finally:
        #clean up
        vm.detach_disk(target="vdf", extra="--persistent")
        image.remove()
        vmxml.set_seclabel(backup_seclabel)
        utils_selinux.set_status(backup_sestatus)
