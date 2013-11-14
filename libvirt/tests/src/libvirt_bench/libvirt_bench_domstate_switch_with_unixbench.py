import os
import time
import logging
import shutil
import subprocess

from autotest.client.shared import error
from autotest.client import utils
from virttest import virsh, utils_test, utils_misc, data_dir


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
    2) Run unixbench on guest.
    3) Run domstate_switch test for each VM.
    3) Clean up.
    """
    vms = env.get_all_vms()
    unixbench_control_file = params.get("unixbench_controle_file",
                                        "unixbench5.control")
    timeout = int(params.get("LB_domstate_with_unixbench_loop_time", "600"))
    # Run unixbench on guest.
    guest_unixbench_pids = []
    params["test_control_file"] = unixbench_control_file
    # Fork a new process to run unixbench on each guest.
    for vm in vms:
        params["main_vm"] = vm.name
        control_path = os.path.join(test.virtdir, "control",
                                    unixbench_control_file)

        session = vm.wait_for_login()
        command = utils_test.run_autotest(vm, session, control_path,
                                          None, None,
                                          params, copy_only=True)
        session.cmd("%s &" % command)

    for vm in vms:
        session = vm.wait_for_login()

        def _is_unixbench_running():
            return (not session.cmd_status("ps -ef|grep perl|grep Run"))
        if not utils_misc.wait_for(_is_unixbench_running, timeout=120):
            raise error.TestNAError("Failed to run unixbench in guest.\n"
                                    "Since we need to run a autotest of unixbench "
                                    "in guest, so please make sure there are some "
                                    "necessary packages in guest, such as gcc, tar, bzip2")
    logging.debug("Unixbench is already running in VMs.")

    # Run unixbench on host.
    from autotest.client import common
    autotest_client_dir = os.path.dirname(common.__file__)
    autotest_local_path = os.path.join(autotest_client_dir, "autotest")
    unixbench_control_path = os.path.join(data_dir.get_root_dir(),
                                          "shared", "control",
                                          unixbench_control_file)
    args = [autotest_local_path, unixbench_control_path, '--verbose',
            '-t', unixbench_control_file]
    host_unixbench_process = subprocess.Popen(args)

    try:
        # Create a BackgroundTest for each vm to run test domstate_switch.
        backgroud_tests = []
        for vm in vms:
            bt = utils_test.BackgroundTest(func_in_thread, [vm, timeout])
            bt.start()
            backgroud_tests.append(bt)

        for bt in backgroud_tests:
            bt.join()
    finally:
        # Kill process on host running unixbench.
        utils_misc.kill_process_tree(host_unixbench_process.pid)
        # Remove the result dir produced by subprocess host_unixbench_process.
        unixbench_control_result = os.path.join(autotest_client_dir,
                                                "results",
                                                unixbench_control_file)
        if os.path.isdir(unixbench_control_result):
            shutil.rmtree(unixbench_control_result)
