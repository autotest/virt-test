import logging, time
from autotest_lib.client.common_lib import error
from autotest_lib.client.virt import virt_utils

@error.context_aware
def run_guest_s4(test, params, env):

    """
    Suspend a guest os to disk (S4)
    Support both Linux and Windows guest.

    Recommend usage:
        Linux: ide+e1000 && SWAP > RAM
        Windows: virtio_blk+virtio_nic && VIRT_MEM > physical_RAM

    1) clear guest system_log and check weather (Linux guest) supports S4 OR
        enable S4 support(Windows guest). if not support,then error this test.
    2) run a background program as a flag and push guest into s4 state.
    3) Check whether guest really down, if not,then fail this test.
    4) Resume guest,check weather background program still running,
        if not ,error this test.
    5) check guest system_log,if not acpi s4 message found,fail this test.

    Because WinXP/2003 dont record ACPI event into log,
    so will always pass this test if the guest's physical memory smaller
        than virtual memory

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.

    """

    error.base_context("before S4")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("clearing guest system_log AND checking "
                "whether guest OS supports S4", logging.info)
    s, o = session.cmd_status_output(params.get("check_s4_support_cmd"))
    if s !=0:
        logging.debug("Recommended to check the size of guest's mem and swap.")
        raise error.TestError("The guest doesn't support S4, %s" % o)

    session2 = vm.wait_for_login(timeout=timeout)

    try:
        logging.info("Waiting until all guest OS services are fully started...")
        time.sleep(float(params.get("services_up_timeout", 10)))

        logging.info("run a program in background as a flag")
        session.sendline(params.get("bg_cmd"))
        time.sleep(5)

        # Make sure the background program is running as expected
        error.context("making sure background program is running")
        session2.cmd(params.get("check_bg_cmd") )
        logging.info("Launched background command in guest " )
        error.context()
        error.base_context()

        # Suspend to disk
        logging.info("Starting suspend to disk now...")
        session2.sendline(params.get("set_s4_cmd"))

        # Make sure the VM goes down
        error.base_context("after S4")
        suspend_timeout = 240 + int(params.get("smp")) * 60
        if not virt_utils.wait_for(vm.is_dead, suspend_timeout, 2, 2):
            raise error.TestFail("VM refuses to go down. Suspend failed.")
        logging.info("VM suspended successfully. Sleeping for a while before "
                     "resuming it.")
        time.sleep(10)

        # Start vm, and check whether the program is still running
        logging.info("Resuming suspended VM...")
        vm.create()
        time.sleep(5)
        if not vm.is_alive():
            raise error.TestError("Failed to start VM after suspend to disk")

        session3 = vm.wait_for_login(timeout=timeout)
        if not session3:
            raise error.TestFail("Could not log into VM after resuming from"
                                "suspend to disk")


        # Check whether the test command is still alive
        bg_status = session3.cmd_status(params.get("check_bg_cmd"))
        s4_status = session3.cmd_status(params.get("check_s4_cmd"))
        #for debug only
        logging.debug ("bg_status %s" % bg_status)
        logging.debug ("s4_status %s" % s4_status)

        error.context("making sure background program is still running",
                      logging.info)
        if bg_status:
            raise error.TestError("backgrond program disappeared after resume.")
        elif s4_status:
            raise error.TestError("there's not Suspend log found .")
        else:
            logging.info("The system has resumed")

        logging.info("remove flag from guest")
        session3.cmd_output(params.get("kill_bg_cmd"))
        session3.close()
    finally:
        session2.close()
        session.close()
