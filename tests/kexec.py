import logging, os
from autotest.client.shared import error

def run_kexec(test, params, env):
    """
    Reboot to new kernel through kexec command:
    1) Boot guest with x2apic cpu flag.
    2) Install a new kernel if only one kernel installed.
    3) Reboot to new kernel through kexec command.
    4) Check x2apic flag if need.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    cmd_timeout = int(params.get("cmd_timeout", 360))

    def check_x2apic_flag():
        x86info_link = os.path.join(test.bindir, "tests_rsc/x86info*")
        vm.copy_files_to(x86info_link, "/root/x86info.tar")

        setup_x86info_cmd = "tar -xvf x86info.tar && cd x86info && make"
        session.cmd_output(setup_x86info_cmd, timeout=cmd_timeout)
        check_x2apic_cmd = "/root/x86info/x86info -f"
        (s, o) = session.cmd_status_output(check_x2apic_cmd)
        if "x2apic" not in o:
            raise error.TestFail("There is no x2apic flag in guest cpu.\n"
                                 "Output got from x86info:\n%s" % o)

    def install_new_kernel():
        from autotest.client.tests.kvm.tests import rh_kernel_update
        try:
            rh_kernel_update.run_rh_kernel_update(test, params, env)
        except Exception:
            raise error.TestError("Fail to install a new kernel!")

    check_x2apic = params.get("check_x2apic", "yes")
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
    o = session.cmd_output(cmd,timeout=cmd_timeout)
    kernels = o.split()
    new_kernel = None
    for kernel in kernels:
        kernel = kernel.strip()
        if cur_kernel_version not in kernel:
            new_kernel = kernel[7:]
    if not new_kernel:
        raise error.TestError("Could not find new kernel, "
                              "command line output: %s" % o)

    logging.info("Will reboot to kernel %s through kexec" % new_kernel)
    cmd = params.get("get_kernel_image") % new_kernel
    kernel_file = session.cmd_output(cmd).strip().splitlines()[0]
    cmd = params.get("get_kernel_ramdisk") % new_kernel
    init_file = session.cmd_output(cmd).strip().splitlines()[0]
    cmd = params.get("load_kernel_cmd") % (kernel_file, init_file)
    session.cmd_output(cmd,timeout=cmd_timeout)
    cmd = params.get("kexec_reboot_cmd")
    session.sendline(cmd)
    session = vm.wait_for_login(timeout=login_timeout)
    kernel = session.cmd_output(check_cur_kernel_cmd).strip()
    logging.info("Current kernel is: %s" % kernel)
    if kernel.strip() != new_kernel.strip():
        raise error.TestFail("Fail to boot to kernel %s, current kernel is %s"
                             %(new_kernel, kernel))
    if "yes" in check_x2apic:
        check_x2apic_flag()
    session.close()
