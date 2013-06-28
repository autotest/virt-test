from autotest.client.shared import error
from virttest import data_dir, storage, utils_selinux, virsh
from tests import unattended_install

def run_svirt_install(test, params, env):
    """
    Test svirt in virt-install.

    (1). Init variables.
    (2). Set selinux on host.
    (3). Set label of image.
    (4). run unattended install.
    (5). clean up.
    """
    #Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("host_selinux", "enforcing")

    #Set selinux status on host.
    backup_sestatus = utils_selinux.get_status()
    utils_selinux.set_status(host_sestatus)

    #Set the image label.
    disk_label = params.get("disk_label", None)
    vm_name = params.get("main_vm", None)
    vm_params = params.object_params(vm_name)
    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    image_filename = storage.get_image_filename(vm_params, base_dir)
    utils_selinux.set_context_of_file(image_filename, disk_label)

    try:
        try:
            unattended_install.run_unattended_install(test, params, env)
            #Install completed.
            if status_error:
                raise error.TestFail('Test successed in negative case.')
        except error.CmdError, e:
            #Install failed.
            if not status_error:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % e)
    finally:
        #cleanup
        utils_selinux.set_status(backup_sestatus)
        if virsh.domain_exists(vm_name):
            virsh.remove_domain(vm_name)
