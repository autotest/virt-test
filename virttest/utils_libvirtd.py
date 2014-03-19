"""
Module to control libvirtd service.
"""
import logging
import re
from virttest import remote, aexpect, utils_misc
from autotest.client.shared import error
from autotest.client import utils, os_dep


class LibvirtdError(Exception):

    """
    Base Error of libvirtd.
    """
    pass


class LibvirtdActionError(LibvirtdError):

    """
    Error in service command.
    """

    def __init__(self, action, detail):
        LibvirtdError.__init__(self)
        self.action = action
        self.detail = detail

    def __str__(self):
        return ('Failed to %s libvirtd.\n'
                'Detail: %s.' % (self.action, self.detail))


class LibvirtdActionUnknownError(LibvirtdActionError):

    """
    Error in service command when service name is unknown.
    """

    def __init__(self, action):
        self.action = action
        self.detail = 'Action %s is Unknown.' % self.action
        LibvirtdActionError.__init__(self, self.action, self.detail)

try:
    os_dep.command("libvirtd")
    LIBVIRTD = "libvirtd"
except ValueError:
    LIBVIRTD = None


def service_libvirtd_control(action, remote_ip=None,
                             remote_pwd=None, remote_user='root',
                             libvirtd=LIBVIRTD):
    """
    Libvirtd control by action, if cmd executes successfully,
    return True, otherwise raise LibvirtActionError.

    If the action is status, return True when it's running,
    otherwise return False.

    @ param action: start|stop|status|restart|condrestart|
      reload|force-reload|try-restart
    @ raise LibvirtdActionUnknownError: Action is not supported.
    @ raise LibvirtdActionError: Take the action on libvirtd Failed.
    """
    if LIBVIRTD is None:
        logging.warning("Libvirtd service is not available in host, "
                        "utils_libvirtd module will not function normally")
    service_cmd = ('service %s %s' % (libvirtd, action))

    actions = ['start', 'stop', 'restart', 'condrestart', 'reload',
               'force-reload', 'try-restart']

    session = None
    if remote_ip:
        try:
            session = remote.wait_for_login('ssh', remote_ip, '22',
                                            remote_user, remote_pwd,
                                            r"[\#\$]\s*$")
        except remote.LoginError, detail:
            raise LibvirtdActionError(action, detail)

    if action in actions:
        try:
            if session:
                session.cmd(service_cmd)
            else:
                utils.run(service_cmd)
        except (error.CmdError, aexpect.ShellError), detail:
            raise LibvirtdActionError(action, detail)
        if action is not 'stop':
            if not libvirtd_wait_for_start(session=session):
                raise LibvirtdActionError(action, "Libvirtd doesn't started.")

    elif action == "status":
        if session:
            try:
                output = session.cmd_output(service_cmd)
            except aexpect.ShellError, detail:
                raise LibvirtdActionError(action, detail)
        else:
            cmd_result = utils.run(service_cmd, ignore_status=True)
            output = cmd_result.stdout
        logging.debug("Checking libvirtd status:\n%s", output)
        if re.search("running", output):
            return True
        else:
            return False
    else:
        raise LibvirtdActionUnknownError(action)


def libvirtd_restart():
    """
    Restart libvirt daemon.
    """
    try:
        service_libvirtd_control('restart')
        logging.debug("Restarted libvirtd successfully")
        return libvirtd_wait_for_start()
    except LibvirtdActionError, detail:
        logging.debug("Failed to restart libvirtd:\n%s", detail)
        return False


def libvirtd_stop():
    """
    Stop libvirt daemon.
    """
    try:
        service_libvirtd_control('stop')
        logging.debug("Stop libvirtd successfully")
        return True
    except LibvirtdActionError, detail:
        logging.debug("Failed to stop libvirtd:\n%s", detail)
        return False


def libvirtd_start():
    """
    Start libvirt daemon.
    """
    try:
        service_libvirtd_control('start')
        logging.debug("Start libvirtd successfully")
        return libvirtd_wait_for_start()
    except LibvirtdActionError, detail:
        logging.debug("Failed to start libvirtd:\n%s", detail)
        return False


def libvirtd_is_running():
    """
    Check if libvirt service is running.
    """
    return service_libvirtd_control('status')


def libvirtd_wait_for_start(timeout=60, session=None):
    """
    Wait n seconds for libvirt to start. Default is 10 seconds.
    """
    def _check_start():
        virsh_cmd = "virsh list"
        try:
            if session:
                session.cmd(virsh_cmd, timeout=2)
            else:
                utils.run(virsh_cmd, timeout=2)
            return True
        except:
            return False
    return utils_misc.wait_for(_check_start, timeout=timeout)
