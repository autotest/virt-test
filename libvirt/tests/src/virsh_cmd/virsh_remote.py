import logging
from autotest.client.shared import error
from virttest import libvirt_vm, virsh


def run_virsh_remote(test, params, env):
    """
    Test virsh commands with remote session.
    """
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    cmd_list = params.get("vr_cmd_list", "list").split(',')
    host_cmd = "host" == params.get("vr_type", "host")
    start_vm = "yes" == params.get("start_vm")

    remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
    remote_pwd = params.get("remote_pwd", None)
    remote_user = params.get("remote_user", "root")
    local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
    remote_uri = libvirt_vm.complete_uri(local_ip)
    remote_args = {'remote_user': remote_user, 'remote_ip': remote_ip,
                   'remote_pwd': remote_pwd, 'uri': remote_uri}
    vcb = virsh.VirshConnectBack(**remote_args)
    if not vcb.kosher_args(remote_ip, remote_uri):
        vcb.close_session()
        raise error.TestNAError("Check your configuration of "
                                "remote and local ip.")

    fail_info = []
    for cmd in cmd_list:
        if not host_cmd:
            cmd = "%s %s" % (cmd, vm_name)

        # Prepare vm's state
        if vm.is_dead() and start_vm:
            vm.start()
        elif vm.is_alive() and not start_vm:
            vm.destroy()

        result = vcb.command(cmd, ignore_status=True)
        if result.exit_status:
            fail_info.append(result)
    vcb.close_session()
    if len(fail_info):
        raise error.TestFail("Execute remote virsh command failed:"
                             "\n%s" % fail_info)
