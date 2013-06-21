"""
svirt guest_operation test

@copyright: 2012 FNST Inc.
"""
from autotest.client.shared import error
from virttest import utils_selinux, virsh
from virttest.libvirt_xml.vm_xml import VMXML


def run_svirt_guest_operation(test, params, env):
    """
    Test the guest operations which are start,shutdown,destroy,undefine and clone
    """
    #start functions begin.
    def start_action():
        """
        Start VM and check the result.
        """
        result = virsh.start(vm.name)
        if result.exit_status:
            raise error.TestFail("VM start failed."
                                 "Detail: %s." % (result.stderr))

    def start_verify():
        """
        Check the status of VM is alive.
        """
        if not vm.is_alive():
            raise error.TestFail("VM is not alive after start.")

    def start_cleanup():
        """
        Cleanup for start operation.
        """
        pass
    #start functions end.

    #destroy functions begin.
    def destroy_action():
        """
        Start VM and Destroy VM.
        """
        result = virsh.start(vm.name)
        if result.exit_status:
            raise error.TestFail("VM start failed."
                                 "Detail: %s." % (result.stderr))

        result = virsh.destroy(vm.name)
        if result.exit_status:
            raise error.TestFail("VM destroy failed."
                                 "Detail: %s." % (result.stderr))

    def destroy_verify():
        """
        Check VM is not alive and check the context of disks.
        """
        if vm.is_alive():
            raise error.TestFail("VM is alive after destroy.")
        for path, context in backup_disks_context.items():
            context_current = utils_selinux.get_context_of_file(filename=path)
            if not context == context_current:
                raise error.TestFail("Context is changed from %s to %s"
                                     "after destroy."
                                     % (context, context_current))

    def destroy_cleanup():
        """
        Cleanup for destroy operation.
        """
        pass
    #destroy functions end.

    #undefine functions begin.
    def undefine_action():
        """
        Undefine VM and check result.
        """
        result = virsh.undefine(vm.name)
        if result.exit_status:
            raise error.TestFail("VM undefine failed."
                                 "Detail: %s." % (result.stderr))

    def undefine_verify():
        """
        Check the VM does not exist.
        """
        if vm.exists():
            raise error.TestFail("VM exists after undefine.")

    def undefine_cleanup():
        """
        Specific cleanup for undefine operation.

        revert VM .
        """
        vmxml.define()
    #undefine functions end.


    #Init a dict contain operation to functions.
    operation2functions = {"start":{"action":"start_action",
                                    "verify":"start_verify",
                                    "cleanup":"start_cleanup"},
                           "destroy":{"action":"destroy_action",
                                      "verify":"destroy_verify",
                                      "cleanup":"destroy_cleanup"},
                           "undefine":{"action":"undefine_action",
                                       "verify":"undefine_verify",
                                       "cleanup":"undefine_cleanup"}}
    #Get general variables.
    status_error = ('yes' == params.get("status_error", 'no'))
    host_sestatus = params.get("host_selinux", "enforcing")
    operation = params.get("operation", "start")
    #Get variables about seclabel for VM.
    sec_type = params.get("sec_type", "dynamic")
    sec_model = params.get("sec_model", "selinux")
    sec_label = params.get("sec_label", None)
    sec_relabel = params.get("sec_relabel", "yes")
    sec_dict = {'type':sec_type, 'model':sec_model,
                'label':sec_label, 'relabel':sec_relabel}
    #Get variables about VM and get a VM object and VMXML instance.
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vmxml = VMXML.new_from_dumpxml(vm_name)
    #Get variables about VM image.
    guest_img_label = params.get("guest_img_label", None)

    #Set selinux of host.
    backup_sestatus = utils_selinux.get_status()
    utils_selinux.set_status(host_sestatus)
    #Set seclabel of VM.
    backup_seclabel = vmxml.get_seclabel()
    vmxml.set_seclabel(sec_dict)

    #Set the disks of VM to specific context.
    disks = vm.get_disk_devices()
    backup_disks_context = {}
    for disk in disks.values():
        path = disk['source']
        backup_context = utils_selinux.get_context_of_file(filename=path)
        backup_disks_context[path] = backup_context
        utils_selinux.set_context_of_file(filename=path,
                                          context=guest_img_label)

    #Get the functions for the operation of this case.
    functions = operation2functions[operation]
    action_func = functions["action"]
    verify_func = functions["verify"]
    cleanup_func = functions["cleanup"]

    try:
        try:
            #Do the action.
            locals()[action_func]()
            #Do the verification.
            locals()[verify_func]()
            #Action and Verify success.
            if status_error:
                raise error.TestFail('Test successed in negative case.')
            else:
                pass
        except error.TestFail, detail:
            #Action or Verify failed.
            if status_error:
                pass
            else:
                raise error.TestFail("Test failed in positive case."
                                     "error: %s" % detail)
    finally:
        #cleanup
        #host sestatus revert.
        utils_selinux.set_status(backup_sestatus)
        #VM seclabel revert.
        vmxml.set_seclabel(backup_seclabel)
        #Disks of VM revert.
        for path in backup_disks_context:
            context = backup_disks_context[path]
            utils_selinux.set_context_of_file(filename=path, context=context)
        #Specific cleanup for specific operation.
        locals()[cleanup_func]()
