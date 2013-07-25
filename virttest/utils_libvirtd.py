"""
Module to control libvirtd service.
"""
import logging, re
from virttest import remote, aexpect
from autotest.client.shared import error, service
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
    Error in service command when service name is unkown.
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
    logging.warning("Libvirtd service is not availible in host, "
                    "utils_libvirtd module will not function normally")


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
                if action.find('-') != -1:
                    action = action.replace('-', '_')
                    extend_cmd_dict = {action:True}
                init_name = service.get_name_of_init()
                service.COMMANDS_SERVICE[init_name].update(extend_cmd_dict)
                libvirtd_service = service.SpecificServiceManager(libvirtd)
                eval("libvirtd_service.%s()" % action)
        except (error.CmdError, aexpect.ShellError), detail:
            raise LibvirtdActionError(action, detail)

    elif action == "status":
        if session:
            try:
                status, output = session.cmd_status_output(service_cmd)
            except aexpect.ShellError, detail:
                raise LibvirtdActionError(action, detail)
            if status:
                raise LibvirtdActionError(action, output)
        else:
            libvirtd_service = service.SpecificServiceManager(libvirtd)
            cmd_result = eval("libvirtd_service.%s(ignore_status=True)"
                              % action)
            if cmd_result.exit_status:
                raise LibvirtdActionError(action, cmd_result.stderr)
            output = cmd_result.stdout

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
        logging.debug("Restarted libvirtd successfuly")
        return True
    except LibvirtdActionError, detail:
        logging.debug("Failed to restart libvirtd:\n%s", detail)
        return False


def libvirtd_stop():
    """
    Stop libvirt daemon.
    """
    try:
        service_libvirtd_control('stop')
        logging.debug("Stop libvirtd successfuly")
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
        logging.debug("Start libvirtd successfuly")
        return True
    except LibvirtdActionError, detail:
        logging.debug("Failed to start libvirtd:\n%s", detail)
        return False


def libvirtd_force_reload():
    """
    Force-reload libvirt daemon.
    """
    try:
        service_libvirtd_control('force-reload')
        logging.debug("Force-reload libvirtd successfuly")
        return True
    except LibvirtdActionError, detail:
        logging.debug("Failed to force-reload libvirtd:\n%s", detail)
        return False


def libvirtd_try_restart():
    """
    Try-restart libvirt daemon.
    """
    try:
        service_libvirtd_control('try-restart')
        logging.debug("Try-restart libvirtd successfuly")
        return True
    except LibvirtdActionError, detail:
        logging.debug("Failed to try-restart libvirtd:\n%s", detail)
        return False


def libvirtd_is_running():
    """
    Check if libvirt service is running.
    """
    try:
        return service_libvirtd_control('status')
    except LibvirtdActionError, detail:
        logging.debug("Failed to get status of libvirtd:\n%s", detail)
        return False
