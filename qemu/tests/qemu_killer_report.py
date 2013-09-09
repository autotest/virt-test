import logging
import os
import re
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run_qemu_killer_report(test, params, env):
    """
    Test that QEMU report the process ID that sent it kill signals.

    1) Start a VM.
    2) Kill VM by signal 15 in another process.
    3) Check that QEMU report the process ID that sent it kill signals.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """

    def kill_vm_by_signal_15():
        vm_pid = vm.get_pid()
        logging.info("VM: %s, PID: %s" % (vm.name, vm_pid))
        thread_pid = os.getpid()
        logging.info("Main Process ID is %s" % thread_pid)
        utils_misc.kill_process_tree(vm_pid, 15)
        return thread_pid

    def killer_report(re_str):
        output = vm.process.get_output()
        results = re.findall(re_str, output)
        if results:
            return results
        else:
            return False

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    re_str = "terminating on signal 15 from pid ([0-9]+)"
    re_str = params.get("qemu_error_re", re_str)
    error.context("Kill VM by signal 15", logging.info)
    thread_pid = kill_vm_by_signal_15()
    # Wait QEMU print error log.
    results = utils_misc.wait_for(lambda: killer_report(re_str),
                                  60, 2, 2)
    error.context("Check that QEMU can report who killed it", logging.info)
    if not results:
        raise error.TestFail("QEMU did not tell us who killed it")
    elif int(results[-1]) != thread_pid:
        msg = "QEMU identified the process that killed it incorrectly. "
        msg += "Killer PID: %s, " % thread_pid
        msg += "QEMU reported PID: %s" % int(results[-1])
        raise error.TestFail(msg)
    else:
        logging.info("QEMU identified the process that killed it properly")
