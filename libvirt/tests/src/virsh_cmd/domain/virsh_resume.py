import logging
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh resume.

    1) Start vm, Prepare options such as id, uuid
    2) Prepare vm state for test, default is paused.
    3) Prepare other environment
    4) Run command, get result.
    5) Check result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm.verify_alive()

    # Get parameters
    vm_ref = params.get("resume_vm_ref", "domname")
    vm_state = params.get("resume_vm_state", "paused")
    option_suffix = params.get("resume_option_suffix")
    status_error = params.get("status_error", "no")

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Prepare vm state
    if vm_state == "paused":
        vm.pause()
    elif vm_state == "shutoff":
        vm.destroy()

    # Prepare options
    if vm_ref == "domname":
        vm_ref = vm_name
    elif vm_ref == "domid":
        vm_ref = domid
    elif vm_ref == "domuuid":
        vm_ref = domuuid
    elif domid and vm_ref == "hex_id":
        if domid == "-":
            vm_ref = domid
        else:
            vm_ref = hex(int(domid))

    if option_suffix:
        vm_ref = "%s %s" % (vm_ref, option_suffix)

    # Run resume command
    result = virsh.resume(vm_ref, ignore_status=True)
    logging.debug(result)
    status = result.exit_status

    # Get vm state after virsh resume executed.
    domstate = vm.state()

    # Check status_error
    if status_error == "yes":
        # Wrong resume command was excuted, recover with right resume
        if domstate == "paused":
            vm.resume()
        vm.destroy()
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        # Right resume command failed, forcing destroy vm
        if domstate == "paused":
            vm.destroy(gracefully=False)
            raise error.TestFail("Resume vm failed."
                                 "State is still paused")
        vm.destroy()
        if status != 0:
            raise error.TestFail("Run failed with right command")
