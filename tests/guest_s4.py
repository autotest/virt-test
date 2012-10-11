from autotest.client.shared import error
from virttest.utils_test import GuestSuspend


@error.context_aware
def run_guest_s4(test, params, env):
    """
    Suspend guest to disk, supports both Linux and Windows.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    GuestSuspend.guest_suspend_disk(params, vm)
