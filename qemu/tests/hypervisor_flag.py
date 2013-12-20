"""
Sanity check for hypervisor flag in guest.
"""

import logging
from autotest.client.shared import error

def run(test, params, env):
    """
    Test if guest has 'hypervisor' flag in /proc/cpuinfo.

    1) Get a living VM
    2) Establish a remote session to it
    3) Grab information from /proc/cpuinfo
    4) Test if it has 'hypervisor' flag

    :param test: kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    cpuinfo = session.cmd("cat /proc/cpuinfo")
    logging.debug("Guest '/proc/cpuinfo': %s", cpuinfo)
    if "hypervisor" not in cpuinfo:
        raise error.TestFail("hypervisor flag undefined in cpuinfo")
