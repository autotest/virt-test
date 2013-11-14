import logging
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest
    2) Check, configure and enable the kdump
    3) Trigger a crash by 'sysrq-trigger' and check the vmcore for
       each vcpu, or only trigger one crash with nmi interrupt and
       check vmcore.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    crash_timeout = float(params.get("crash_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    def_kernel_param_cmd = ("grubby --update-kernel=`grubby --default-kernel`"
                            " --args=crashkernel=128M@16M")
    kernel_param_cmd = params.get("kernel_param_cmd", def_kernel_param_cmd)
    def_kdump_enable_cmd = "chkconfig kdump on && service kdump restart"
    kdump_enable_cmd = params.get("kdump_enable_cmd", def_kdump_enable_cmd)
    def_crash_kernel_prob_cmd = "grep -q 1 /sys/kernel/kexec_crash_loaded"
    crash_kernel_prob_cmd = params.get("crash_kernel_prob_cmd",
                                       def_crash_kernel_prob_cmd)

    def crash_test(vcpu):
        """
        Trigger a crash dump through sysrq-trigger

        :param vcpu: vcpu which is used to trigger a crash
        """
        session = vm.wait_for_login(timeout=timeout)
        session.cmd_output("rm -rf /var/crash/*")

        if crash_cmd == "nmi":
            session.cmd("echo 1 > /proc/sys/kernel/unknown_nmi_panic")
            vm.monitor.nmi()
        else:
            logging.info("Triggering crash on vcpu %d ...", vcpu)
            session.sendline("taskset -c %d %s" % (vcpu, crash_cmd))

        if not utils_misc.wait_for(lambda: not session.is_responsive(), 240, 0,
                                   1):
            raise error.TestFail("Could not trigger crash on vcpu %d" % vcpu)

        error.context("Waiting for kernel crash dump to complete",
                      logging.info)
        session = vm.wait_for_login(timeout=crash_timeout)

        error.context("Probing vmcore file...", logging.info)
        session.cmd("ls -R /var/crash | grep vmcore")
        logging.info("Found vmcore.")

        session.cmd_output("rm -rf /var/crash/*")

    try:
        error.context("Checking the existence of crash kernel...",
                      logging.info)
        try:
            session.cmd(crash_kernel_prob_cmd)
        except Exception:
            error.context("Crash kernel is not loaded. Trying to load it",
                          logging.info)
            session.cmd(kernel_param_cmd)
            session = vm.reboot(session, timeout=timeout)

        if params.get("kdump_config"):
            error.context("Configuring the Core Collector", logging.info)
            config_file = "/etc/kdump.conf"
            for config_line in params.get("kdump_config").split(";"):
                config_cmd = "grep '^%s$' %s || echo -e '%s' >> %s "
                config_con = config_line.strip()
                session.cmd(config_cmd % ((config_con, config_file) * 2))

        error.context("Enabling kdump service...", logging.info)
        # the initrd may be rebuilt here so we need to wait a little more
        session.cmd(kdump_enable_cmd, timeout=120)

        error.context("Kdump Testing, force the Linux kernel to crash",
                      logging.info)
        crash_cmd = params.get("crash_cmd", "echo c > /proc/sysrq-trigger")
        if crash_cmd == "nmi":
            crash_test(None)
        else:
            # trigger crash for each vcpu
            nvcpu = int(params.get("smp", 1))
            for i in range(nvcpu):
                crash_test(i)

    finally:
        session.close()
