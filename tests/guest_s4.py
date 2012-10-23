from autotest.client.shared import error
from autotest.client.virt.utils_test import GuestSuspend


@error.context_aware
def run_guest_s4(test, params, env):

    """
    Suspend a guest os to disk (S4), Support both Linux and Windows guests.

    Recommend usage:
     * Linux: ide+e1000 && SWAP > RAM
     * Windows: virtio_blk+virtio_nic && VIRT_MEM > physical_RAM

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    GuestSuspend.guest_suspend_disk(params, vm)
