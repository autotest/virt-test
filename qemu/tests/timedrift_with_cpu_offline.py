import logging
import time
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run_timedrift_with_cpu_offline(test, params, env):
    """
    Time drift test with vm's cpu offline/online:

    1) Log into a guest (the vcpu num >= 2).
    2) Take a time reading from the guest and host.
    3) Set cpu offline in vm.
    4) Take the time from the guest and host as given frequency.
    5) Set cpu online, which was set offline before
    5) Take the time from the guest and host as given frequency.
    6) If the drift (in seconds) is higher than a user specified value, fail.

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    boot_option_added = params.get("boot_option_added")
    boot_option_removed = params.get("boot_option_removed")
    if boot_option_added or boot_option_removed:
        utils_test.update_boot_option(vm,
                                      args_removed=boot_option_removed,
                                      args_added=boot_option_added)

    session = vm.wait_for_login(timeout=login_timeout)

    # Command to run to get the current time
    time_command = params.get("time_command")
    # Filter which should match a string to be passed to time.strptime()
    time_filter_re = params.get("time_filter_re")
    # Time format for time.strptime()
    time_format = params.get("time_format")
    # Use this value to measure the drift.
    drift_threshold = params.get("drift_threshold")
    # The time interval to check vm's time
    interval_gettime = int(params.get("interval_gettime", 600))
    test_duration = float(params.get("test_duration", "60"))

    try:
        # Get time before set cpu offine
        # (ht stands for host time, gt stands for guest time)
        error.context("get time before set cpu offline")
        (ht0, gt0) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)
        # Check cpu number
        error.context("check guest cpu number")
        smp = int(params.get("smp"))
        if smp < 2:
            raise error.TestError("The guest only has %d vcpu,"
                                  "unsupport cpu offline" % smp)

        # Set cpu offline
        error.context("set cpu offline ")
        offline_cpu_cmd = params.get("offline_cpu_cmd")
        s, o = session.cmd_status_output(offline_cpu_cmd)
        if s != 0:
            logging.error(o)
            raise error.TestError("Failed set guest cpu offline")

        # Get time after set cpu offline
        error.context("get time after set cpu offline")
        (ht1, gt1) = utils_test.get_time(session, time_command,
                                         time_filter_re, time_format)
        # Report results
        host_delta = ht1 - ht0
        guest_delta = gt1 - gt0
        drift = 100.0 * (host_delta - guest_delta) / host_delta
        logging.info("Host duration: %.2f", host_delta)
        logging.info("Guest duration: %.2f", guest_delta)
        logging.info("Drift: %.2f%%", drift)
        if abs(drift) > drift_threshold:
            raise error.TestFail("Time drift too large: %.2f%%" % drift)

        # Set cpu online again
        error.context("set cpu online")
        online_cpu_cmd = params.get("online_cpu_cmd")
        s, o = session.cmd_status_output(online_cpu_cmd)
        if s != 0:
            logging.error(o)
            raise error.TestError("Failed set guest cpu online")

        error.context("get time after set cpu online")
        start_time = time.time()
        while (time.time() - start_time) < test_duration:
            # Get time delta after set cpu online
            (ht1, gt1) = utils_test.get_time(session, time_command,
                                             time_filter_re, time_format)

            # Report results
            host_delta = ht1 - ht0
            guest_delta = gt1 - gt0
            drift = 100.0 * (host_delta - guest_delta) / host_delta
            logging.info("Host duration: %.2f", host_delta)
            logging.info("Guest duration: %.2f", guest_delta)
            logging.info("Drift: %.2f%%", drift)
            time.sleep(interval_gettime)
        if abs(drift) > drift_threshold:
            raise error.TestFail("Time drift too large: %.2f%%" % drift)
    finally:
        session.close()
        # remove flags add for this test.
        if boot_option_added or boot_option_removed:
            utils_test.update_boot_option(vm,
                                          args_removed=boot_option_added,
                                          args_added=boot_option_removed)
