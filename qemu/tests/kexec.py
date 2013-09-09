import logging
import os
from autotest.client.shared import error
from virttest import data_dir


@error.context_aware
def run_kexec(test, params, env):
    """
    Reboot to new kernel through kexec command:
    1) Boot guest with x2apic cpu flag.
    2) Check x2apic enabled in guest if need.
    2) Install a new kernel if only one kernel installed.
    3) Reboot to new kernel through kexec command.
    4) Check x2apic enabled in guest again if need.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def check_x2apic_flag():
        x2apic_enabled = False
        error.context("Check x2apic enabled in guest", logging.info)
        x2apic_output = session.cmd_output(check_x2apic_cmd).strip()
        x2apic_check_string = params.get("x2apic_check_string").split(",")
        for check_string in x2apic_check_string:
            if check_string.strip() in x2apic_output:
                x2apic_enabled = True
        if not x2apic_enabled:
            raise error.TestFail("x2apic is not enabled in guest.")

    def install_new_kernel():
        error.context("Install a new kernel in guest", logging.info)
        try:
            # pylint: disable=E0611
            from qemu.tests import rh_kernel_update
            rh_kernel_update.run_rh_kernel_update(test, params, env)
        except Exception, detail:
            raise error.TestError("Failed to install a new kernel in "
                                  "guest: %s" % detail)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    cmd_timeout = int(params.get("cmd_timeout", 360))
    check_x2apic = params.get("check_x2apic", "yes")
    check_x2apic_cmd = params.get("check_x2apic_cmd")
    if "yes" in check_x2apic:
        check_x2apic_flag()
    cmd = params.get("kernel_count_cmd")
    count = session.cmd_output(cmd, timeout=cmd_timeout)
    kernel_num = int(count)
    if kernel_num <= 1:
        # need install a new kernel
        install_new_kernel()
        session = vm.wait_for_login(timeout=login_timeout)
        count = session.cmd_output(cmd, timeout=cmd_timeout)
        if int(count) <= 1:
            raise error.TestError("Could not find a new kernel "
                                  "after rh_kernel_update.")

    check_cur_kernel_cmd = params.get("check_cur_kernel_cmd")
    cur_kernel_version = session.cmd_output(check_cur_kernel_cmd).strip()
    logging.info("Current kernel is: %s" % cur_kernel_version)
    cmd = params.get("check_installed_kernel")
    output = session.cmd_output(cmd, timeout=cmd_timeout)
    kernels = output.split()
    new_kernel = None
    for kernel in kernels:
        kernel = kernel.strip()
        if cur_kernel_version not in kernel:
            new_kernel = kernel[7:]
    if not new_kernel:
        raise error.TestError("Could not find new kernel, "
                              "command line output: %s" % output)
    msg = "Reboot to kernel %s through kexec" % new_kernel
    error.context(msg, logging.info)
    cmd = params.get("get_kernel_image") % new_kernel
    kernel_file = session.cmd_output(cmd).strip().splitlines()[0]
    cmd = params.get("get_kernel_ramdisk") % new_kernel
    init_file = session.cmd_output(cmd).strip().splitlines()[0]
    cmd = params.get("load_kernel_cmd") % (kernel_file, init_file)
    session.cmd_output(cmd, timeout=cmd_timeout)
    cmd = params.get("kexec_reboot_cmd")
    session.sendline(cmd)
    session = vm.wait_for_login(timeout=login_timeout)
    kernel = session.cmd_output(check_cur_kernel_cmd).strip()
    logging.info("Current kernel is: %s" % kernel)
    if kernel.strip() != new_kernel.strip():
        raise error.TestFail("Fail to boot to kernel %s, current kernel is %s"
                             % (new_kernel, kernel))
    if "yes" in check_x2apic:
        check_x2apic_flag()
    session.close()
