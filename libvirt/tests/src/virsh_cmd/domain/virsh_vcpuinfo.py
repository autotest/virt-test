import logging
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run_virsh_vcpuinfo(test, params, env):
    """
    Test command: virsh vcpuinfo.

    The command can get domain vcpu information
    1.Prepare test environment.
    2.When the ibvirtd == "off", stop the libvirtd service.
    3.Perform virsh vcpuinfo operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # run test case
    vm_ref = params.get("vcpuinfo_vm_ref")
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("vcpuinfo_extra"))

    result = virsh.vcpuinfo(vm_ref)
    status = result.exit_status
    err = result.stderr.strip()

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if not status:
            logging.debug(result)
            raise error.TestFail("Run successfully with wrong command!")
        # Check the error message in negative case.
        if not err:
            logging.debug(result)
            logging.debug("Bugzilla: https://bugzilla.redhat.com/show_bug."
                          "cgi?id=889276 is helpful for tracing this bug.")
            raise error.TestFail("No error message for a command error!")
    elif status_error == "no":
        if status:
            logging.debug(result)
            raise error.TestFail("Run failed with right command")
