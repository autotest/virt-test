"""
Module to control ntpd service.
"""
import logging
import re
from virttest import aexpect, utils_misc
from autotest.client.shared import error
from autotest.client import utils, os_dep


class NtpdError(Exception):

    """
    Base Error of ntpd.
    """
    pass


class NtpdActionError(NtpdError):

    """
    Error in service command.
    """

    def __init__(self, action, detail):
        NtpdError.__init__(self)
        self.action = action
        self.detail = detail

    def __str__(self):
        return ('Failed to %s ntpd.\n'
                'Detail: %s.' % (self.action, self.detail))


class NtpdActionUnknownError(NtpdActionError):

    """
    Error in service command when service name is unknown.
    """

    def __init__(self, action):
        self.action = action
        self.detail = 'Action %s is Unknown.' % self.action
        NtpdActionError.__init__(self, self.action, self.detail)

try:
    os_dep.command("ntpd")
    NTPD = "ntpd"
except ValueError:
    NTPD = None
    logging.warning("Ntpd service is not available in host, "
                    "utils_ntpd module will not function normally")


def service_ntpd_control(action, session=None, ntpd=NTPD):
    """
    Ntpd control by action, if cmd executes successfully,
    return True, otherwise raise NtpActionError.

    If the action is status, return True when it's running,
    otherwise return False.

    @ param action: start|stop|status|restart|
      force-reload|try-restart
    @ raise NtpdActionUnknownError: Action is not supported.
    @ raise NtpdActionError: Take the action on ntpd Failed.
    """
    service_cmd = ('service %s %s' % (ntpd, action))

    actions = ['start', 'stop', 'restart', 
               'force-reload', 'try-restart']

    if action in actions:
        try:
            if session:
                session.cmd(service_cmd)
            else:
                utils.run(service_cmd)
        except (error.CmdError, aexpect.ShellError), detail:
            raise NtpdActionError(action, detail)
        if action is not 'stop':
            try:
                if session:
                    session.cmd("chkconfig %s on" % ntpd)
                else:
                    utils.run("chkconfig %s on" % ntpd)
            except (error.CmdError, aexpect.ShellError), detail:
                raise NtpdActionError(action, detail)
            if not ntpd_wait_for_start(session=session):
                raise NtpdActionError(action, "Ntpd wasn't started.")
        else:
            if not ntpd_wait_for_stop(session=session):
                raise NtpdActionError(action, "Ntpd wasn't stopped.")

    elif action == "status":
        if session:
            try:
                status, output = session.cmd_status_output(service_cmd)
            except aexpect.ShellError, detail:
                raise NtpdActionError(action, detail)
            if status:
                raise NtpdActionError(action, output)
        else:
            cmd_result = utils.run(service_cmd, ignore_status=True)
            if cmd_result.exit_status:
                raise NtpdActionError(action, cmd_result.stderr)
            output = cmd_result.stdout

        if re.search("running", output):
            return True
        else:
            return False
    else:
        raise NtpdActionUnknownError(action)


def ntpd_restart(session=None):
    """
    Restart ntp daemon.
    """
    try:
        service_ntpd_control('restart', session)
        logging.debug("Restarted ntpd successfully")
        return True
    except NtpdActionError, detail:
        logging.debug("Failed to restart ntpd:\n%s", detail)
        return False


def ntpd_stop(session=None):
    """
    Stop ntp daemon.
    """
    try:
        service_ntpd_control('stop', session)
        logging.debug("Stop ntpd successfully")
        return True
    except NtpdActionError, detail:
        logging.debug("Failed to stop ntpd:\n%s", detail)
        return False


def ntpd_start(session=None):
    """
    Start ntp daemon.
    """
    try:
        service_ntpd_control('start', session)
        logging.debug("Start ntpd successfully")
        return True
    except NtpdActionError, detail:
        logging.debug("Failed to start ntpd:\n%s", detail)
        return False


def ntpd_is_running(session=None):
    """
    Check if ntp service is running.
    """
    try:
        return service_ntpd_control('status', session)
    except NtpdActionError, detail:
        logging.debug("Failed to get status of ntpd:\n%s", detail)
        return False


def ntpdate(service_ip, session=None):
    """
    set the date and time via NTP
    """
    try:
        ntpdate_cmd = "ntpdate %s" % service_ip
        if session:
            session.cmd(ntpdate_cmd)
        else:
            utils.run(ntpdate_cmd)
    except (error.CmdError, aexpect.ShellError), detail:
        raise error.TestFail("Failed to set the date and time. %s" % detail)


def get_date(session=None):
    """
    set the date and time via NTP
    """
    try:
        date_cmd = "date +%s"
        if session:
            date_info = session.cmd_output(date_cmd).strip()
        else:
            date_info = utils.run(date_cmd).stdout.strip()
        return date_info
    except (error.CmdError, aexpect.ShellError), detail:
        raise error.TestFail("Get date failed. %s " % detail)


def ntpd_wait_for_stop(timeout=10, session=None):
    """
    Wait n seconds for ntpd to stop. Default is 10 seconds.
    """
    def _check_stop():
        """
        Check if ntpd is stop
        """
        return (not ntpd_is_running(session))
    return utils_misc.wait_for(_check_stop, timeout=timeout)


def ntpd_wait_for_start(timeout=10, session=None):
    """
    Wait n seconds for ntpd to start. Default is 10 seconds.
    """
    def _check_start():
        """
        Check if ntpd is running
        """
        return (ntpd_is_running(session))
    return utils_misc.wait_for(_check_start, timeout=timeout)
