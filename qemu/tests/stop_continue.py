import logging
from autotest.client.shared import error, utils


def run_stop_continue(test, params, env):
    """
    Suspend a running Virtual Machine and verify its state.

    1) Boot the vm
    2) Suspend the vm through stop command
    3) Verify the state through info status command
    4) Check is the ssh session to guest is still responsive,
       if succeed, fail the test.

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=login_timeout)
    session_bg = None

    try:
        if params.get("prepare_op"):
            op_timeout = float(params.get("prepare_op_timeout", 60))
            session.cmd(params.get("prepare_op"), timeout=op_timeout)

        if params.get("start_bg_process"):
            session_bg = vm.wait_for_login(timeout=login_timeout)
            bg_cmd_timeout = float(params.get("bg_cmd_timeout", 240))
            bg = utils.InterruptedThread(session_bg.cmd,
                                         kwargs={'cmd': params.get("bg_cmd"),
                                                 'timeout': bg_cmd_timeout,})
            bg.start()

        logging.info("Stop the VM")
        vm.pause()
        logging.info("Verifying the status of VM is 'paused'")
        vm.verify_status("paused")

        logging.info("Check the session is responsive")
        if session.is_responsive():
            raise error.TestFail("Session is still responsive after stop")

        logging.info("Try to resume the guest")
        vm.resume()
        logging.info("Verifying the status of VM is 'running'")
        vm.verify_status("running")

        logging.info("Try to re-log into guest")
        session = vm.wait_for_login(timeout=login_timeout)

        if params.get("start_bg_process"):
            if bg:
                bg.join()

        if params.get("check_op"):
            op_timeout = float(params.get("check_op_timeout", 60))
            s, o = session.cmd_status_output(params.get("check_op"),
                                             timeout=op_timeout)
            if s != 0:
                raise error.TestFail("Something wrong after stop continue, "
                                     "check command report: %s" % o)
    finally:
        if params.get("clean_op"):
            op_timeout = float(params.get("clean_op_timeout", 60))
            session.cmd(params.get("clean_op"),  timeout=op_timeout)
        session.close()
        if params.get("start_bg_process"):
            if session_bg:
                session_bg.close()
