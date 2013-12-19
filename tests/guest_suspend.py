from autotest.client.shared import error
from virttest import utils_test


class GuestSuspendBaseTest(utils_test.qemu.GuestSuspend):

    def do_guest_suspend(self, **args):
        suspend_type = args.get("suspend_type", self.SUSPEND_TYPE_MEM)

        self.verify_guest_support_suspend(**args)
        self.setup_bg_program(**args)
        self.check_bg_program(**args)

        # Do something before start suspend
        self.action_before_suspend(**args)

        self.start_suspend(**args)

        # Do something during suspend stage
        self.action_during_suspend(**args)

        if suspend_type == self.SUSPEND_TYPE_DISK:
            self.verify_guest_down(**args)
            self.resume_guest_disk(**args)

        if suspend_type == self.SUSPEND_TYPE_MEM:
            self.resume_guest_mem(**args)

        self.check_bg_program(**args)
        self.verify_guest_up(**args)

        # Do something after suspend
        self.action_after_suspend(**args)

        self.kill_bg_program(**args)

        self._cleanup_open_session()

    def guest_suspend_mem(self, params):
        """
        Suspend a guest os to memory. Support both Linux and Windows guest.

        Test steps:
        1) Boot a guest.
        2) Clear guest's log and check(Linux guest) or enable(Windows guest)
           S3 mode.
        3) Run a background program as a flag.
        4) Set guest into S3 state.
        5) Sleep a while before resuming guest.
        6) Verify background program is still running.
        7) Verify guest system log.

        NOTE:
          Because WinXP/2003 doesn't record ACPI event into log, this test
          always passes if the guest's driver supports S3

        :param params: Dictionary with test parameters.
        :param env: Dictionary with the test environment.

        """
        self.do_guest_suspend(
            suspend_type=self.SUSPEND_TYPE_MEM,
            suspend_support_chk_cmd=params.get("s3_support_chk_cmd"),
            suspend_bg_program_setup_cmd=params.get("s3_bg_program_setup_cmd"),
            suspend_bg_program_chk_cmd=params.get("s3_bg_program_chk_cmd"),
            suspend_bg_program_kill_cmd=params.get("s3_bg_program_kill_cmd"),
            suspend_start_cmd=params.get("s3_start_cmd"),
            suspend_log_chk_cmd=params.get("s3_log_chk_cmd"))

    def guest_suspend_disk(self, params):
        """
        Suspend guest to disk, supports both Linux and Windows.

        Test steps:
        1) Boot a guest.
        2) Clear guest's log and check(Linux guest) or enable(Windows guest)
           S3 mode.
        3) Run a background program as a flag.
        4) Set guest into S4 state.
        5) Sleep a while before resuming guest.
        6) Verify background program is still running.
        7) Verify guest system log.

        :param params: Dictionary with test parameters.
        :param env: Dictionary with the test environment.
        """
        self.do_guest_suspend(
            suspend_type=self.SUSPEND_TYPE_DISK,
            suspend_support_chk_cmd=params.get("s4_support_chk_cmd"),
            suspend_bg_program_setup_cmd=params.get("s4_bg_program_setup_cmd"),
            suspend_bg_program_chk_cmd=params.get("s4_bg_program_chk_cmd"),
            suspend_bg_program_kill_cmd=params.get("s4_bg_program_kill_cmd"),
            suspend_start_cmd=params.get("s4_start_cmd"),
            suspend_log_chk_cmd=params.get("s4_log_chk_cmd"))


class GuestSuspendNegativeTest(GuestSuspendBaseTest):

    """
    This class is used to test the situation which sets 'disable_s3/s4' to '1'
    in qemu cli. Guest should disable suspend function in this case.
    """

    def do_guest_suspend(self, **args):
        s, o = self._check_guest_suspend_log(**args)
        if not s:
            raise error.TestFail("Guest reports support Suspend even if it's"
                                 " disabled in qemu. Output:\n '%s'" % o)


@error.context_aware
def run(test, params, env):
    """
    Suspend guest to memory/disk, supports both Linux and Windows.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vms = params.get("vms").split(" ")
    vm = env.get_vm(vms[0])
    vm.verify_alive()
    if params.get("negative_test") == "yes":
        gs = GuestSuspendNegativeTest(params, vm)
    else:
        gs = GuestSuspendBaseTest(params, vm)

    suspend_type = params.get("guest_suspend_type")
    if suspend_type == gs.SUSPEND_TYPE_MEM:
        gs.guest_suspend_mem(params)
    elif suspend_type == gs.SUSPEND_TYPE_DISK:
        gs.guest_suspend_disk(params)
    else:
        raise error.TestError("Unknown guest suspend type, Check your"
                              " 'guest_suspend_type' config.")
