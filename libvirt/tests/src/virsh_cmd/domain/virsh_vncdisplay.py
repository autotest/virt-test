from autotest.client.shared import error
from virttest import libvirt_vm, virsh, remote, utils_libvirtd


def run(test, params, env):
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

    def remote_case(params, vm_name):
        """
        Test remote case.
        """
        remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
        local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
        remote_pwd = params.get("remote_pwd", "")
        status = 0
        output = ""
        try:
            if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
                raise error.TestNAError("remote_ip and/or local_ip parameters "
                                        "not changed from default values.")
            uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s vncdisplay %s" % (uri, vm_name)
            status, output = session.cmd_status_output(command,
                                                       internal_timeout=5)
            session.close()
        except error.CmdError:
            status = 1
            output = "remote test failed"
        return status, output

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

    if vm_ref == "remote":
        status, output = remote_case(params, vm_name)
    else:
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
