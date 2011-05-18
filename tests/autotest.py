import os, logging, sys
from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import virt_test_utils


def run_autotest(test, params, env, machine=None, kvm_test=False):
    """
    Run an autotest test inside a guest.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    if machine is None:
        machine = env.get_vm(params["main_vm"])
    machine.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = machine.wait_for_login(timeout=timeout)

    # Collect test parameters
    timeout = int(params.get("test_timeout", 300))
    control_path = None
    if not kvm_test:
        control_path = os.path.join(test.bindir, "autotest_control",
                                    params.get("test_control_file"))
    outputdir = test.outputdir
    virt_test_utils.run_autotest(machine, session, control_path, timeout,
                            outputdir, params, kvm_test)

def run_autotest_background(test, params, env, test_name = "dbench",
                            test_control_file="control", machine=None,
                            kvm_test=False):
    """
    Wrapper of run_autotest() and make it run in the background through fork()
    and let it run in the child process.
    1) Flush the stdio.
    2) Build test params which is recevied from arguments and used by
       run_autotest()
    3) Fork the process and let the run_autotest() run in the child
    4) Catch the exception raise by run_autotest() and exit the child with
       non-zero return code.
    5) If no exception catched, reutrn 0

    @param test: kvm test object
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
        run_autotest(test, params, env, machine, kvm_test)
        os.remove(flag_fname)
    except error.TestFail, message_fail:
        logging.info("[Autotest Background FAIL] %s" % message_fail)
        os.remove(flag_fname)
        os._exit(1)
    except error.TestError, message_error:
        logging.info("[Autotest Background ERROR] %s" % message_error)
        os.remove(flag_fname)
        os._exit(2)
    except:
        os.remove(flag_fname)
        os._exit(3)

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
