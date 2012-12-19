"""
Common spice test utility functions.

"""
import logging, time
from autotest.client.shared import error
from aexpect import ShellCmdError, ShellStatusError, ShellTimeoutError


def wait_timeout(timeout=10):
    """
    time.sleep(timeout) + logging.debug(timeout)

    @param timeout=10
    """
    logging.debug("Waiting (timeout=%ss)", timeout)
    time.sleep(timeout)


def start_vdagent(guest_session, test_timeout):
    """
    Sending commands to start the spice-vdagentd service

    @param guest_session: ssh session of the VM
    @param test_timeout: timeout time for the cmds
    """
    cmd = "service spice-vdagentd start"
    try:
        guest_session.cmd(cmd, print_func=logging.info,
                                   timeout=test_timeout)
    except ShellStatusError:
        logging.debug("Status code of \"%s\" was not obtained, most likely"
                      "due to a problem with colored output" % cmd)
    except:
        raise error.TestFail("Guest Vdagent Daemon Start failed")

    logging.debug("------------ End of guest checking for Spice Vdagent"
                  " Daemon ------------")
    wait_timeout(3)


def restart_vdagent(guest_session, test_timeout):
    """
    Sending commands to restart the spice-vdagentd service

    @param guest_session: ssh session of the VM
    @param test_timeout: timeout time for the cmds
    """
    cmd = "service spice-vdagentd restart"
    try:
        guest_session.cmd(cmd, print_func=logging.info,
                                   timeout=test_timeout)
    except ShellCmdError:
        raise error.TestFail("Couldn't restart spice vdagent process")
    except:
        raise error.TestFail("Guest Vdagent Daemon Check failed")

    logging.debug("------------ End of Spice Vdagent"
                     " Daemon  Restart ------------")
    wait_timeout(3)


def stop_vdagent(guest_session, test_timeout):
    """
    Sending commands to stop the spice-vdagentd service

    @param guest_session: ssh session of the VM
    @param test_timeout: timeout time for the cmds
    """
    cmd = "service spice-vdagentd stop"
    try:
        guest_session.cmd(cmd, print_func=logging.info,
                                   timeout=test_timeout)
    except ShellStatusError:
        logging.debug("Status code of \"%s\" was not obtained, most likely"
                      "due to a problem with colored output" % cmd)
    except ShellCmdError:
        raise error.TestFail("Couldn't turn off spice vdagent process")
    except:
        raise error.TestFail("Guest Vdagent Daemon Check failed")

    logging.debug("------------ End of guest checking for Spice Vdagent"
                  " Daemon ------------")
    wait_timeout(3)


def verify_vdagent(guest_session, test_timeout):
    """
    Verifying vdagent is installed on a VM

    @param guest_session: ssh session of the VM
    @param test_timeout: timeout time for the cmds
    """
    cmd = "rpm -qa | grep spice-vdagent"

    try:
        guest_session.cmd(cmd, print_func=logging.info, timeout=test_timeout)
    finally:
        logging.debug("----------- End of guest check to see if vdagent package"
                     " is available ------------")
    wait_timeout(3)


def verify_virtio(guest_session, test_timeout):
    """
    Verify Virtio linux driver is properly loaded.

    @param guest_session: ssh session of the VM
    @param test_timeout: timeout time for the cmds
    """
    #cmd = "lsmod | grep virtio_console"
    cmd = "ls /dev/virtio-ports/"
    try:
        guest_session.cmd(cmd, print_func=logging.info, timeout=test_timeout)
    finally:
        logging.debug("------------ End of guest check of the Virtio-Serial"
                     " Driver------------")
    wait_timeout(3)

def launch_startx(vm):
    """
    Run startx on the VM

    @param guest_session: ssh session of the VM
    """
    vm_session = vm.wait_for_login(timeout=60)

    try:
        logging.info("Starting X server on the VM");
        vm_session.cmd("startx &", timeout=15)
    except (ShellCmdError, ShellStatusError, ShellTimeoutError):
        logging.debug("Ignoring an Exception that Occurs from calling startx")

    wait_timeout(15)
    vm_session.close()
