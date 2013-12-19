from autotest.client.shared import error
from virttest import remote, libvirt_vm, virsh, libvirt_xml, utils_libvirtd


class StartError(Exception):

    """
    Error in starting vm.
    """

    def __init__(self, vm_name, output):
        Exception.__init__(self)
        self.vm_name = vm_name
        self.output = output

    def __str__(self):
        return str("Start vm %s Failed.\n"
                   "Output:%s"
                   % (self.vm_name, self.output))


def do_virsh_start(vm_name):
    """
    Start vm by using virsh start command.

    Throws a StartError if execute virsh start command failed.

    :param vm_ref: option of virsh start command.
    """
    cmd_result = virsh.command("start %s" % vm_name)

    if cmd_result.exit_status:
        raise StartError(vm_name, cmd_result.stderr)


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
    vm_name = params.get("vm_name", "vm1")
    backup_name = vm_name
    if vm_name is not "":
        vm = env.get_vm(vm_name)
    vmxml = libvirt_xml.VMXML()

    libvirtd_state = params.get("libvirtd", "on")
    pre_operation = params.get("vs_pre_operation", "")
    status_error = params.get("status_error", "no")

    # get the params for remote test
    remote_ip = params.get("remote_ip", "ENTER.YOUR.REMOTE.IP")
    remote_password = params.get(
        "remote_password", "ENTER.YOUR.REMOTE.PASSWORD")
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
            vm_name = new_vm_name
        elif pre_operation == "undefine":
            vmxml = vmxml.new_from_dumpxml(vm_name)
            vmxml.undefine()

        # do the start operation
        try:
            if pre_operation == "remote":
                # get remote session
                session = remote.wait_for_login("ssh", remote_ip, "22", "root",
                                                remote_password, "#")
                # get uri of local
                uri = libvirt_vm.complete_uri(local_ip)

                cmd = "virsh -c %s start %s" % (uri, vm_name)
                status, output = session.cmd_status_output(cmd)
                if status:
                    raise StartError(vm_name, output)
            else:
                do_virsh_start(vm_name)

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

        if (pre_operation == "undefine") and (not vmxml.xml is None):
            if not vmxml.define():
                raise error.TestError("Restore vm failed.")
        elif pre_operation == "rename":
            libvirt_xml.VMXML.vm_rename(vm, backup_name)
