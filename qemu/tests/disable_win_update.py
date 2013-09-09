import logging
from autotest.client.shared import error


def run_disable_win_update(test, params, env):
    """
    This simply stop updates services in Windows guests.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(
        timeout=float(params.get("login_timeout", 240)))

    stop_update_service_cmd = params.get("stop_update_service_cmd")
    s, o = session.get_command_status_output(stop_update_service_cmd)
    if s != 0:
        logging.error("Failed to stop Windows update service: %s" % o)
    else:
        logging.info("Stopped Windows updates services")

    disable_update_service_cmd = params.get("disable_update_service_cmd")
    s, o = session.get_command_status_output(disable_update_service_cmd)
    if s != 0:
        logging.error("Turn off updates service failed: %s" % o)
    else:
        logging.info("Turned off windows updates service")
