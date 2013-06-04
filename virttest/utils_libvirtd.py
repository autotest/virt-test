"""
Module to control libvirtd service.
"""
import logging, re
from autotest.client.shared import error
from autotest.client import utils, os_dep
import remote


try:
    os_dep.command("libvirtd")
    LIBVIRTD = "libvirtd"
except ValueError:
    LIBVIRTD = "systemd-logind"

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
                'Detail: %s' % (self.action, self.detail))


class LibvirtdActionUnknownError(LibvirtdActionError):
    """
    Error in service command when service name is unkown.
    """
    def __init__(self, action):
        self.action = action
        self.detail = 'Action %s is Unknown.' % self.action
        LibvirtdActionError.__init__(self, self.action, self.detail)


def service_libvirtd_control(action, **dargs):
    """
    Libvirtd control by action, if cmd executes successfully,
    return True, otherwise raise LibvirtActionError.

    If the action is status, return True when it's running,
    otherwise return False.

    @ param action: start|stop|status|restart|condrestart|
      reload|force-reload|try-restart
    """
    #service_name for unittest.
    service_name = dargs.get('service_name', LIBVIRTD)
    remote_ip = dargs.get('remote_ip', None)
    remote_pwd = dargs.get('remote_pwd', None)
    remote_user = dargs.get('remote_user', 'root')
    service_cmd = ('service %s %s' % (service_name, action))

    actions = ['start', 'stop', 'restart', 'condrestart', 'reload',
               'force-reload', 'try-restart']
    if action in actions:
        try:
            if remote_ip is not None:
                session = remote.wait_for_login('ssh', remote_ip, '22',
                                 remote_user, remote_pwd, r"[\#\$]\s*$")
                session.cmd(service_cmd)
            else:
                utils.run(service_cmd)
        except error.CmdError, detail:
            raise LibvirtdActionError(action, detail)

    elif action == "status":
        cmd_result = utils.run(service_cmd, ignore_status=True)
        if cmd_result.exit_status:
            raise LibvirtdActionError(action, cmd_result.stderr)

        if re.search("running", cmd_result.stdout.strip()):
            return True
        else:
            return False
    else:
        raise LibvirtdActionUnknownError(action)


def libvirtd_restart(**dargs):
    """
    Restart libvirt daemon.
    """
    try:
        service_libvirtd_control('restart', **dargs)
        logging.debug("Restarted libvirtd successfuly")
    except LibvirtdActionError, detail:
        logging.debug("Failed to restart libvirtd:\n%s", detail)
        raise


def libvirtd_stop(**dargs):
    """
    Stop libvirt daemon.
    """
    try:
        service_libvirtd_control('stop', **dargs)
        logging.debug("Stop libvirtd successfuly")
    except LibvirtdActionError, detail:
        logging.debug("Failed to stop libvirtd:\n%s", detail)
        raise


def libvirtd_start(**dargs):
    """
    Start libvirt daemon.
    """
    try:
        service_libvirtd_control('start', **dargs)
        logging.debug("Start libvirtd successfuly")
    except LibvirtdActionError, detail:
        logging.debug("Failed to start libvirtd:\n%s", detail)
        raise


def libvirtd_status(**dargs):
    """
    Get the status of libvirt daemon.
    """
    try:
        return service_libvirtd_control('status', **dargs)
    except LibvirtdActionError, detail:
        logging.debug("Failed to get status of libvirtd:\n%s", detail)
        raise
