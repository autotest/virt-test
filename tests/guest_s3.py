from autotest.client.shared import error
from autotest.client.virt.utils_test import GuestSuspend


@error.context_aware
def run_guest_s3(test, params, env):
    """
    Suspend guest to memory, supports both Linux and Windows.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    GuestSuspend.guest_suspend_mem(params, vm)
