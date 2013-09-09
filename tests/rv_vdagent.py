"""
rv_vdagent.py - basic tests to verify, vdagent status, starting, stopping,
and restarting correctly.

Requires: connected binaries remote-viewer, Xorg, gnome session

"""
from autotest.client.shared import error
from virttest import utils_spice


def run_rv_vdagent(test, params, env):
    """
    Tests spice vdagent (starting, stopping, restarting, and status)

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    vdagent_test = params.get("vdagent_test")

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_root_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    vdagent_status = utils_spice.get_vdagent_status(
        guest_root_session, test_timeout)

    # start test
    if vdagent_test == "start":
        if "running" in vdagent_status:
            # stop the service prior to starting
            utils_spice.stop_vdagent(guest_root_session, test_timeout)
            utils_spice.start_vdagent(guest_root_session, test_timeout)
        else:
            utils_spice.start_vdagent(guest_root_session, test_timeout)
        # Verify the status of vdagent is running
        status = utils_spice.get_vdagent_status(
            guest_root_session, test_timeout)
        if "running" in status:
            pass
        else:
            raise error.TestFail(
                "Vdagent status is not running after a start attempt.")
    # stop test
    elif vdagent_test == "stop":
        if "stopped" in vdagent_status:
            # start the service prior to stopping the service
            utils_spice.start_vdagent(guest_root_session, test_timeout)
            utils_spice.stop_vdagent(guest_root_session, test_timeout)
        else:
            utils_spice.stop_vdagent(guest_root_session, test_timeout)
        # Verify the status of vdagent is stopped
        status = utils_spice.get_vdagent_status(
            guest_root_session, test_timeout)
        if "stopped" in status:
            pass
        else:
            print "Status: " + status
            raise error.TestFail(
                "Vdagent status is not stopped after a stop attempt.")
    # restart test when vdagent service is running
    elif vdagent_test == "restart_start":
        if "stopped" in vdagent_status:
            # start the service prior to stopping the service
            utils_spice.start_vdagent(guest_root_session, test_timeout)
            utils_spice.restart_vdagent(guest_root_session, test_timeout)
        else:
            utils_spice.restart_vdagent(guest_root_session, test_timeout)
        # Verify the status of vdagent is started
        status = utils_spice.get_vdagent_status(
            guest_root_session, test_timeout)
        if "running" in status:
            pass
        else:
            raise error.TestFail(
                "Vdagent status is not started after a restart attempt.")
    # restart test when vdagent service is stopped
    elif vdagent_test == "restart_stop":
        if "running" in vdagent_status:
            # start the service prior to stopping the service
            utils_spice.stop_vdagent(guest_root_session, test_timeout)
            utils_spice.restart_vdagent(guest_root_session, test_timeout)
        else:
            utils_spice.restart_vdagent(guest_root_session, test_timeout)
        # Verify the status of vdagent is started
        status = utils_spice.get_vdagent_status(
            guest_root_session, test_timeout)
        if "running" in status:
            pass
        else:
            raise error.TestFail(
                "Vdagent status is not started after a restart attempt.")
    else:
        raise error.TestFail("No test to run, check value of vdagent_test")

    client_session.close()
    guest_root_session.close()
