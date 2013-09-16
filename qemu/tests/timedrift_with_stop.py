import logging
import time
import os
import signal
from autotest.client.shared import error
from virttest import utils_test


def run_timedrift_with_stop(test, params, env):
    """
    Time drift test with stop/continue the guest:

    1) Log into a guest.
    2) Take a time reading from the guest and host.
    3) Stop the running of the guest
    4) Sleep for a while
    5) Continue the guest running
    6) Take a second time reading.
    7) If the drift (in seconds) is higher than a user specified value, fail.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    sleep_time = int(params.get("sleep_time", 30))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    boot_option_added = params.get("boot_option_added")
    boot_option_removed = params.get("boot_option_removed")
    if boot_option_added or boot_option_removed:
        utils_test.update_boot_option(vm,
                                      args_removed=boot_option_removed,
                                      args_added=boot_option_added)

    session = vm.wait_for_login(timeout=login_timeout)

    # Collect test parameters:
    # Command to run to get the current time
    time_command = params["time_command"]
    # Filter which should match a string to be passed to time.strptime()
    time_filter_re = params["time_filter_re"]
    # Time format for time.strptime()
    time_format = params["time_format"]
    drift_threshold = float(params.get("drift_threshold", "10"))
    drift_threshold_single = float(params.get("drift_threshold_single", "3"))
    stop_iterations = int(params.get("stop_iterations", 1))
    stop_time = int(params.get("stop_time", 60))
    stop_with_signal = params.get("stop_with_signal") == "yes"

    # Get guest's pid.
    pid = vm.get_pid()

    try:
        # Get initial time
        # (ht stands for host time, gt stands for guest time)
        (ht0, gt0) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)

        # Stop the guest
        for i in range(stop_iterations):
            # Get time before current iteration
            (ht0_, gt0_) = utils_test.get_time(session, time_command,
                                               time_filter_re, time_format)
            # Run current iteration
            logging.info("Stop %s second: iteration %d of %d...",
                         stop_time, (i + 1), stop_iterations)
            if stop_with_signal:
                logging.debug("Stop guest")
                os.kill(pid, signal.SIGSTOP)
                time.sleep(stop_time)
                logging.debug("Continue guest")
                os.kill(pid, signal.SIGCONT)
            else:
                vm.pause()
                time.sleep(stop_time)
                vm.resume()

            # Sleep for a while to wait the interrupt to be reinjected
            logging.info("Waiting for the interrupt to be reinjected ...")
            time.sleep(sleep_time)

            # Get time after current iteration
            (ht1_, gt1_) = utils_test.get_time(session, time_command,
                                               time_filter_re, time_format)
            # Report iteration results
            host_delta = ht1_ - ht0_
            guest_delta = gt1_ - gt0_
            drift = abs(host_delta - guest_delta)
            logging.info("Host duration (iteration %d): %.2f",
                         (i + 1), host_delta)
            logging.info("Guest duration (iteration %d): %.2f",
                         (i + 1), guest_delta)
            logging.info("Drift at iteration %d: %.2f seconds",
                         (i + 1), drift)
            # Fail if necessary
            if drift > drift_threshold_single:
                raise error.TestFail("Time drift too large at iteration %d: "
                                     "%.2f seconds" % (i + 1, drift))

        # Get final time
        (ht1, gt1) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)

    finally:
        if session:
            session.close()
        # remove flags add for this test.
        if boot_option_added or boot_option_removed:
            utils_test.update_boot_option(vm,
                                          args_removed=boot_option_added,
                                          args_added=boot_option_removed)

    # Report results
    host_delta = ht1 - ht0
    guest_delta = gt1 - gt0
    drift = abs(host_delta - guest_delta)
    logging.info("Host duration (%d stops): %.2f",
                 stop_iterations, host_delta)
    logging.info("Guest duration (%d stops): %.2f",
                 stop_iterations, guest_delta)
    logging.info("Drift after %d stops: %.2f seconds",
                 stop_iterations, drift)

    # Fail if necessary
    if drift > drift_threshold:
        raise error.TestFail("Time drift too large after %d stops: "
                             "%.2f seconds" % (stop_iterations, drift))
