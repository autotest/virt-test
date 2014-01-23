from autotest.client.shared import error
from virttest import libvirt_vm, virsh, remote, utils_libvirtd


def run(test, params, env):
    """
    Test command: virsh dommemstat.

    The command gets memory statistics for a domain
    1.Prepare test environment.
    2.When the ibvirtd == "off", stop the libvirtd service.
    3.Perform virsh dommemstat operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    status_error = params.get("status_error", "no")
    vm_ref = params.get("dommemstat_vm_ref", "name")
    libvirtd = params.get("libvirtd", "on")
    extra = params.get("dommemstat_extra", "")
    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

     # run test case
    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref.count("_invalid_"):
        # vm_ref names parameter to fetch
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s" % vm_name

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    if vm_ref != "remote":
        status = virsh.dommemstat(vm_ref, extra, ignore_status=True,
                                  debug=True).exit_status
    else:
        remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
        remote_pwd = params.get("remote_pwd", None)
        local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
        if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
            raise error.TestNAError("local/remote ip parameters not set.")
        status = 0
        try:
            remote_uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s dommemstat %s %s" % (remote_uri, vm_name,
                                                        extra)
            status = session.cmd_status(command, internal_timeout=5)
            session.close()
        except error.CmdError:
            status = 1

    # recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
