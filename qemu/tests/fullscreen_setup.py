"""
fullscreen_setup.py - Used as a setup test for the full-screen test.

To make sure the full screen test is tested correctly, this setup will
change the resolution of the guest, by default creating two VMs from
the same setup will result in them having the same resolution.

"""
import logging
from virttest import utils_spice, aexpect


def run_fullscreen_setup(test, params, env):
    """
    Simple test for Remote Desktop connection
    Tests expectes that Remote Desktop client (spice/vnc) will be executed
    from within a second guest so we won't be limited to Linux only clients

    The plan is to support remote-viewer at first place

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    utils_spice.wait_timeout(10)

    logging.debug("Exporting guest display")
    guest_session.cmd("export DISPLAY=:0.0")

    # Get the min, current, and max resolution on the guest
    output = guest_session.cmd("xrandr | grep Screen")
    outputlist = output.split()

    minimum = "640x480"

    current_index = outputlist.index("current")
    current = outputlist[current_index + 1]
    current += outputlist[current_index + 2]
    # Remove trailing comma
    current += outputlist[current_index + 3].replace(",", "")

    maximum = "2560x1600"

    logging.info("Minimum: " + minimum + " Current: " + current +
                 " Maximum: " + maximum)
    if(current != minimum):
        resolution = minimum
    else:
        resolution = maximum

    # Changing the guest resolution
    guest_session.cmd("xrandr -s " + resolution)
    logging.info("The resolution on the guest has been changed from " +
                 current + " to: " + resolution)

    # Start vdagent daemon
    utils_spice.start_vdagent(guest_session, test_timeout)

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    client_session.close()
    guest_session.close()
