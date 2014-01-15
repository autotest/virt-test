import time
import logging

from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test steps:

    1) Get the params from params.
    2) loop:
            start
            shutdown
            start
            suspend
            resume
            destroy
    3) clean up.
    """
    def for_each_vm(vms, virsh_func, state_list=None):
        """
        Execute the virsh_func with each vm in vms.

        :Param vms: List of vm.
        :Param virsh_func: Function in virsh module.
        :Param state_list: States to verify the result of virsh_func.
                           None means do not check the state.
        """
        vm_names = []
        for vm in vms:
            vm_names.append(vm.name)
        for vm_name in vm_names:
            cmd_result = virsh_func(vm_name)
            if cmd_result.exit_status:
                raise error.TestFail(cmd_result)
            if state_list is None:
                continue
            actual_state = virsh.domstate(vm_name).stdout.strip()
            if not (actual_state in state_list):
                raise error.TestFail("Command %s succeed, but the state is %s,"
                                     "but not %s." %
                                     (virsh_func.__name__, actual_state,
                                      str(state_list)))
        logging.debug("Operation %s on %s succeed.",
                      virsh_func.__name__, vm_names)

    # Get VMs.
    vms = env.get_all_vms()
    # Get operations from params.
    start_in_loop = ("yes" == params.get("LB_domstate_switch_start", "no"))
    start_post_state = params.get("LB_domstate_switch_start_post_state",
                                  "running").split(',')
    shutdown_in_loop = ("yes" == params.get("LB_domstate_switch_shutdown",
                                            "no"))
    shutdown_post_state = params.get("LB_domstate_switch_shutdown_post_state",
                                     "shutdown").split(',')
    destroy_in_loop = ("yes" == params.get("LB_domstate_switch_destroy", "no"))
    destroy_post_state = params.get("LB_domstate_switch_destroy_post_state",
                                    "shut off").split(',')
    suspend_in_loop = ("yes" == params.get("LB_domstate_switch_suspend", "no"))
    suspend_post_state = params.get("LB_domstate_switch_suspend_post_state",
                                    "paused").split(',')
    resume_in_loop = ("yes" == params.get("LB_domstate_switch_resume", "no"))
    resume_post_state = params.get("LB_domstate_switch_resume_post_state",
                                   "running").split(',')
    # Get the loop_time.
    loop_time = int(params.get("LB_domstate_switch_loop_time", "600"))
    current_time = int(time.time())
    end_time = current_time + loop_time
    # Init a counter for the loop.
    loop_counter = 0
    try:
        try:
            # Verify the vms is all loaded completely.
            for vm in vms:
                vm.wait_for_login()
            # Start the loop from current_time to end_time.
            while current_time < end_time:
                if loop_counter > (len(vms) * 1000 * loop_time):
                    raise error.TestFail("Loop ")
                if shutdown_in_loop:
                    for_each_vm(vms, virsh.shutdown, shutdown_post_state)
                    for vm in vms:
                        if not vm.wait_for_shutdown(count=240):
                            raise error.TestFail("Command shutdown succeed, but "
                                                 "failed to wait for shutdown.")
                if destroy_in_loop:
                    for_each_vm(vms, virsh.destroy, destroy_post_state)
                if start_in_loop:
                    for_each_vm(vms, virsh.start, start_post_state)
                    for vm in vms:
                        if not vm.wait_for_login():
                            raise error.TestFail("Command start succeed, but "
                                                 "failed to wait for login.")
                if suspend_in_loop:
                    for_each_vm(vms, virsh.suspend, suspend_post_state)
                if resume_in_loop:
                    for_each_vm(vms, virsh.resume, resume_post_state)
                logging.debug("Finish %s loop.", loop_counter)
                # Update the current_time and loop_counter.
                current_time = int(time.time())
                loop_counter += 1
        except error.TestFail, detail:
            raise error.TestFail("Succeed for %s loop, and got an error.\n"
                                 "Detail: %s." % (loop_counter, detail))
    finally:
        # Resume vm if vm is paused.
        for vm in vms:
            if vm.is_paused():
                vm.resume()
            vm.destroy()
