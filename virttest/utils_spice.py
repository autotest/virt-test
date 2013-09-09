"""
Common spice test utility functions.

"""
import os
import logging
import time
import sys
from autotest.client.shared import error
from aexpect import ShellCmdError, ShellStatusError, ShellTimeoutError


class RVConnectError(Exception):

    """Exception raised in case that remote-viewer fails to connect"""
    pass


def wait_timeout(timeout=10):
    """
    time.sleep(timeout) + logging.debug(timeout)

    @param timeout=10
    """
    logging.debug("Waiting (timeout=%ss)", timeout)
    time.sleep(timeout)


def verify_established(client_vm, host, port, rv_binary):
    """
    Parses netstat output for established connection on host:port
    @param client_session - vm.wait_for_login()
    @param host - host ip addr
    @param port - port for client to connect
    @param rv_binary - remote-viewer binary
    """
    rv_binary = rv_binary.split(os.path.sep)[-1]

    client_session = client_vm.wait_for_login(timeout=60)

    # !!! -n means do not resolve port names
    cmd = '(netstat -pn 2>&1| grep "^tcp.*:.*%s:%s.*ESTABLISHED.*%s.*") \
        > /dev/null' % (host, str(port), rv_binary)
    try:
        netstat_out = client_session.cmd(cmd)
        logging.info("netstat output: %s", netstat_out)

    except ShellCmdError:
        logging.error("Failed to get established connection from netstat")
        raise RVConnectError()

    else:
        logging.info("%s connection to %s:%s successful.",
                     rv_binary, host, port)
    client_session.close()


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


def get_vdagent_status(vm_session, test_timeout):
    """
    Return the status of vdagent
    @param vm_session:  ssh session of the VM
    @param test_timeout: timeout time for the cmd
    """
    output = ""
    cmd = "service spice-vdagentd status"

    wait_timeout(3)
    try:
        output = vm_session.cmd(
            cmd, print_func=logging.info, timeout=test_timeout)
    except ShellCmdError:
        # getting the status of vdagent stopped returns 3, which results in a
        # ShellCmdError
        return("stopped")
    except:
        print "Unexpected error:", sys.exc_info()[0]
        raise error.TestFail(
            "Failed attempting to get status of spice-vdagentd")
    wait_timeout(3)
    return(output)


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
