import logging
import commands
from autotest.client.shared import error
from virttest import virsh, utils_misc


def run(test, params, env):
    """
    Test virsh reset command
    """

    if not virsh.has_help_command('reset'):
        raise error.TestNAError("This version of libvirt does not support "
                                "the reset test")

    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm_ref = params.get("reset_vm_ref")
    readonly = params.get("readonly", False)
    status_error = ("yes" == params.get("status_error", "no"))
    start_vm = ("yes" == params.get("start_vm"))

    vm = env.get_vm(vm_name)
    domid = vm.get_id()
    domuuid = vm.get_uuid()
    bef_pid = commands.getoutput("pidof -s qemu-kvm")

    if vm_ref == 'id':
        vm_ref = domid
    elif vm_ref == 'uuid':
        vm_ref = domuuid
    else:
        vm_ref = vm_name

    tmpfile = "/home/%s" % utils_misc.generate_random_string(6)
    logging.debug("tmpfile is %s", tmpfile)
    if start_vm:
        session = vm.wait_for_login()
        session.cmd("touch %s" % tmpfile)
        status = session.get_command_status("ls %s" % tmpfile)
        if status == 0:
            logging.info("Succeed generate file %s", tmpfile)
        else:
            raise error.TestFail("Touch command failed!")

    # record the pid before reset for compare
    output = virsh.reset(vm_ref, readonly=readonly)
    if output.exit_status != 0:
        if status_error:
            logging.info("Failed to reset guest as expected, Error:%s.",
                         output.stderr)
            return
        else:
            raise error.TestFail("Failed to reset guest, Error:%s." %
                                 output.stderr)
    elif status_error:
        raise error.TestFail("Expect fail, but succeed indeed.")

    session.close()
    session = vm.wait_for_login()
    status = session.get_command_status("ls %s" % tmpfile)
    if status == 0:
        raise error.TestFail("Fail to reset guest, tmpfile still exist!")
    else:
        aft_pid = commands.getoutput("pidof -s qemu-kvm")
        if bef_pid == aft_pid:
            logging.info("Succeed to check guest reset, tmpfile disappeared.")
        else:
            raise error.TestFail("Domain pid changed after reset!")
    session.close()
