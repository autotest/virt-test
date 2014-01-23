from autotest.client.shared import error
from virttest import libvirt_vm, remote, virsh, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh dominfo.

    The command returns basic information about the domain.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh dominfo operation.
    4.Recover test environment.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(vm_name)
    if vm.is_alive() and params.get("start_vm") == "no":
        vm.destroy()

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    vm_ref = params.get("dominfo_vm_ref")
    extra = params.get("dominfo_extra", "")
    status_error = params.get("status_error", "no")
    libvirtd = params.get("libvirtd", "on")

    def remote_test(params, vm_name):
        """
        Test remote case.
        """
        remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
        local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
        remote_pwd = params.get("remote_pwd", "")
        status = 0
        output = ""
        err = ""
        try:
            if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
                raise error.TestNAError("remote_ip and/or local_ip parameters "
                                        "not changed from default values.")
            uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s dominfo %s" % (uri, vm_name)
            status, output = session.cmd_status_output(command,
                                                       internal_timeout=5)
            if status != 0:
                err = output
            session.close()
        except error.CmdError:
            status = 1
            output = ""
            err = "remote test failed"
        return status, output, err

    # run test case
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

    if vm_ref != "remote":
        result = virsh.dominfo(vm_ref, ignore_status=True)
        status = result.exit_status
        output = result.stdout.strip()
        err = result.stderr.strip()
    else:
        status, output, err = remote_test(params, vm_name)

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
