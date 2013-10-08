import logging
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run_stop_continue(test, params, env):
    """
    Suspend a running Virtual Machine and verify its state.

    1) Boot the vm
    2) Do preparation operation (Optional)
    3) Start a background process (Optional)
    4) Stop the VM
    5) Verify the status of VM is 'paused'
    6) Verify the session has no response
    7) Resume the VM
    8) Verify the status of VM is 'running'
    9) Re-login the guest
    10) Do check operation (Optional)
    11) Do clean operation (Optional)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=login_timeout)
    session_bg = None

    start_bg_process = params.get("start_bg_process")
    try:
        prepare_op = params.get("prepare_op")
        if prepare_op:
            error.context("Do preparation operation: '%s'" % prepare_op,
                          logging.info)
            op_timeout = float(params.get("prepare_op_timeout", 60))
            session.cmd(prepare_op, timeout=op_timeout)

        if start_bg_process:
            bg_cmd = params.get("bg_cmd")
            error.context("Start a background process: '%s'" % bg_cmd,
                          logging.info)
            session_bg = vm.wait_for_login(timeout=login_timeout)
            bg_cmd_timeout = float(params.get("bg_cmd_timeout", 240))
            args = (bg_cmd, bg_cmd_timeout)

            bg = utils_test.BackgroundTest(session_bg.cmd, args)
            bg.start()

        error.base_context("Stop the VM", logging.info)
        vm.pause()
        error.context("Verify the status of VM is 'paused'", logging.info)
        vm.verify_status("paused")

        error.context("Verify the session has no response", logging.info)
        if session.is_responsive():
            msg = "Session is still responsive after stop"
            logging.error(msg)
            raise error.TestFail(msg)

        error.base_context("Resume the VM", logging.info)
        vm.resume()
        error.context("Verify the status of VM is 'running'", logging.info)
        vm.verify_status("running")

        error.context("Re-login the guest", logging.info)
        session = vm.wait_for_login(timeout=login_timeout)

        if start_bg_process:
            if bg:
                bg.join()

        check_op = params.get("check_op")
        if check_op:
            error.context("Do check operation: '%s'" % check_op, logging.info)
            op_timeout = float(params.get("check_op_timeout", 60))
            s, o = session.cmd_status_output(check_op, timeout=op_timeout)
            if s != 0:
                raise error.TestFail("Something wrong after stop continue, "
                                     "check command report: %s" % o)
    finally:
        clean_op = params.get("clean_op")
        if clean_op:
            error.context("Do clean operation: '%s'" % clean_op, logging.info)
            op_timeout = float(params.get("clean_op_timeout", 60))
            session.cmd(clean_op, timeout=op_timeout, ignore_all_errors=True)
