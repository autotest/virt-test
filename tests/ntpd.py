import logging
import time
from autotest.client.shared import utils, error
from virttest import remote, utils_test, aexpect
from virttest.staging import service


class NTPTest(object):
    """
    This class is for ntpd test
    """
    def __init__(self, params, env):
        """
        Initialize the object and set a few attributes.
        """
        self.server_hostname = None
        self.server_ip = params.get("remote_ip")
        if self.server_ip.count("REMOTE"):
            raise error.TestNAError("Please set server ip!")
        self.server_user = params.get("remote_user")
        self.server_password = params.get("remote_pwd")
        self.local_clock = params.get("local_clock")
        self.net_range = params.get("net_range")
        self.mask = params.get("mask", "255.255.255.0")
        self.restrict_option = params.get("restrict_option")
        self.vm_name = params.get("main_vm")
        self.ntpdate_sleep = int(params.get("ntpdate_sleep", "0"))
        self.ntpd_sleep = int(params.get("ntpd_sleep", "0"))
        self.long_sleep = int(params.get("long_sleep", "0"))
        self.vm = env.get_vm(self.vm_name)
        try:
            self.server_session = remote.wait_for_login('ssh',
                                                     self.server_ip, "22",
                                                     self.server_user,
                                                     self.server_password,
                                                     r"[\$#]\s*$")
            self.session = self.vm.wait_for_login()
        except remote.LoginTimeoutError, detail:
            raise error.TestNAError(str(detail))

    def close_session(self):
        """
        CLose connection of server and guest.
        """
        self.server_session.close()
        self.session.close()

    # Server configuration
    def server_config(self):
        """
        configuer the ntp server:
        1.ZONE = American/New_York;
        2.start ntpd service;
        3.restrict the host and guest
        """
        logging.info("waiting for login server.....")
        self.server_hostname = self.server_session.\
                               cmd_output('hostname').strip()
        logging.debug("service hostname is %s" % self.server_hostname)
        cmd =  'echo \'ZONE = "America/New_York"\' > /etc/sysconfig/clock'
        status = self.server_session.cmd_status(cmd)
        if status:
            raise error.TestError("set ZONE in server failed.")
        cmd_ln = 'ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime'
        self.server_session.cmd_status(cmd_ln)

        # Add server of local clock
        output = self.server_session.cmd_output("grep '^server %s'"
                                                " /etc/ntp.conf"
                                                % self.local_clock).strip()
        if not output:
            status = self.server_session.cmd_status("echo 'server %s' >> "
                                                    "/etc/ntp.conf"
                                                    % self.local_clock)
            if status:
                raise error.TestError("config local_clock failed.")

        # Add host and guest in restrict
        output = self.server_session.cmd_output("grep '^restrict %s'"
                                                " /etc/ntp.conf"
                                                % self.net_range).strip()
        if not output:
            status = self.server_session.cmd_status("echo 'restrict %s "
                                                    "mask %s %s' "
                                                    ">> /etc/ntp.conf"
                                                    % (self.net_range,
                                                       self.mask,
                                                       self.restrict_option))
            if status:
                raise error.TestError("config restrict failed.")

        # Restart ntpd service
        server_run = remote.RemoteRunner(session=self.server_session)
        server_ntpd = service.Factory.create_service("ntpd", run=server_run.run)
        server_ntpd.restart()


    # Host configuration
    def host_config(self):
        """
        configuer the host :
        1.ZONE = American/New_York;
        2.check cpuinfo;
        3.add ntp server ip;
        4.start ntpd service
        """
        # Set the time zone to New_York
        cmd =  ('echo \'ZONE = "America/New_York"\' > /etc/sysconfig/clock;')
        try:
            utils.run(cmd, ignore_status=False)
        except error.CmdError, detail:
            raise error.TestFail("set Zone on host failed.%s" % detail)
        cmd_ln = 'ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime'
        utils.run(cmd_ln, ignore_status=True)

        # Check the cpu info of constant_tsc
        cmd = "cat /proc/cpuinfo | grep constant_tsc"
        result = utils.run(cmd)
        if not result.stdout.strip():
            raise error.TestFail("constant_tsc not available in this system!!")

        # Stop ntpd to use ntpdate
        host_ntpd = service.Factory.create_service("ntpd")
        host_ntpd.stop()

        # Timing by ntpdate
        utils_test.ntpdate(self.server_ip)

        # Test the ntpdate result
        server_date = utils_test.get_date(self.server_session)
        host_date = utils_test.get_date()
        logging.info("server time: %s" % server_date)
        logging.info("host time: %s" % host_date)
        if not abs(int(server_date) - int(host_date)) < 2:
            raise error.TestFail("timing by ntpdate on host failed!!")

        # Delete server of local clock
        result = utils.run("grep '^server %s' /etc/ntp.conf" % self.local_clock,
                           ignore_status = True)
        if result.stdout.strip():
            utils.run("sed -i '/%s/d' /etc/ntp.conf" % self.local_clock)
        # Check the ntp.conf and add server ip into it
        cmd = "grep '^server %s' /etc/ntp.conf" % self.server_ip
        result = utils.run(cmd, ignore_status=True)
        if not result.stdout.strip():
            cmd = "echo 'server %s' >> /etc/ntp.conf" % self.server_ip
            try:
                utils.run(cmd, ignore_status=False)
            except error.CmdError, detail:
                raise error.TestFail("config /etc/ntp.conf on host failed!!")

        # Start ntpd service
        host_ntpd.start()

    # Guest configure
    def guest_config(self):
        """
        configure the guest:
        1.ZONE = American/New_York;
        2.test the ntpdate;
        3.configur the ntp.conf;
        4.restart ntpd service
        """
        # Set the time zone to american new york
        cmd =  ('echo \'ZONE = "America/New_York"\' > /etc/sysconfig/clock;')
        self.session.cmd(cmd)
        cmd_ln = 'ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime'
        self.session.cmd(cmd_ln)

        # Timing by ntpdate
        guest_run = remote.RemoteRunner(session=self.session)
        guest_ntpd = service.Factory.create_service("ntpd", run=guest_run.run)
        guest_ntpd.stop()

        # ntpdate
        utils_test.ntpdate(self.server_ip, self.session)

        # Check the result of ntpdate
        server_date = utils_test.get_date(self.server_session)
        guest_date = utils_test.get_date(self.session)
        logging.info("server time is : %s" % server_date)
        logging.info("guest time is : %s " % guest_date)
        if not abs(int(server_date) - int(guest_date)) < 2:
            raise error.TestFail("timing by ntpdate on guest failed!!")

        # Delete server of local clock
        output = self.session.cmd_output("grep '%s' /etc/ntp.conf"
                                         % self.local_clock).strip()
        if not output:
            self.session.cmd("sed -i '/%s/d' /etc/ntp.conf" % self.local_clock)
        # Check the ntp.conf and add server ip into it
        output = self.session.cmd_output("grep '^server %s' /etc/ntp.conf"
                                         % self.server_ip)
        if not output:
            cmd = "echo 'server %s' >> /etc/ntp.conf" % self.server_ip
            status = self.session.cmd_status(cmd)
            if status:
                raise error.TestFail("config /etc/ntp.conf on server failed!!")

        # Start the ntpd service
        guest_ntpd.start()

    # Test ntpd on host and guest by ntpq -p
    def ntpq_test(self):
        """
        test the service ntpd after 20m: ntpq -p on host and guest
        """
        logging.info("waiting for ntpd timing : %s s" % self.ntpd_sleep)
        time.sleep(self.ntpd_sleep)
        # Test on host
        cmd_ip = "ntpq -p | grep '^*%s'" % self.server_ip
        cmd_name = ""
        if self.server_hostname:
            cmd_name = "ntpq -p | grep '^*%s'" % self.server_hostname
        result_ntpq_ip = utils.run(cmd_ip, ignore_status=True)
        result_ntpq_name = utils.run(cmd_name, ignore_status=True)
        if (not result_ntpq_ip.stdout.strip()
            and not result_ntpq_name.stdout.strip()):
            raise error.TestFail("ntpd setting failed of %s host !!"
                                 % self.vm_name)
        # Test on guest
        output_ip = self.session.cmd_output(cmd_ip).strip()
        output_name = self.session.cmd_output(cmd_name).strip()
        if not output_ip and not output_name:
            raise error.TestFail("ntpd setting failed of %s guest !!"
                                 % self.vm_name)

    def long_time_test(self):
        """
        test on guest ntpd after 24h
        """
        logging.info("waiting for long time test : %s s" % self.long_sleep)
        time.sleep(self.long_sleep)
        server_date = utils_test.get_date(self.server_session)
        guest_date = utils_test.get_date(self.session)
        logging.info("server time is %s" % server_date)
        logging.info("guest time is %s" % guest_date)
        if not abs(int(server_date) - int(guest_date)) < 2:
            raise error.TestFail("timing by ntpd on guest failed")


