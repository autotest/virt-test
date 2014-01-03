import logging
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test virsh inject-nmi command
    """

    if not virsh.has_help_command('inject-nmi'):
        raise error.TestNAError("This version of libvirt does not support the "
                                "inject-nmi test")
    if not virsh.has_help_command('qemu-monitor-command'):
        raise error.TestNAError("This version of libvirt does not support the "
                                "qemu-monitor-command test")

    vm_name = params.get("main_vm", "virt-tests-vm1")
    readonly = params.get("readonly", False)
    status_error = ("yes" == params.get("status_error", "no"))

    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()

    num_bef = session.get_command_output("cat /proc/interrupts |"
                                         "grep NMI").split()[1]

    def inject_nmi_check(expect_num):
        """
        Do inject nmi check in guest

        :param expect_num: expect num difference, int type
        """
        session.get_command_status("sync")
        num_aft = session.get_command_output("cat /proc/interrupts |"
                                             "grep NMI").split()[1]
        if int(num_aft) - int(num_bef) == expect_num:
            logging.info("Succeed to check inject nmi in guest")
        else:
            raise error.TestFail("Fail to check inject nmi in guest")

    try:
        output = virsh.inject_nmi(vm_name, readonly=readonly)
        if output.exit_status != 0:
            if status_error:
                logging.info("Failed to inject nmi to guest as expected, Error"
                             ":%s.", output.stderr)
                return
            else:
                raise error.TestFail("Failed to inject nmi to guest, Error:%s."
                                     % output.stderr)
        elif status_error:
            raise error.TestFail("Expect fail, but succeed indeed.")
        inject_nmi_check(1)

        output = virsh.qemu_monitor_command(vm_name, "nmi")
        if output.exit_status != 0:
            raise error.TestFail("Failed to inject nmi by qemu-monitor-command"
                                 ", Error:%s." % output.stderr)
        inject_nmi_check(2)

    finally:
        session.close()
