import logging, time, re
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run_timedrift_with_savevm(test, params, env):
    """
    Time drift test with save the guest:

    1) Log into a guest.
    2) Take a time reading from the guest and host.
    3) Save vm.
    4) Load vm.
    5) Take the time from the guest and host as given frequency.
    6) If the drift (in seconds) is higher than a user specified value, fail.

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    cmd_timeout = int(params.get("cmd_timeout", 120))
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
    # Use this value to measure the drift when ignore vm stop time.
    drift_threshold = params.get("drift_threshold")
    sleep_time = int(params.get("sleep_time", 600))
    # The frequence to check vm's time
    times_gettime = int(params.get("times_gettime", 3))
    # The time interval to check vm's time
    interval_gettime = int(params.get("interval_gettime", 600))
    # Use this value to measure the drift when subtract vm stop time.
    max_drift_threshold = float(params.get("max_drift_threshold"))

    try:
        # Get time before savevm
        # (ht stands for host time, gt stands for guest time)
        (ht0, gt0) = utils_test.get_time(session, time_command,
                                              time_filter_re, time_format)
        # Save vm
        error.context("Start save snapshot")
        t_start = time.time()
        vm.monitor.send_args_cmd("savevm", timeout=360)
        o = vm.monitor.info("snapshots")
        logging.info("The snapshots information after savevm: %s" % o)

        # Load vm
        logging.info("Start load snapshot")
        vm.monitor.send_args_cmd("loadvm 1", timeout=360)
        t_end = time.time()
        t_cost = t_end - t_start
        logging.info("Savevm & Loadvm t_cost = %f s" % t_cost)

        logging.info("Let vm sleep %d s" % sleep_time)
        time.sleep(sleep_time)

        for times in range(times_gettime):
            time.sleep(interval_gettime)
            # Get time after loadvm
            (ht1, gt1) = utils_test.get_time(session, time_command,
                                                  time_filter_re, time_format)
            host_delta = ht1 - ht0
            guest_delta = gt1 - gt0
            difference = abs(host_delta - guest_delta)
            r_time = sleep_time + interval_gettime * (times + 1)
            logging.info("The guest is running %f s after loadvm", r_time)
            logging.info("Host duration: %.2f", host_delta)
            logging.info("Guest duration: %.2f", guest_delta)
            logging.info("Difference is: %.2f seconds", difference)

        # Fail if necessary
        if drift_threshold:
            if difference > float(drift_threshold):
                raise error.TestFail("Time drift too large: %.2f seconds"
                                      % difference)
        else:
            drift = abs(difference - t_cost)
            logging.info("abs(difference - t_cost) = %f" % drift)
            if drift >= max_drift_threshold:
                raise error.TestFail("Time drift too large: %.2f seconds"
                                      % drift)
    finally:
        o = vm.monitor.info("snapshots")
        num = len(re.split("\n", o)[3:-1])
        for snapshot in xrange(num):
            logging.info("Delete snapshot %d" % (snapshot + 1))
            vm.monitor.send_args_cmd("delvm %s" % (snapshot + 1))
        session.close()
        # remove flags add for this test.
        if boot_option_added or boot_option_removed:
            utils_test.update_boot_option(vm,
                                               args_removed=boot_option_added,
                                               args_added=boot_option_removed)
