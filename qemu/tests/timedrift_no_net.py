import logging
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_test
from virttest import utils_misc
from generic.tests.guest_suspend import GuestSuspendBaseTest


class GuestSuspendSerialConsole(GuestSuspendBaseTest):

    def __init__(self, params, vm, session):
        super(GuestSuspendSerialConsole, self).__init__(params, vm)

    def _get_session(self):
        self.vm.verify_alive()
        session = self.vm.wait_for_serial_login(timeout=self.login_timeout)
        return session

    @error.context_aware
    def action_during_suspend(self, **args):
        error.context("Sleep a while before resuming guest", logging.info)

        time.sleep(float(self.params.get("wait_timeout", "1800")))
        if self.os_type == "windows":
            # Due to WinXP/2003 won't suspend immediately after issue S3 cmd,
            # delay 10~60 secs here, maybe there's a bug in windows os.
            logging.info("WinXP/2003 need more time to suspend, sleep 50s.")
            time.sleep(50)


def subw_guest_suspend(params, vm, session):
    gs = GuestSuspendSerialConsole(params, vm, session)

    suspend_type = params.get("guest_suspend_type")
    if suspend_type == gs.SUSPEND_TYPE_MEM:
        error.context("Suspend vm to mem", logging.info)
        gs.guest_suspend_mem(params)
    elif suspend_type == gs.SUSPEND_TYPE_DISK:
        error.context("Suspend vm to disk", logging.info)
        gs.guest_suspend_disk(params)
    else:
        raise error.TestError("Unknown guest suspend type, Check your"
                              " 'guest_suspend_type' config.")


def subw_guest_pause_resume(params, vm, session):
    vm.monitor.cmd("stop")
    if not vm.monitor.verify_status("paused"):
        raise error.TestError("VM is not paused Current status: %s",
                              vm.monitor.get_status())
    time.sleep(float(params.get("wait_timeout", "1800")))
    vm.monitor.cmd("cont")
    if not vm.monitor.verify_status("running"):
        raise error.TestError("VM is not running. Current status: %s",
                              vm.monitor.get_status())


def time_diff(host_guest_time_before,
              host_guest_time_after):
    """
    Function compares diff of host and guest time before and after.
    It allows compare time in different timezones.

    :params host_guest_time_before: Time from host and guest.
    :type host_guest_time_before: (float, float)
    :params host_guest_time_after: Time from host and guest.
    :type host_guest_time_after: (float, float)
    :returns: Time diff between server and guest time.
    :rtype: float
    """
    before_diff = host_guest_time_before[0] - host_guest_time_before[1]
    after_diff = host_guest_time_after[0] - host_guest_time_after[1]

    return before_diff - after_diff


@error.context_aware
def run(test, params, env):
    """
    Test suspend commands in qemu guest agent.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    clock_server = params.get("clock_server", "clock.redhat.com")
    ntputil_install = params.get("ntputil_install", "yum install -y ntpdate")
    login_timeout = int(params.get("login_timeout", "240"))
    guest_clock_source = params.get("guest_clock_source", "kvm-clock")
    date_time_command = params.get("date_time_command",
                                   "date -u +'TIME: %a %m/%d/%Y %H:%M:%S.%N'")
    date_time_filter_re = params.get("date_time_filter_re",
                                     r"(?:TIME: \w\w\w )(.{19})(.+)")
    date_time_format = params.get("date_time_format",
                                  "%m/%d/%Y %H:%M:%S")
    hwclock_time_command = params.get("hwclock_time_command")
    hwclock_time_filter_re = params.get("hwclock_time_filter_re",
                                        r"(.+)")
    hwclock_time_format = params.get("hwclock_time_format",
                                     "%a %b %d %H:%M:%S %Y")
    tolerance = float(params.get("time_diff_tolerance", "0.5"))

    sub_work = params["sub_work"]
    test_type = params["timedrift_sub_work"]

    vm_name = params.get("vms")
    vm = env.get_vm(vm_name)
    error.context("Check if ntp utils are host in system.", logging.info)
    try:
        utils_misc.find_command("ntpdate")
    except ValueError:
        error.context("Install ntp utils `%s`." % (ntputil_install),
                      logging.info)
        utils.run(ntputil_install)
    error.context("Sync host machine with clock server %s" % (clock_server),
                  logging.info)
    utils.run("ntpdate %s" % (clock_server))
    error.context("Check clock source on guest VM", logging.info)
    session = vm.wait_for_serial_login(timeout=login_timeout)
    out = session.cmd_output("cat /sys/devices/system/clocksource/"
                             "clocksource0/current_clocksource")
    if not guest_clock_source in out:
        raise error.TestFail("Clock source %s missing in guest clock "
                             "sources %s." % (guest_clock_source, out))

    error.context("Get clock from host and guest VM using `date`",
                  logging.info)
    before_date = utils_test.get_time(session,
                                      date_time_command,
                                      date_time_filter_re,
                                      date_time_format)
    logging.debug("date: host time=%ss guest time=%ss",
                  *before_date)

    error.context("Get clock from host and guest VM using `hwclock`",
                  logging.info)
    before_hwclock = utils_test.get_time(session,
                                         hwclock_time_command,
                                         hwclock_time_filter_re,
                                         hwclock_time_format)
    logging.debug("hwclock: host time=%ss guest time=%ss",
                  *before_hwclock)

    session.close()

    if sub_work in globals():  # Try to find sub work function.
        globals()[sub_work](params, vm, session)
    else:
        raise error.TestNAError("Unable to found subwork %s in %s test file." %
                                (sub_work, __file__))

    session = vm.wait_for_serial_login(timeout=login_timeout)
    error.context("Get clock from host and guest VM using `date`",
                  logging.info)
    after_date = utils_test.get_time(session,
                                     date_time_command,
                                     date_time_filter_re,
                                     date_time_format)
    logging.debug("date: host time=%ss guest time=%ss",
                  *after_date)

    error.context("Get clock from host and guest VM using `hwclock`",
                  logging.info)
    after_hwclock = utils_test.get_time(session,
                                        hwclock_time_command,
                                        hwclock_time_filter_re,
                                        hwclock_time_format)
    logging.debug("hwclock: host time=%ss guest time=%ss",
                  *after_hwclock)

    if test_type == 'guest_suspend':
        date_diff = time_diff(before_date, after_date)
        hwclock_diff = time_diff(before_hwclock, after_hwclock)
        if date_diff > tolerance and hwclock_diff > tolerance:
            raise error.TestFail("hwclock %ss and date %ss difference is "
                                 "'guest_diff_time != host_diff_time'"
                                 " out of tolerance %ss" % (hwclock_diff,
                                                            date_diff,
                                                            tolerance))
        elif date_diff > tolerance:
            raise error.TestFail("date %ss difference is "
                                 "'guest_diff_time != host_diff_time'"
                                 " out of tolerance %ss" % (date_diff,
                                                            tolerance))
        elif hwclock_diff > tolerance:
            raise error.TestFail("hwclock %ss difference is "
                                 "'guest_diff_time != host_diff_time'"
                                 " out of tolerance %ss" % (hwclock_diff,
                                                            tolerance))
    elif test_type == "guest_pause_resume":
        date_diff = time_diff(before_date, after_date)
        if date_diff > tolerance:
            raise error.TestFail("date %ss difference is"
                                 "'guest_time_after-guest_time_before'"
                                 " out of tolerance %ss" % (date_diff,
                                                            tolerance))
