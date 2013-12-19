import logging
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir, utils_misc, aexpect


@error.context_aware
def run(test, params, env):
    """
    Timer device check clock frequency offset using NTP on CPU starved guest:

    1) Check for an appropriate clocksource on host.
    2) Boot the guest.
    3) Copy time-warp-test.c to guest.
    4) Compile the time-warp-test.c.
    5) Stop ntpd and apply load on guest.
    6) Pin every vcpu to a physical cpu.
    7) Verify each vcpu is pinned on host.
    8) Run time-warp-test on guest.
    9) Start ntpd on guest.
    10) Check the drift in /var/lib/ntp/drift file on guest after hours
        of running.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def _drift_file_exist():
        try:
            session.cmd("test -f /var/lib/ntp/drift")
            return True
        except Exception:
            return False

    error.context("Check for an appropriate clocksource on host", logging.info)
    host_cmd = "cat /sys/devices/system/clocksource/"
    host_cmd += "clocksource0/current_clocksource"
    if not "tsc" in utils.system_output(host_cmd):
        raise error.TestNAError("Host must use 'tsc' clocksource")

    error.context("Boot the guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    sess_guest_load = vm.wait_for_login(timeout=timeout)

    error.context("Copy time-warp-test.c to guest", logging.info)
    src_file_name = os.path.join(data_dir.get_root_dir(), "shared", "deps",
                                 "time-warp-test.c")
    vm.copy_files_to(src_file_name, "/tmp")

    error.context("Compile the time-warp-test.c", logging.info)
    cmd = "cd /tmp/;"
    cmd += " yum install -y popt-devel;"
    cmd += " rm -f time-warp-test;"
    cmd += " gcc -Wall -o time-warp-test time-warp-test.c -lrt"
    sess_guest_load.cmd(cmd)

    error.context("Stop ntpd and apply load on guest", logging.info)
    sess_guest_load.cmd("yum install -y ntp; service ntpd stop")
    load_cmd = "for ((I=0; I<`grep 'processor id' /proc/cpuinfo| wc -l`; I++));"
    load_cmd += " do taskset -c $I /bin/bash -c 'for ((;;)); do X=1; done &';"
    load_cmd += " done"
    sess_guest_load.sendline(load_cmd)

    error.context("Pin every vcpu to a physical cpu", logging.info)
    host_cpu_cnt_cmd = params["host_cpu_cnt_cmd"]
    host_cpu_num = utils.system_output(host_cpu_cnt_cmd).strip()
    host_cpu_list = (_ for _ in range(int(host_cpu_num)))
    cpu_pin_list = zip(vm.vcpu_threads, host_cpu_list)
    if len(cpu_pin_list) < len(vm.vcpu_threads):
        raise error.TestNAError("There isn't enough physical cpu to"
                                " pin all the vcpus")
    for vcpu, pcpu in cpu_pin_list:
        utils.system("taskset -p -c %s %s" % (pcpu, vcpu))

    error.context("Verify each vcpu is pinned on host", logging.info)

    error.context("Run time-warp-test", logging.info)
    session = vm.wait_for_login(timeout=timeout)
    cmd = "/tmp/time-warp-test > /dev/null &"
    session.sendline(cmd)

    error.context("Start ntpd on guest", logging.info)
    cmd = "service ntpd start; sleep 1; echo"
    session.cmd(cmd)

    error.context("Check if the drift file exists on guest", logging.info)
    test_run_timeout = float(params["test_run_timeout"])
    try:
        utils_misc.wait_for(_drift_file_exist, test_run_timeout, step=5)
    except aexpect.ShellCmdError, detail:
        raise error.TestError("Failed to wait for the creation of"
                              " /var/lib/ntp/drift file. Detail: '%s'" % detail)

    error.context("Verify the drift file content on guest", logging.info)
    output = session.cmd("cat /var/lib/ntp/drift")
    if int(output) > 20:
        raise error.TestFail("Failed to check the ntp drift."
                             " Output: '%s'" % output)
