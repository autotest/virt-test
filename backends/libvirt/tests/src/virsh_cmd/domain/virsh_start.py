from autotest.client.shared import error
from virttest import remote, libvirt_vm, virsh, libvirt_xml, utils_libvirtd


class StartError(Exception):

    """
    Error in starting vm.
    """

    def __init__(self, vm_ref, output):
        Exception.__init__(self)
        self.vm_ref = vm_ref
        self.output = output

    def __str__(self):
        return str("Start vm %s Failed.\n"
                   "Output:%s"
                   % (self.vm_ref, self.output))


def do_virsh_start(vm_ref):
    """
    Start vm by using virsh start command.

    Throws a StartError if execute virsh start command failed.

    :param vm_ref: option of virsh start command.
    """
    cmd_result = virsh.command("start %s" % vm_ref)

    if cmd_result.exit_status:
        raise StartError(vm_ref, cmd_result.stderr)


def run(test, params, env):
    """
    Test command: virsh start.

    1) Get the params from params.
    2) Prepare libvirtd's status.
    3) Do the start operation.
    4) Result check.
    5) clean up.
    """
    # get the params from params
    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm_ref = params.get("vm_ref", "vm1")

    # Backup for recovery.
    vmxml_backup = libvirt_xml.vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    backup_name = vm_ref
    if vm_ref is not "":
        vm = env.get_vm(vm_ref)
    vmxml = libvirt_xml.VMXML()

    libvirtd_state = params.get("libvirtd", "on")
    pre_operation = params.get("vs_pre_operation", "")
    status_error = params.get("status_error", "no")

    # get the params for remote test
    remote_ip = params.get("remote_ip", "ENTER.YOUR.REMOTE.IP")
    remote_pwd = params.get("remote_pwd", "ENTER.YOUR.REMOTE.PASSWORD")
    local_ip = params.get("local_ip", "ENTER.YOUR.LOCAL.IP")
    if pre_operation == "remote" and (remote_ip.count("ENTER.YOUR.") or
                                      local_ip.count("ENTER.YOUR.")):
        raise error.TestNAError("Remote test parameters not configured")

    try:
        # prepare before start vm
        if libvirtd_state == "on":
            utils_libvirtd.libvirtd_start()
        elif libvirtd_state == "off":
            utils_libvirtd.libvirtd_stop()

        if pre_operation == "rename":
            new_vm_name = params.get("vs_new_vm_name", "virsh_start_vm1")
            vm = libvirt_xml.VMXML.vm_rename(vm, new_vm_name)
            vm_ref = new_vm_name
        elif pre_operation == "undefine":
            vmxml = vmxml.new_from_dumpxml(vm_ref)
            vmxml.undefine()

        # do the start operation
        try:
            if pre_operation == "remote":
                # get remote session
                session = remote.wait_for_login("ssh", remote_ip, "22", "root",
                                                remote_pwd, "#")
                # get uri of local
                uri = libvirt_vm.complete_uri(local_ip)

                cmd = "virsh -c %s start %s" % (uri, vm_ref)
                status, output = session.cmd_status_output(cmd)
                if status:
                    raise StartError(vm_ref, output)
            else:
                do_virsh_start(vm_ref)

            # start vm successfully
            if status_error == "yes":
                raise error.TestFail("Run successfully with wrong command!")

        except StartError, excpt:
            # start vm failed
            if status_error == "no":
                raise error.TestFail("Run failed with right command: %s",
                                     str(excpt))
    finally:
        # clean up
        if libvirtd_state == "off":
            utils_libvirtd.libvirtd_start()

        elif pre_operation == "rename":
            libvirt_xml.VMXML.vm_rename(vm, backup_name)

        # Restore VM
        vmxml_backup.sync()
