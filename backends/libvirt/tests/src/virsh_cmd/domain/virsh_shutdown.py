from autotest.client.shared import error
from virttest import remote, libvirt_vm, virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh shutdown.

    The conmand can gracefully shutdown a domain.

    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh setvcpus operation.
    4.Recover test environment.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("shutdown_vm_ref")
    libvirtd = params.get("libvirtd", "on")

    # run test case
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("shutdown_extra"))
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    if vm_ref != "remote":
        status = virsh.shutdown(vm_ref, ignore_status=True).exit_status
    else:
        remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
        remote_pwd = params.get("remote_pwd", None)
        local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
        if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
            raise error.TestNAError(
                "Remote test parameters unchanged from default")
        status = 0
        try:
            remote_uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s shutdown %s" % (remote_uri, vm_name)
            status = session.cmd_status(command, internal_timeout=5)
            session.close()
        except error.CmdError:
            status = 1

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    status_error = params.get("status_error")
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
