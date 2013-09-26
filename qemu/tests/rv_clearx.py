"""
This restarts the x server on all vms by killing gdm in order to eliminate any
side effects and running applications that might interfere with tests.
"""

import logging
from autotest.client.shared import error
from virttest.aexpect import ShellCmdError
from virttest import utils_misc


def is_pid_alive(session, pid):

    try:
        session.cmd("ps -p %s" % pid)
    except ShellCmdError:
        return False

    return True


def run_rv_clearx(test, params, env):
    for vm_name in params.get("vms").split():
        vm = env.get_vm(vm_name)
        logging.info("restarting X on: %s", vm_name)
        session = vm.wait_for_login(username="root", password="123456",
                                    timeout=int(params.get("login_timeout", 360)))
        pid = session.cmd("pgrep Xorg")
        session.cmd("killall Xorg")

        utils_misc.wait_for(lambda: is_pid_alive(session, pid), 10, 5, 0.2)

        try:
            session.cmd("ps -C Xorg")
        except:
            raise error.TestFail("X not running")