def run_ntpd(test, params, env):
    """
    Test ntpd service, in default setting the execution
    will take longer than 24 hours.

    1.Configure ntpd service in server
    2.Set the date and configure ntpd service in host
    3.Set the date and configure ntpd service in guest
    4.Check ntpd service valid in guest
    5.After long time, test ntpd service still works on guest.
    """

    ntp_test = NTPTest(params, env)
    ping_s, _ = utils_test.ping(ntp_test.server_ip, count=1,
                                timeout=5, session=ntp_test.session)
    if ping_s:
        ntp_test.close_session()
        raise error.TestNAError("Please make sure the guest can ping server!")

    # Start test from here
    try:
        # Server configuration
        try:
            ntp_test.server_config()
        except (aexpect.ShellError, remote.LoginTimeoutError), detail:
            raise error.TestFail("server config failed. %s" % detail)
        logging.info("waiting for ntp server : %s s" % ntp_test.ntpdate_sleep)
        # Host and Guest will use server's ntpd service to set time.
        # here wait for some seconds for server ntpd service valid
        time.sleep(ntp_test.ntpdate_sleep)

        # Host configuration
        try:
            ntp_test.host_config()
        except (aexpect.ShellError, remote.LoginTimeoutError), detail:
            raise error.TestFail("host config failed.%s" % detail)

        # Guest configuration
        try:
            ntp_test.guest_config()
        except (aexpect.ShellError, remote.LoginTimeoutError), detail:
            raise error.TestFail("guest config failed.%s" % detail)

        try:
            # Wait 20min for ntpq test
            ntp_test.ntpq_test()
        except (aexpect.ShellError, remote.LoginTimeoutError), detail:
            raise error.TestFail("ntpq test failed.%s" % detail)

        try:
            # Wait 24h for  test
            ntp_test.long_time_test()
        except (aexpect.ShellError, remote.LoginTimeoutError), detail:
            raise error.TestFail("long time test failed.%s" % detail)
    finally:
        ntp_test.close_session()
