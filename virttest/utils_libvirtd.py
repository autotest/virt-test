"""
Module to control libvirtd service.
"""
import logging

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
        Wait n seconds for libvirt to start. Default is 10 seconds.
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


def service_libvirtd_control(action, remote_ip=None, remote_pwd=None,
                             remote_user='root'):
    deprecation_warning()
    session = None
    if remote_ip:
        session = remote.wait_for_login('ssh', remote_ip, '22',
                                        remote_user, remote_pwd,
                                        r"[\#\$]\s*$")
        libvirtd_instance = Libvirtd(session)
    else:
        libvirtd_instance = Libvirtd()

    getattr(libvirtd_instance, action)()
