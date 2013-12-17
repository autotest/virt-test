import os
import re
import time
import logging
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import data_dir
from virttest import env_process
from tests.guest_suspend import GuestSuspendBaseTest


class TimedriftTest(object):

    """
    Base class for time drift test, include common steps for time drift test;
    """

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.open_sessions = []
        self.ntp_server = params.get("ntp_server", "clock.redhat.com")
        self.tolerance = float(self.params.get("time_diff_tolerance", "6.0"))

    def is_windows_guest(self):
        """
        Check is a windows guest;

        :return: False or True
        :rtype: bool
        """
        return "windows" in self.params["os_type"]

    def get_session(self, vm):
        timeout = float(self.params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        self.open_sessions.append(session)
        return session

    def get_vm(self, vm_name=None):
        """
        Get a live vm, if not create it;

        :param vm_name: vm name;
        :return: qemu vm object;
        :rtype: VM object;
        """
        name = vm_name or self.params["main_vm"]
        self.params["start_vm"] = "yes"
        self.params["restart_vm"] = "no"
        env_process.preprocess_vm(self.test, self.params, self.env, name)
        vm = self.env.get_vm(name)
        vm.verify_alive()
        return vm

    def _close_sessions(self):
        for session in self.open_sessions:
            if session:
                try:
                    session.close()
                except:
                    pass

    def execute(self, cmd, session=None):
        """
        Execute command in guest or host, if session is not None return
        command output in guest else return command ouput in host;

        :param cmd: shell commands;
        :param session: ShellSession or None;
        :return: command output string
        :rtype: str
        """
        try:
            if session:
                timeout = int(self.params.get("execute_timeout", 360))
                ret = session.cmd_output(cmd, timeout=timeout)
            else:
                ret = utils.system_output(cmd)
        except Exception, e:
            target = session and "guest" or "host"
            logging.debug("Run command('%s') in %s" % (target, cmd))
            raise e
        return ret

    def calibrate_time(self, session=None):
        """
        calibrate system time via ntp server, if session is not None,
        calibrate guest time else calibrate host time;

        :param session: ShellSession object or None
        :return: ntpdate command output;
        :rtype: str
        """
        if session and self.is_windows_guest():
            cmd = "w32tm /config "
            cmd += "/manualpeerlist:%s " % self.ntp_server
            cmd += "/syncfromflags:manual /update"
        else:
            cmd = "ntpdate %s && hwclock -w" % self.ntp_server
        return self.execute(cmd, session)

    def get_time(self, session, time_command, time_filter_re, time_format):
        """
        Get a unix epoch time; 

        :param session: ShellSession object;
        :param time_command: command to get time string from host/guest;
        :param time_filter_re: regrex to filter out formated time from string;
        :param time_format: time format of time_command out put;
        :return: pair of host time and guest time;  
        """
        def make_time(output):
            # Get and parse host time
            reo = re.findall(time_filter_re, output)[0]
            if isinstance(reo, tuple):
                time_str = reo[0].strip()
                diff = float(reo[1])
            else:
                time_str = reo.strip()
                diff = 0.0
            logging.info("timestr: %s, diff: %s" % (time_str, diff))
            try:
                num_time = time.mktime(time.strptime(time_str, time_format))
                num_time += float(diff)
                return num_time
            except Exception, err:
                logging.debug("(time_format, time_string): (%s, %s)",
                              time_format, output)
                raise err

        time_filter_re = r"%s" % time_filter_re
        guest_time = make_time(self.execute(time_command, session))
        if "hwclock" in time_command:
            host_time = make_time(self.execute(time_command))
        else:
            host_time = time.time()
        return (host_time, guest_time)

    def verify_clock_source(self, session):
        """
        Verify guest used expected clocksource;

        :param session: ShellSession object;
        :raise: error.TestFail Exception
        """
        clock_source = self.params.get("guest_clock_source", "kvm-clock")
        read_clock_cmd = "cat /sys/devices/system/clocksource/"
        read_clock_cmd += "clocksource0/current_clocksource"
        current_clocksource = session.cmd_output(read_clock_cmd)
        if not clock_source in current_clocksource:
            raise error.TestFail("Guest didn't use'%s'" % clock_source +
                                 "clocksource, current clocksoure " +
                                 "is %s;" % current_clocksource)

    def cleanup(self):
        self._close_sessions()
        self.calibrate_time()


class BackwardtimeTest(TimedriftTest):

    """
    Base class for test time drift after backward host/guest system clock;
    """

    def __init__(self, test, params, env):
        super(BackwardtimeTest, self).__init__(test, params, env)

    def set_time(self, nsec, session=None):
        """
        Change host/guest time, if session is not None, change guest time,
        else change host time;

        :param nsec: float seconds, if nsec >0 forward else backward time;
        :param session: ShellSession object;
        """
        src_file = os.path.join(data_dir.get_deps_dir(), "change_time.py")
        python_bin = "python"
        if session:
            dst_dir = self.params["tmp_dir"]
            dst_file = "%s/change_time.py" % dst_dir
            python_bin = self.params["python_bin"]
            if self.is_windows_guest():
                dst_file = r"%s\change_time.py" % dst_dir
            vm = self.get_vm()
            vm.copy_files_to(src_file, dst_dir)
        else:
            dst_file = src_file
        set_time_cmd = "%s %s %s" % (python_bin, dst_file, float(nsec))
        return self.execute(set_time_cmd, session)

    def time_diff(self, session, clock="sys"):
        """
        Calculate system/hardware time difference bewteen host and guest;

        :param session: ShellSession object;
        :param clock: 'hw'or 'sys'
        :return: time difference
        :rtype: float
        """
        time_command = self.params.get("%s_time_command" % clock)
        time_filter_re = self.params.get("%s_time_filter_re" % clock)
        time_format = self.params.get("%s_time_format" % clock)
        host_time, guest_time = self.get_time(session,
                                              time_command,
                                              time_filter_re,
                                              time_format)
        guest_ctime = time.ctime(guest_time)
        host_ctime = time.ctime(host_time)
        debug_msg = "Host %s Time: %s = %s epoch seconds " % (clock,
                                                              host_ctime,
                                                              host_time)
        logging.info(debug_msg)
        debug_msg = "Guest %s Time: %s = %s epoch seconds" % (clock,
                                                              guest_ctime,
                                                              guest_time)
        logging.info(debug_msg)
        return abs(host_time - guest_time)

    def check_drift_after_adjust_time(self, session, clock="sys"):
        """
        Verify host/guest system/hardware clock drift after change host/guest
        time;

        :param session: ShellSession
        :param clock: 'sys' or 'hw'
        :raise: error.TestFail Exception
        """
        current_diff = self.time_diff(session, clock=clock)
        excepted_diff = "%s_time_difference" % clock
        excepted_diff = self.params.get(excepted_diff, "0")
        for x in re.findall(r"\$\{(.*)\}", excepted_diff):
            excepted_diff = excepted_diff.replace("${%s}" % x, self.params[x])
        excepted_diff = float(eval(excepted_diff))
        drift = abs(excepted_diff - current_diff)
        if drift > self.tolerance:
            raise error.TestFail("%s clock has more that " % clock +
                                 "%s seconds " % self.tolerance +
                                 "drift (%s) after test" % drift)

    def check_dirft_before_adjust_time(self, session, clock="sys"):
        """
        Verify host/guest system/hardware clock drift before change host/guest
        time;

        :param session: ShellSession
        :param clock: 'sys' or 'hw'
        :raise: error.TestFail Exception
        """
        drift = self.time_diff(session, clock)
        if drift > self.tolerance:
            raise error.TestFail("%s clock has more that " % clock +
                                 "%s seconds drift " % self.tolerance +
                                 "(%s) before test" % drift)

    @error.context_aware
    def pre_test(self):
        """
        TODO:
            step 1: sync host time from ntp server;
            step 2: unify timezone of host and guest;
            step 3: verify system/hardware time drift between host and guest;
            step 4: verify guest clock source if linux guest;
        """
        error.context("calibrate host time", logging.info)
        self.calibrate_time()
        vm = self.get_vm()
        session = self.get_session(vm)
        error.context("check guest system time drift", logging.info)
        self.check_dirft_before_adjust_time(session, clock="sys")
        if not self.is_windows_guest():
            error.context("check guest hardware time drift", logging.info)
            self.check_dirft_before_adjust_time(session, clock="hw")
            error.context("check guest clocksource", logging.info)
            self.verify_clock_source(session)

    @error.context_aware
    def post_test(self):
        """
        TODO:
            step 7: verify system time drift between host and guest;
            step 8: close opening session and calibrate host time;
        Notes:
            Hardware clock time drift will not be check as it's a know issue;
        """
        vm = self.get_vm()
        session = self.get_session(vm)
        error.context("check guest system time drift", logging.info)
        self.check_drift_after_adjust_time(session, clock="sys")
        error.context("reset host system/hardware time", logging.info)
        self.cleanup()

    def run(self, fuc):
        self.pre_test()
        if callable(fuc):
            fuc()
        self.post_test()


@error.context_aware
def run_timedrift_adjust_time(test, params, env):
    """
    Time drift after change host/guest sysclock test:

    Include sub test:
       1): reboot guest after change host/guest system clock
       2): pause guest change host system clock and wait a long time, then
       cont guest;
       3): suspend guest change host system clock and wait a long time, then
       Resume guest;

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    class Test_reboot(BackwardtimeTest):

        """
        Test Steps:
            5) Forward host/guest system time 30mins
            6) Reboot guest
        """

        def __init__(self, test, params, env):
            super(Test_reboot, self).__init__(test, params, env)

        @error.context_aware
        def reboot(self):
            error.context("Reboot guest", logging.info)
            vm = self.get_vm()
            session = self.get_session(vm)
            host_sec = self.params.get("change_host_seconds")
            if host_sec:
                self.set_time(host_sec)
            guest_sec = self.params.get("change_guest_seconds")
            if guest_sec:
                self.set_time(guest_sec, session=session)
            vm.reboot(session=session, method="shell")

        def run(self):
            fuc = self.reboot
            return super(Test_reboot, self).run(fuc)

    class Test_pause_cont(BackwardtimeTest):

        """
        Test Steps:
            5) Forward host system time 30mins
            6) Pause guest 30 mins, then cont it;
        """

        def __init__(self, test, params, env):
            super(Test_pause_cont, self).__init__(test, params, env)

        @error.context_aware
        def pause_cont(self):
            vm = self.get_vm()
            sleep_time = float(params.get("sleep_time", 1800))
            error.context("Pause guest %s seconds" % sleep_time,
                          logging.info)
            vm.pause()
            host_sec = self.params.get("change_host_seconds")
            if host_sec:
                self.set_time(host_sec)
            time.sleep(sleep_time)
            error.context("Resume guest", logging.info)
            vm.resume()

        def run(self):
            fuc = self.pause_cont
            return super(Test_pause_cont, self).run(fuc)

    class Test_suspend_resume(BackwardtimeTest, GuestSuspendBaseTest):

        """
        Test Steps:
            5) Suspend guest 30 mins, then resume it;
            6) Forward host system time 30mins
        """

        def __init__(self, test, params, env):
            BackwardtimeTest.__init__(self, test, params, env)

        @error.context_aware
        def action_during_suspend(self, **args):
            sleep_time = float(self.params.get("sleep_time", 1800))
            error.context("Sleep %s seconds before resume" % sleep_time,
                          logging.info)
            host_sec = self.params.get("change_host_seconds")
            if host_sec:
                self.set_time(host_sec)
            time.sleep(sleep_time)

        def suspend_resume(self):
            vm = self.get_vm()
            GuestSuspendBaseTest.__init__(self, params, vm)
            if self.params.get("guest_suspend_type") == "mem":
                self.guest_suspend_mem(self.params)
            else:
                self.guest_suspend_disk(self.params)

        def run(self):
            fuc = self.suspend_resume
            return super(Test_suspend_resume, self).run(fuc)

    test_name = "Test_%s" % params["vm_action"]
    SubTest = locals().get(test_name)
    if issubclass(SubTest, BackwardtimeTest):
        timedrift_test = SubTest(test, params, env)
        timedrift_test.run()
