from autotest.client.shared import error
from virttest import virsh, utils_libvirtd


def run_virsh_vncdisplay(test, params, env):
    """
    Test command: virsh vncdisplay.

    The command can output the IP address and port number for the VNC display.
    1.Prepare test environment.
    2.When the ibvirtd == "off", stop the libvirtd service.
    3.Perform virsh vncdisplay operation.
    4.Recover test environment.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(vm_name)

    libvirtd = params.get("libvirtd", "on")
    vm_ref = params.get("vncdisplay_vm_ref")
    status_error = params.get("status_error", "no")
    extra = params.get("vncdisplay_extra", "")

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, extra)
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    result = virsh.vncdisplay(vm_ref, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()

    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
