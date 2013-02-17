from autotest.client.shared import error
from virttest import virsh, remote, libvirt_vm

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
        libvirt_vm.libvirtd_stop()

    #run test case
    vm_ref = params.get("vcpuinfo_vm_ref")
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    def remote_case(params, vm_name):
        """
        Test remote case.
        """
        remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
        remote_pwd = params.get("remote_pwd", None)
        local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
        if remote_ip.count("EXAMPLE.COM") or local_ip.count("EXAMPLE.COM"):
            raise error.TestNAError("Remote test defaults not changed")
        status = 0
        output = ""
        err = ""
        try:
            remote_uri = libvirt_vm.complete_uri(local_ip)
            session = remote.remote_login("ssh", remote_ip, "22", "root",
                                          remote_pwd, "#")
            session.cmd_output('LANG=C')
            command = "virsh -c %s vcpuinfo %s" % (remote_uri, vm_name)
            status, output = session.cmd_status_output(command,
                                                       internal_timeout=5)
            session.close()
            if status != 0:
                err = output
        except error.CmdError:
            status = 1
            output = ""
            err = "remote test failed"
        return status, output, err


    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif  vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("vcpuinfo_extra"))

    if vm_ref == "remote":
        status, output, err = remote_case(params, vm_name)
    else:
        result = virsh.vcpuinfo(vm_ref)
        status = result.exit_status
        output = result.stdout.strip()
        err = result.stderr.strip()

    #recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()

    #check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
