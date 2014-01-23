import logging
from autotest.client.shared import error
from virttest import utils_misc


def kdump_enable(vm, vm_name, crash_kernel_prob_cmd,
                 kernel_param_cmd, kdump_enable_cmd, timeout):
    """
    Check, configure and enable the kdump

    :param vm_name: vm name
    :param crash_kernel_prob_cmd: check kdume loaded
    :param kernel_param_cmd: the param add into kernel line for kdump
    :param kdump_enable_cmd: enable kdump command
    :param timeout: Timeout in seconds
    """
    error.context("Try to log into guest '%s'." % vm_name, logging.info)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Checking the existence of crash kernel in %s" %
                  vm_name, logging.info)
    try:
        session.cmd(crash_kernel_prob_cmd)
    except Exception:
        error.context("Crash kernel is not loaded. Trying to load it",
                      logging.info)
        session.cmd(kernel_param_cmd)
        session = vm.reboot(session, timeout=timeout)

    if vm.params.get("kdump_config"):
        error.context("Configuring the Core Collector", logging.info)
        config_file = "/etc/kdump.conf"
        for config_line in vm.params.get("kdump_config").split(";"):
            config_cmd = "grep '^%s$' %s || echo -e '%s' >> %s "
            config_con = config_line.strip()
            session.cmd(config_cmd % ((config_con, config_file) * 2))

    error.context("Enabling kdump service...", logging.info)
    # the initrd may be rebuilt here so we need to wait a little more
    session.cmd(kdump_enable_cmd, timeout=120)

    return session


def crash_test(vm, vcpu, crash_cmd, timeout):
    """
    Trigger a crash dump through sysrq-trigger

    :param vcpu: vcpu which is used to trigger a crash
    :param crash_cmd: crash_cmd which is triggered crash command
    :param timeout: Timeout in seconds
    """
    session = vm.wait_for_login(timeout=timeout)

    logging.info("Delete the vmcore file.")
    session.cmd_output("rm -rf /var/crash/*")

    if crash_cmd == "nmi":
        logging.info("Triggering crash with 'nmi' interrupt")
        session.cmd("echo 1 > /proc/sys/kernel/unknown_nmi_panic")
        vm.monitor.nmi()
    else:
        logging.info("Triggering crash on vcpu %d ...", vcpu)
        session.sendline("taskset -c %d %s" % (vcpu, crash_cmd))


def check_vmcore(vm, session, timeout):
    """
    Check the vmcore file after triggering a crash

    :param session: A shell session object or None.
    :param timeout: Timeout in seconds
    """
    if not utils_misc.wait_for(lambda: not session.is_responsive(), 240, 0,
                               1):
        raise error.TestFail("Could not trigger crash")

    error.context("Waiting for kernel crash dump to complete",
                  logging.info)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Probing vmcore file...", logging.info)
    try:
        session.cmd("ls -R /var/crash | grep vmcore")
    except Exception:
        raise error.TestFail("Could not found vmcore file.")

    logging.info("Found vmcore.")


@error.context_aware
def run(test, params, env):
    """
    KVM kdump test:
    1) Log into the guest(s)
    2) Check, configure and enable the kdump
    3) Trigger a crash by 'sysrq-trigger' and check the vmcore for each vcpu,
       or only trigger one crash with 'nmi' interrupt and check vmcore.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    timeout = float(params.get("login_timeout", 240))
    crash_timeout = float(params.get("crash_timeout", 360))
    def_kernel_param_cmd = ("grubby --update-kernel=`grubby --default-kernel`"
                            " --args=crashkernel=128M@16M")
    kernel_param_cmd = params.get("kernel_param_cmd", def_kernel_param_cmd)
    def_kdump_enable_cmd = "chkconfig kdump on && service kdump restart"
    kdump_enable_cmd = params.get("kdump_enable_cmd", def_kdump_enable_cmd)
    def_crash_kernel_prob_cmd = "grep -q 1 /sys/kernel/kexec_crash_loaded"
    crash_kernel_prob_cmd = params.get("crash_kernel_prob_cmd",
                                       def_crash_kernel_prob_cmd)

    vms = params.get("vms", "vm1 vm2").split()
    vm_list = []
    session_list = []

    for vm_name in vms:
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        vm_list.append(vm)

        session = kdump_enable(vm, vm_name, crash_kernel_prob_cmd,
                               kernel_param_cmd, kdump_enable_cmd, timeout)
        session_list.append(session)

    for vm in vm_list:
        error.context("Kdump Testing, force the Linux kernel to crash",
                      logging.info)
        crash_cmd = params.get("crash_cmd", "echo c > /proc/sysrq-trigger")
        if crash_cmd == "nmi":
            crash_test(vm, None, crash_cmd, timeout)
        else:
            # trigger crash for each vcpu
            nvcpu = int(params.get("smp", 1))
            for i in range(nvcpu):
                crash_test(vm, i, crash_cmd, timeout)

    for i in range(len(vm_list)):
        error.context("Check the vmcore file after triggering a crash",
                      logging.info)
        check_vmcore(vm_list[i], session_list[i], crash_timeout)
