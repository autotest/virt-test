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


# Following functions are old style interfaces in utils_libvirt.
# When we reimplemenete this module with staging/service.py,
# usage of utils_libvirtd is changed. But we need to keep the
# old interface working still for the old version of tp-libvirt.
global_libvirtd = Libvirtd()


def deprecation_warning():
    """
    As the utils_libvirtd.libvirtd_xxx interfaces are deprecated,
    this function are printing the warning to user.
    """
    logging.warning("This function was deprecated, Please use "
                    "class utils_libvirtd.Libvirtd to manage "
                    "libvirtd service.")


def libvirtd_start():
    deprecation_warning()
    return global_libvirtd.start()


def libvirtd_is_running():
    deprecation_warning()
    return global_libvirtd.is_running()


def libvirtd_stop():
    deprecation_warning()
    return global_libvirtd.stop()


def libvirtd_restart():
    deprecation_warning()
    return global_libvirtd.restart()


def service_libvirtd_control(action):
    deprecation_warning()
    getattr(global_libvirtd, action)()
