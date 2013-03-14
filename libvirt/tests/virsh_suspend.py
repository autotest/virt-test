from autotest.client.shared import error
from virttest import virsh

def run_virsh_suspend(test, params, env):
    """
    Test command: virsh suspend.

    The command can suspend a domain.
    1.Prepare test environment.
    2.Perform virsh suspend operation.
    3.Confirm the test result.
    """
    vm_name = params.get("main_vm", "virt-test-vm1")
    vm = env.get_vm(vm_name)

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("suspend_vm_ref", "")
    extra = params.get("suspend_extra", "")
    status_error = params.get("status_error", "no")

     #run test case
    if vm_ref == "id":
       vm_ref = domid
    elif vm_ref == "hex_id":
       vm_ref = hex(int(domid.strip()))
    elif vm_ref.find("invalid") != -1:
       vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
       vm_ref = "%s %s" % (vm_name, extra)
    elif vm_ref == "uuid":
       vm_ref = domuuid

    result = virsh.suspend(vm_ref, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()
    if status == 0 and not vm.is_paused():
        status = 1

    #check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
    else:
        raise error.TestFail("The status_error must be 'yes' or 'no'!")
