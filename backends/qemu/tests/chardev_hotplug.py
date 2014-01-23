import logging
import os
import fcntl
from autotest.client.shared import error
from autotest.client import utils


@error.context_aware
def run(test, params, env):
    """
    Test chardev hotplug.

    1) Log into the guest.
    2) Clear dmesg.
    3) Add a null chardev, remove it
    4) Add a file chardev by path, verify that it shows ok for guest os,
       pipe a message to it, verify that message made to host side.
    5) Add a file chardev by fd, verify that it shows ok for guest os,
       pipe a message to it, verify that message made to host side.
    5) Add a pty chardev, verify that it shows ok for guest os,
       pipe a message to it, verify that message made to host side.

    :param test: qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def cmd_qmp_log(vm, cmd, args):
        logging.debug("[qmp cmd %s] %s" % (cmd, args))
        reply = vm.monitor.cmd_qmp(cmd, args)
        logging.debug("[qmp reply] %s" % reply)
        if "error" in reply:
            if reply["error"]["class"] == "CommandNotFound":
                raise error.TestNAError("qmp command %s not supported" % cmd)
            else:
                raise error.TestFail("qmp error: %s" % reply["error"]["desc"])
        return reply

    def pci_serial_add(vm, name, addr, chardev):
        reply = cmd_qmp_log(vm, 'device_add', {'driver': 'pci-serial',
                                               'id': name,
                                               'addr': addr,
                                               'chardev': chardev})
        return reply

    def device_del(vm, name):
        reply = cmd_qmp_log(vm, 'device_del', {'id': name})
        return reply

    def chardev_add(vm, name, kind, args):
        backend = {'type': kind, 'data': args}
        reply = cmd_qmp_log(vm, 'chardev-add', {'id': name,
                                                'backend': backend})
        return reply

    def chardev_del(vm, name):
        reply = cmd_qmp_log(vm, 'chardev-remove', {'id': name})
        return reply

    def chardev_use(vm, name):
        addr = "18.0"

        # hotplug serial adapter
        pci_serial_add(vm, "test-serial", addr, name)
        session.cmd_status("sleep 1")
        session.cmd_status("udevadm settle")
        msg_add = session.cmd("dmesg -c | grep %s" % addr)
        for line in msg_add.splitlines():
            logging.debug("[dmesg add] %s" % line)
        lspci = session.cmd("lspci -vs %s" % addr)
        for line in lspci.splitlines():
            logging.debug("[lspci] %s" % line)

        # send message
        device = session.cmd("ls /sys/bus/pci/devices/*%s/tty" % addr)
        device = device.strip()
        logging.info("guest tty device is '%s'" % device)
        session.cmd("test -c /dev/%s" % device)
        session.cmd("echo 'Hello virttest world' > /dev/%s" % device)

        # unplug serial adapter
        device_del(vm, "test-serial")
        session.cmd_status("sleep 1")
        msg_del = session.cmd("dmesg -c")
        for line in msg_del.splitlines():
            logging.debug("[dmesg del] %s" % line)

    error.context("Log into guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    session.cmd_status("dmesg -c")

    error.context("Test null chardev", logging.info)
    chardev_add(vm, "chardev-null", "null", {})
    chardev_use(vm, "chardev-null")
    chardev_del(vm, "chardev-null")

    error.context("Test file chardev", logging.info)
    filename = "/tmp/chardev-file-%s" % vm.instance
    args = {'out': filename}
    chardev_add(vm, "chardev-file", "file", args)
    chardev_use(vm, "chardev-file")
    chardev_del(vm, "chardev-file")
    output = utils.system_output("cat %s" % filename)
    if output.find("Hello virttest world") == -1:
        raise error.TestFail("Guest message not found [%s]" % output)

    error.context("Test pty chardev", logging.info)
    reply = chardev_add(vm, "chardev-pty", "pty", {})
    filename = reply["return"]["pty"]
    logging.info("host pty device is '%s'" % filename)
    fd_dst = os.open(filename, os.O_RDWR | os.O_NONBLOCK)
    chardev_use(vm, "chardev-pty")
    output = os.read(fd_dst, 256)
    os.close(fd_dst)
    if output.find("Hello virttest world") == -1:
        raise error.TestFail("Guest message not found [%s]" % output)
    chardev_del(vm, "chardev-pty")

    error.context("Cleanup", logging.info)
    session.close()
