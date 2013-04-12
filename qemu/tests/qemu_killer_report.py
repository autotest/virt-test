import logging, time, os, re
from autotest.client.shared import error
from virttest import utils_misc


def run_qemu_killer_report(test, params, env):
    """
    Test that QEMU report the process ID that sent it kill signals.

    1) Start a VM.
    2) Kill VM by signal 15 in another process.
    3) Check that QEMU report the process ID that sent it kill signals.

    @param test: Kvm test object
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    def kill_vm_by_signal_15():
        vm_pid = vm.get_pid()
        logging.info("VM: %s, PID: %s" % (vm.name, vm_pid))
        thread_pid = os.getpid()
        logging.info("Main Process ID is %s" % thread_pid)
        utils_misc.kill_process_tree(vm_pid, 15)
        return thread_pid

    re_str = "terminating on signal 15 from pid ([0-9]*)"
    re_str = params.get("qemu_error_re", re_str)
    logging.info("Kill VM by signal 15")
    thread_pid = kill_vm_by_signal_15()
    # Wait qemu print error log.
    time.sleep(30)
    log = os.path.join(test.debugdir, "%s.INFO" % test.tagged_testname)
    files = open(log, "r")
    txt = files.read()
    results = re.findall(re_str, txt)
    debug = "Regular expression operation result from qemu output:%s" % results
    logging.debug(debug)
    if not results:
        raise error.TestFail("qemu did not tell us who kill it")
    pid = results[-1]
    if int(pid) != thread_pid:
        msg = "QEMU return wrong PID. Process that kill qemu: %s" % thread_pid
        msg += "But QEMU report: %s" % pid
        raise error.TestFail(msg)
