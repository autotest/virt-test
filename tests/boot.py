import time
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run_boot(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest
    3) Send a reboot command or a system_reset monitor command (optional)
    4) Wait until the guest is up again
    5) Log into the guest to verify it's up again

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    error.context("Try to log into guest.")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    if params.get("rh_perf_envsetup_script"):
        utils_test.service_setup(vm, session, test.virtdir)

    if params.get("reboot_method"):
        error.context("Reboot guest.")
        if params["reboot_method"] == "system_reset":
            time.sleep(int(params.get("sleep_before_reset", 10)))
            # Reboot the VM
        for i in range(int(params.get("reboot_count", 1))):
            session = vm.reboot(session, params["reboot_method"], 0, timeout)

    session.close()
