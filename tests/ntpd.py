import logging
import time
from autotest.client.shared import utils, error
from virttest import remote, utils_ntpd, aexpect
from virttest.utils_test.__init__ import ping

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

    server_ip = params.get("server_ip")
    server_user = params.get("server_user")
    server_password = params.get("server_password")
    local_clock = params.get("local_clock")
    net_range = params.get("net_range")
    mask = params.get("mask", "255.255.255.0")
    restrict_option = params.get("restrict_option")
    vm_name = params.get("main_vm")
    ntpdate_sleep = int(params.get("ntpdate_sleep", "0"))
    ntpd_sleep = int(params.get("ntpd_sleep", "0"))
    long_sleep = int(params.get("long_sleep", "0"))
    vm = env.get_vm(vm_name)
    try:
        session = vm.wait_for_login()
    except remote.LoginTimeoutError, detail:
        raise error.TestNAError(str(detail))
    ping_s, _ = ping(server_ip, count=1, timeout=5, session=session)
    if ping_s:
        session.close()
        raise error.TestNAError("Please make sure the guest can ping server!")
    session.close()
    server_hostname = None

    # Server configuration
    def server_config():
        """
        configuer the ntp server:
        1.ZONE = American/New_York;
        2.start ntpd service;
        3.restrict the host and guest
        """
        logging.info("waiting for login server.....")
        server_session = remote.wait_for_login('ssh', server_ip,"22",
                                               server_user,
                                               server_password, "#")
        global server_hostname
        server_hostname = server_session.cmd_output('hostname').strip()
        logging.debug("service hostname is %s" % server_hostname)
        cmd =  'echo \'ZONE = "America/New_York"\' > /etc/sysconfig/clock'
        status = server_session.cmd_status(cmd)
        if status:
            raise error.TestError("set ZONE in server failed.")
        cmd_cp = 'cp -f /usr/share/zoneinfo/America/New_York /etc/localtime'
        try:
            server_session.cmd_status(cmd_cp)
        except aexpect.ShellError:
            server_session.cmd_status("\n")

        # Add server of local clock
        output = server_session.cmd_output("grep '^server %s' /etc/ntp.conf"
                                           % local_clock).strip()
        if not output:
            status = server_session.cmd_status("echo 'server %s' >> "
                                               "/etc/ntp.conf" % local_clock)
            if status:
                raise error.TestError("config local_clock failed.")

        # Add host and guest in restrict
        output = server_session.cmd_output("grep '^restrict %s' /etc/ntp.conf"
                                           % net_range).strip()
        if not output:
            status = server_session.cmd_status("echo 'restrict %s mask %s %s' "
                                               ">> /etc/ntp.conf"
                                               % (net_range, mask,
                                                  restrict_option))
            if status:
                raise error.TestError("config restrict failed.")

        # Restart ntpd service
        utils_ntpd.ntpd_restart(server_session)
        server_session.close()


    # Host configuration
    def host_config():
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
        cmd_cp = 'cp -f /usr/share/zoneinfo/America/New_York /etc/localtime'
        utils.run(cmd_cp, ignore_status=True)

        # Check the cpu info of constant_tsc
        cmd = "cat /proc/cpuinfo | grep constant_tsc"
        result = utils.run(cmd)
        if not result.stdout.strip():
            raise error.TestFail("constant_tsc not available in this system!!")

        # Stop ntpd to use ntpdate
        utils_ntpd.ntpd_stop()


        # Timing by ntpdate
        utils_ntpd.ntpdate(server_ip)

        # Test the ntpdate result
        server_session = remote.wait_for_login('ssh', server_ip, "22",
                                               server_user,
                                               server_password, "#")
        server_date = utils_ntpd.get_date(server_session)
        host_date = utils_ntpd.get_date()
        server_session.close()
        logging.info("server time: %s" % server_date)
        logging.info("host time: %s" % host_date)
        if not abs(int(server_date) - int(host_date)) < 2:
            raise error.TestFail("timing by ntpdate on host failed!!")

        # Delete server of local clock
        result = utils.run("grep '^server %s' /etc/ntp.conf" % local_clock,
                           ignore_status = True)
        if result.stdout.strip():
            utils.run("sed -i '/%s/d' /etc/ntp.conf" % local_clock)
        # Check the ntp.conf and add server ip into it
        cmd = "grep '^server %s' /etc/ntp.conf" % server_ip
        result = utils.run(cmd, ignore_status=True)
        if not result.stdout.strip():
            cmd = "echo 'server %s' >> /etc/ntp.conf" % server_ip
            try:
                utils.run(cmd, ignore_status=False)
            except error.CmdError, detail:
                raise error.TestFail("config /etc/ntp.conf on host failed!!")

        # Start ntpd service
        utils_ntpd.ntpd_start()

    # Guest configure
    def guest_config():
        """
        configure the guest:
        1.ZONE = American/New_York;
        2.test the ntpdate;
        3.configur the ntp.conf;
        4.restart ntpd service
        """
        session = vm.wait_for_login()
        # Set the time zone to american new york
        cmd =  ('echo \'ZONE = "America/New_York"\' > /etc/sysconfig/clock;')
        session.cmd(cmd)
        cmd_cp = 'cp -f /usr/share/zoneinfo/America/New_York /etc/localtime'
        try:
            session.cmd(cmd_cp)
        except aexpect.ShellError:
            # Sometimes they are same file
            session.cmd_status("\n")

        # Timing by ntpdate
        utils_ntpd.ntpd_stop(session)

        # ntpdate
        utils_ntpd.ntpdate(server_ip, session)

        # Check the result of ntpdate
        server_session = remote.wait_for_login('ssh', server_ip, "22",
                                               server_user,
                                               server_password, "#")
        server_date = utils_ntpd.get_date(server_session)
        guest_date = utils_ntpd.get_date(session)
        server_session.close()
        logging.info("server time is : %s" % server_date)
        logging.info("guest time is : %s " % guest_date)
        if not abs(int(server_date) - int(guest_date)) < 2:
            raise error.TestFail("timing by ntpdate on guest failed!!")

        # Delete server of local clock
        output = session.cmd_output("grep '%s' /etc/ntp.conf" %
                                    local_clock).strip()
        if not output:
            session.cmd("sed -i '/%s/d' /etc/ntp.conf" % local_clock)
        # Check the ntp.conf and add server ip into it
        output = session.cmd_output("grep '^server %s' /etc/ntp.conf" %
                                    server_ip)
        if not output:
            cmd = "echo 'server %s' >> /etc/ntp.conf" % server_ip
            status = session.cmd_status(cmd)
            if status:
                raise error.TestFail("config /etc/ntp.conf on server failed!!")

        # Start the ntpd service
        utils_ntpd.ntpd_start(session)
        session.close()

    # Test ntpd on host and guest by ntpq -p
    def ntpq_test():
        """
        test the service ntpd after 20m: ntpq -p on host and guest
        """
        # Test on host
        cmd_ip = "ntpq -p | grep '^*%s'" % server_ip
        cmd_name = ""
        global server_hostname
        if server_hostname:
            cmd_name = "ntpq -p | grep '^*%s'" % server_hostname
        result_ntpq_ip = utils.run(cmd_ip, ignore_status=True)
        result_ntpq_name = utils.run(cmd_name, ignore_status=True)
        if (not result_ntpq_ip.stdout.strip()
            and not result_ntpq_name.stdout.strip()):
            raise error.TestFail("ntpd setting failed of %s host !!" % vm_name)
        # Test on guest
        session = vm.wait_for_login()
        output_ip = session.cmd_output(cmd_ip).strip()
        output_name = session.cmd_output(cmd_name).strip()
        session.close()
        if not output_ip and not output_name:
            raise error.TestFail("ntpd setting failed of %s guest !!"
                                 % vm_name)

    def long_time_test():
        """
        test on guest ntpd after 24h
        """
        server_session = remote.wait_for_login('ssh', server_ip, "22",
                                               server_user,
                                               server_password, "#")
        session = vm.wait_for_login()
        server_date = utils_ntpd.get_date(server_session)
        guest_date = utils_ntpd.get_date(session)
        server_session.close()
        session.close()
        logging.info("server time is %s" % server_date)
        logging.info("guest time is %s" % guest_date)
        if not abs(int(server_date) - int(guest_date)) < 2:
            raise error.TestFail("timing by ntpd on guest failed")

    # Start test from here

    # Server configuration
    try:
        server_config()
    except (aexpect.ShellError, remote.LoginTimeoutError), detail:
        raise error.TestFail("server config failed. %s" % detail)
    logging.info("waiting for ntp server : %s s" % ntpdate_sleep)
    time.sleep(ntpdate_sleep)

    # Host configuration
    try:
        host_config()
    except (aexpect.ShellError, remote.LoginTimeoutError), detail:
        raise error.TestFail("host config failed.%s" % detail)

    # Guest configuration
    try:
        guest_config()
    except (aexpect.ShellError, remote.LoginTimeoutError), detail:
        raise error.TestFail("guest config failed.%s" % detail)

    try:
        # Wait 20min for ntpq test
        logging.info("waiting for ntpd timing : %s s" % ntpd_sleep)
        time.sleep(ntpd_sleep)
        ntpq_test()
    except (aexpect.ShellError, remote.LoginTimeoutError), detail:
        raise error.TestFail("ntpq test failed.%s" % detail)

    try:
        # Wait 24h for  test
        logging.info("waiting for long time test : %s s" % long_sleep)
        time.sleep(long_sleep)
        long_time_test()
    except (aexpect.ShellError, remote.LoginTimeoutError), detail:
        raise error.TestFail("long time test failed.%s" % detail)
