import os, logging, sys
from autotest.client.shared import error
from virttest import utils_test


def run_guest_autotest(test, params, env):
    """
    Run an autotest test inside a guest.

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    # Collect test parameters
    timeout = int(params.get("test_timeout", 300))
    control_path = os.path.join(test.virtdir, "autotest_control",
                                params.get("test_control_file"))
    outputdir = test.outputdir

    utils_test.run_autotest(vm, session, control_path, timeout, outputdir,
                                 params)

def run_guest_autotest_background(test, params, env, test_name="dbench",
                            test_control_file="control"):
    """
    Wrapper of run_guest_autotest() and make it run in the background through
    fork() and let it run in the child process.
    1) Flush the stdio.
    2) Build test params which is recevied from arguments and used by
       run_guest_autotest()
    3) Fork the process and let the run_guest_autotest() run in the child
    4) Catch the exception raise by run_guest_autotest() and exit the child with
       non-zero return code.
    5) If no exception catched, reutrn 0

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    @param test_name: The name of testcase which would be executed in the guest
    @param test_control_file: The control file of autotest running in the guest
    """
    def flush():
        sys.stdout.flush()
        sys.stderr.flush()

    logging.info("Running autotest background ...")
    flush()
    pid = os.fork()
    if pid:
        # Parent process
        return pid

    flag_fname = "/tmp/autotest-flag-file-pid-" + str(os.getpid())
    open(flag_fname, 'w').close()
    try:
        params['test_name'] = test_name
        params['test_control_file'] = test_control_file
        # Launch autotest
        run_guest_autotest(test, params, env)
        os.remove(flag_fname)
    except error.TestFail, message_fail:
        logging.info("[Autotest Background FAIL] %s" % message_fail)
        os.remove(flag_fname)
        os._exit(1)
    except error.TestError, message_error:
        logging.info("[Autotest Background ERROR] %s" % message_error)
        os.remove(flag_fname)
        os._exit(2)
    logging.info("[Auototest Background GOOD]")
    os._exit(0)


def wait_autotest_background(pid):
    """
    Wait for background autotest finish.

    @param pid: Pid of the child process executing background autotest
    """
    logging.info("Waiting for background autotest to finish ...")

    (pid, s) = os.waitpid(pid,0)
    status = os.WEXITSTATUS(s)
    if status != 0:
        return False
    return True

