from autotest.client.shared import error
from virttest import libvirt_vm, remote, virsh, utils_libvirtd


def run_virsh_destroy(test, params, env):
    """
    Test command: virsh destroy.

    The command can destroy (stop) a domain.
    1.Prepare test environment.
    2.When the ibvirtd == "off", stop the libvirtd service.
    3.Perform virsh destroy operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("destroy_vm_ref")
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")
    remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
    remote_pwd = params.get("remote_pwd", None)
    local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
    if vm_ref == "remote" and (remote_ip.count("EXAMPLE.COM")
                 or local_ip.count("EXAMPLE.COM")):
        raise error.TestNAError(
            "Remote test parameters unchanged from default")

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("destroy_extra"))
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    if vm_ref != "remote":
        status = virsh.destroy(vm_ref, ignore_status=True).exit_status
        output = ""
    else:
        status = 0
        try:
            remote_uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s destroy %s" % (remote_uri, vm_name)
            status, output = session.cmd_status_output(command,
                                                       internal_timeout=5)
            session.close()
        except error.CmdError:
            status = 1

    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command! "
                                 "Output:\n%s" % output)
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command! Output:\n%s"
                                 % output)
