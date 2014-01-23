import os
import time
import logging

from autotest.client.shared import error
from virttest import virsh, utils_test, utils_misc


def func_in_thread(vm, timeout):
    """
    Function run in thread to switch domstate.
    """
    def run_virsh_function(func, params):
        """
        Function to run virsh function and check the result.
        """
        result = func(params)
        if result.exit_status:
            raise error.TestFail(result)
    # Get current time.
    current_time = time.time()
    end_time = current_time + timeout
    while current_time < end_time:
        run_virsh_function(func=virsh.dom_list, params="--all")
        run_virsh_function(func=virsh.dominfo, params=vm.name)
        run_virsh_function(func=virsh.nodeinfo, params="")
        run_virsh_function(func=virsh.domuuid, params=vm.name)
        run_virsh_function(func=virsh.domid, params=vm.name)
        run_virsh_function(func=virsh.dumpxml, params=vm.name)
        run_virsh_function(func=virsh.domstate, params=vm.name)
        run_virsh_function(func=virsh.suspend, params=vm.name)
        run_virsh_function(func=virsh.resume, params=vm.name)
        # update the current_time.
        current_time = time.time()


def run(test, params, env):
    """
    Test steps:

    1) Get the params from params.
    2) Run iozone on guest.
    3) Run domstate_switch test for each VM.
    3) Clean up.
    """
    vms = env.get_all_vms()
    iozone_control_file = params.get("iozone_control_file",
                                     "iozone.control")
    timeout = int(params.get("LB_domstate_with_iozone_loop_time", "600"))
    # Run iozone on guest.
    params["test_control_file"] = iozone_control_file
    # Fork a new process to run iozone on each guest.
    for vm in vms:
        params["main_vm"] = vm.name
        control_path = os.path.join(test.virtdir, "control",
                                    iozone_control_file)

        session = vm.wait_for_login()
        command = utils_test.run_autotest(vm, session, control_path,
                                          None, None,
                                          params, copy_only=True)
        session.cmd("%s &" % command)

    for vm in vms:
        session = vm.wait_for_login()

        def _is_iozone_running():
            return (not session.cmd_status("ps -ef|grep iozone|grep -v grep"))
        if not utils_misc.wait_for(_is_iozone_running, timeout=120):
            raise error.TestNAError("Failed to run iozone in guest.\n"
                                    "Since we need to run a autotest of iozone "
                                    "in guest, so please make sure there are "
                                    "some necessary packages in guest,"
                                    "such as gcc, tar, bzip2")
    logging.debug("Iozone is already running in VMs.")

    try:
        # Create a BackgroundTest for each vm to run test domstate_switch.
        backgroud_tests = []
        for vm in vms:
            bt = utils_test.BackgroundTest(func_in_thread, [vm, timeout])
            bt.start()
            backgroud_tests.append(bt)

        for bt in backgroud_tests:
            bt.join()

        # Reboot vms after func_in_thread to check vm is running normally.
        for vm in vms:
            vm.reboot()
    finally:
        # Clean up.
        logging.debug("No cleaning operation for this test.")
