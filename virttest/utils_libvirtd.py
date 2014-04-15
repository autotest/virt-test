"""
Module to control libvirtd service.
"""
import re
import logging
from virttest import aexpect

from virttest import remote, utils_misc
from autotest.client import utils, os_dep
from virttest.staging import service


try:
    os_dep.command("libvirtd")
    LIBVIRTD = "libvirtd"
except ValueError:
    LIBVIRTD = None


class Libvirtd(object):

    """
    Class to manage libvirtd service on host or guest.
    """

    def __init__(self, session=None):
        """
        Initialize an service object for libvirtd.

        :params session: An session to guest or remote host.
        """
        self.session = session

        if self.session:
            self.remote_runner = remote.RemoteRunner(session=self.session)
            runner = self.remote_runner.run
        else:
            runner = utils.run

        if LIBVIRTD is None:
            logging.warning("Libvirtd service is not available in host, "
                            "utils_libvirtd module will not function normally")
        self.libvirtd = service.Factory.create_service(LIBVIRTD, run=runner)

    def _wait_for_start(self, timeout=60):
        """
        Wait n seconds for libvirt to start. Default is 60 seconds.
        """
        def _check_start():
            virsh_cmd = "virsh list"
            try:
                if self.session:
                    self.session.cmd(virsh_cmd, timeout=2)
                else:
                    utils.run(virsh_cmd, timeout=2)
                return True
            except:
                return False
        return utils_misc.wait_for(_check_start, timeout=timeout)

    def start(self):
        # pylint: disable=E1103
        self.libvirtd.start()
        return self._wait_for_start()

    def stop(self):
        # pylint: disable=E1103
        self.libvirtd.stop()

    def restart(self):
        # pylint: disable=E1103
        self.libvirtd.restart()
        return self._wait_for_start()

    def is_running(self):
        # pylint: disable=E1103
        return self.libvirtd.status()


class LibvirtdSession(aexpect.Tail):
    """
    Class to generate a libvirtd process and handler all the logging info.
    """
    def _output_handler(self, line):
        """
        Output handler function triggered when new log line outputted.

        This handler separate handlers for both warnings and errors.

        :param line: Newly added logging line.
        """
        # Regex pattern to Match log time string like:
        # '2014-04-08 06:04:22.443+0000: 15122: '
        time_pattern = r'[-\d]+ [.:+\d]+ [:\d]+ '

        # Call `debug_func` if it's a debug log
        debug_pattern = time_pattern + 'debug :'
        result = re.match(debug_pattern, line)
        params = self.debug_params + (line,)
        if self.debug_func and result:
            self.debug_func(*params)

        # Call `info_func` if it's an info log
        info_pattern = time_pattern + 'info :'
        result = re.match(info_pattern, line)
        params = self.info_params + (line,)
        if self.info_func and result:
            self.info_func(*params)

        # Call `warning_func` if it's a warning log
        warning_pattern = time_pattern + 'warning :'
        result = re.match(warning_pattern, line)
        params = self.warning_params + (line,)
        if self.warning_func and result:
            self.warning_func(*params)

        # Call `error_func` if it's an error log
        error_pattern = time_pattern + 'error :'
        result = re.match(error_pattern, line)
        params = self.error_params + (line,)
        if self.error_func and result:
            self.error_func(*params)

    def _termination_handler(self, status):
        """
        Termination handler function triggered when libvirtd exited.

        This handler recover libvirtd service status.

        :param status: Return code of exited libvirtd session.
        """
        if self.was_running:
            logging.debug('Restarting libvirtd service')
            self.libvirtd.start()

    def _wait_for_start(self, timeout=60):
        """
        Wait 'timeout' seconds for libvirt to start.

        :param timeout: Maxinum time for the waiting.
        """
        def _check_start():
            """
            Check if libvirtd is start by return status of 'virsh list'
            """
            virsh_cmd = "virsh list"
            try:
                utils.run(virsh_cmd, timeout=2)
                return True
            except:
                return False
        return utils_misc.wait_for(_check_start, timeout=timeout)

    def __init__(self,
                 debug_func=None, debug_params=(),
                 info_func=None, info_params=(),
                 warning_func=None, warning_params=(),
                 error_func=None, error_params=(),
                 ):
        """
        Initialize a libvirt daemon process and monitor all the logging info.

        The corresponding callback function will be called if a logging line
        is found. The status of libvirtd service will be backed up and
        recovered after termination of this process.

        :param debug_func    : Callback function which will be called if a
                               debug message if found in libvirtd logging.
        :param debug_params  : Additional parameters to be passed to
                               'debug_func'.
        :param info_func     : Callback function which will be called if a
                               info message if found in libvirtd logging.
        :param info_params   : Additional parameters to be passed to
                               'info_func'.
        :param warning_func  : Callback function which will be called if a
                               warning message if found in libvirtd logging.
        :param warning_params: Additional parameters to be passed to
                               'warning_func'.
        :param error_func    : Callback function which will be called if a
                               error message if found in libvirtd logging.
        :param error_params  : Additional parameters to be passed to
                               'error_func'.
        """
        self.debug_func = debug_func
        self.debug_params = debug_params
        self.info_func = info_func
        self.info_params = info_params
        self.warning_func = warning_func
        self.warning_params = warning_params
        self.error_func = error_func
        self.error_params = error_params

        # Libvirtd service status will be backed up at first and
        # recovered after.
        self.libvirtd = Libvirtd()
        self.was_running = self.libvirtd.is_running()
        if self.was_running:
            logging.debug('Stopping libvirtd service')
            self.libvirtd.stop()
        aexpect.Tail.__init__(
            self, LIBVIRTD,
            output_func=self._output_handler,
            termination_func=self._termination_handler)
        self._wait_for_start()


def deprecation_warning():
    """
    As the utils_libvirtd.libvirtd_xxx interfaces are deprecated,
    this function are printing the warning to user.
    """
    logging.warning("This function was deprecated, Please use "
                    "class utils_libvirtd.Libvirtd to manage "
                    "libvirtd service.")


def libvirtd_start():
    libvirtd_instance = Libvirtd()
    deprecation_warning()
    return libvirtd_instance.start()


def libvirtd_is_running():
    libvirtd_instance = Libvirtd()
    deprecation_warning()
    return libvirtd_instance.is_running()


def libvirtd_stop():
    libvirtd_instance = Libvirtd()
    deprecation_warning()
    return libvirtd_instance.stop()


def libvirtd_restart():
    libvirtd_instance = Libvirtd()
    deprecation_warning()
    return libvirtd_instance.restart()


def service_libvirtd_control(action):
    libvirtd_instance = Libvirtd()
    deprecation_warning()
    getattr(libvirtd_instance, action)()
