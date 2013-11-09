import time
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run_client_guest_shutdown(test, params, env):
    """
    KVM shutdown test:
    For a test with two VMs: client & guest
    1) Log into the VMS(guests) that represent the client &guest
    2) Send a shutdown command to the guest, or issue a system_powerdown
       monitor command (depending on the value of shutdown_method)
    3) Wait until the guest is down

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))

    # shutdown both of the sessions
    for vm in [client_vm, guest_vm]:
        vm_session = vm.wait_for_login(timeout=timeout, username="root",
                                       password="123456")
        try:
            error.base_context("shutting down the VM")
            if params.get("shutdown_method") == "shell":
                # Send a shutdown command to the guest's shell
                vm_session.sendline(vm.get_params().get("shutdown_command"))
                error.context("waiting VM to go down (shutdown shell cmd)")
            elif params.get("shutdown_method") == "system_powerdown":
                # Sleep for a while -- give the guest a chance to finish
                # booting
                time.sleep(float(params.get("sleep_before_powerdown", 10)))
                # Send a system_powerdown monitor command
                vm.monitor.cmd("system_powerdown")
                error.context("waiting VM to go down "
                              "(system_powerdown monitor cmd)")

            if not utils_misc.wait_for(vm.is_dead, 240, 0, 1):
                vm.destroy(gracefully=False, free_mac_addresses=True)
                raise error.TestFail("Guest refuses to go down")

        finally:
            vm_session.close()
