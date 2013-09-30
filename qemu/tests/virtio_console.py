# TODO: Why VM recreation doesn't work?
"""
Collection of virtio_console and virtio_serialport tests.

:copyright: 2010-2012 Red Hat Inc.
"""
from collections import deque
import array
import logging
import os
import random
import select
import sys
import socket
import threading
import traceback
import time
from subprocess import Popen
from autotest.client import utils
from autotest.client.shared import error
from virttest import qemu_virtio_port, env_process, utils_test, utils_misc
from virttest import funcatexit


EXIT_EVENT = threading.Event()


def __set_exit_event():
    """
    Sets global EXIT_EVENT
    :note: Used in cleanup by funcatexit in some tests
    """
    logging.warn("Executing __set_exit_event()")
    EXIT_EVENT.set()


@error.context_aware
def run_virtio_console(test, params, env):
    """
    KVM virtio_console test

    This test contain multiple tests. The name of the executed test is set
    by 'virtio_console_test' cfg variable. Main function with the set name
    with prefix 'test_' thus it's easy to find out which functions are
    tests and which are helpers.

    Every test has it's own cfg parameters, please see the actual test's
    docstring for details.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    :raise error.TestNAError: if function with test_$testname is not present
    """
    #
    # General helpers
    #
    @error.context_aware
    def get_vm_with_ports(no_consoles=0, no_serialports=0, spread=None,
                          quiet=False, strict=False):
        """
        Checks whether existing 'main_vm' fits the requirements, modifies
        it if needed and returns the VM object.
        :param no_console: Number of desired virtconsoles.
        :param no_serialport: Number of desired virtserialports.
        :param spread: Spread consoles across multiple virtio-serial-pcis.
        :param quiet: Notify user about VM recreation.
        :param strict: Whether no_consoles have to match or just exceed.
        :return: vm object matching the requirements.
        """
        # check the number of running VM's consoles
        vm = env.get_vm(params["main_vm"])

        if not vm:
            _no_serialports = -1
            _no_consoles = -1
        else:
            _no_serialports = 0
            _no_consoles = 0
            for port in vm.virtio_ports:
                if isinstance(port, qemu_virtio_port.VirtioSerial):
                    _no_serialports += 1
                else:
                    _no_consoles += 1
        _spread = int(params.get('virtio_port_spread', 2))
        if spread is None:
            spread = _spread
        if strict:
            if (_no_serialports != no_serialports or
                    _no_consoles != no_consoles):
                _no_serialports = -1
                _no_consoles = -1
        # If not enough ports, modify params and recreate VM
        if (_no_serialports < no_serialports or _no_consoles < no_consoles
                or spread != _spread):
            if not quiet:
                out = "tests reqirements are different from cfg: "
                if _no_serialports < no_serialports:
                    out += "serial_ports(%d), " % no_serialports
                if _no_consoles < no_consoles:
                    out += "consoles(%d), " % no_consoles
                if spread != _spread:
                    out += "spread(%s), " % spread
                logging.warning(out[:-2] + ". Modify config to speedup tests.")

            params['virtio_ports'] = ""
            if spread:
                params['virtio_port_spread'] = spread
            else:
                params['virtio_port_spread'] = 0

            for i in xrange(max(no_consoles, _no_consoles)):
                name = "console-%d" % i
                params['virtio_ports'] += " %s" % name
                params['virtio_port_type_%s' % name] = "console"

            for i in xrange(max(no_serialports, _no_serialports)):
                name = "serialport-%d" % i
                params['virtio_ports'] += " %s" % name
                params['virtio_port_type_%s' % name] = "serialport"

            if quiet:
                logging.debug("Recreating VM with more virtio ports.")
            else:
                logging.warning("Recreating VM with more virtio ports.")
            env_process.preprocess_vm(test, params, env,
                                      params["main_vm"])
            vm = env.get_vm(params["main_vm"])

        vm.verify_kernel_crash()
        return vm

    @error.context_aware
    def get_vm_with_worker(no_consoles=0, no_serialports=0, spread=None,
                           quiet=False):
        """
        Checks whether existing 'main_vm' fits the requirements, modifies
        it if needed and returns the VM object and guest_worker.
        :param no_console: Number of desired virtconsoles.
        :param no_serialport: Number of desired virtserialports.
        :param spread: Spread consoles across multiple virtio-serial-pcis.
        :param quiet: Notify user about VM recreation.
        :param strict: Whether no_consoles have to match or just exceed.
        :return: tuple (vm object matching the requirements,
                        initialized GuestWorker of the vm)
        """
        vm = get_vm_with_ports(no_consoles, no_serialports, spread, quiet)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        return vm, guest_worker

    @error.context_aware
    def get_vm_with_single_port(port_type='serialport'):
        """
        Wrapper which returns vm, guest_worker and virtio_ports with at lest
        one port of the type specified by fction parameter.
        :param port_type: type of the desired virtio port.
        :return: tuple (vm object with at least 1 port of the port_type,
                        initialized GuestWorker of the vm,
                        list of virtio_ports of the port_type type)
        """
        if port_type == 'serialport':
            vm, guest_worker = get_vm_with_worker(no_serialports=1)
            virtio_ports = get_virtio_ports(vm)[1][0]
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=1)
            virtio_ports = get_virtio_ports(vm)[0][0]
        return vm, guest_worker, virtio_ports

    @error.context_aware
    def get_virtio_ports(vm):
        """
        Returns separated virtconsoles and virtserialports
        :param vm: VM object
        :return: tuple (all virtconsoles, all virtserialports)
        """
        consoles = []
        serialports = []
        for port in vm.virtio_ports:
            if isinstance(port, qemu_virtio_port.VirtioSerial):
                serialports.append(port)
            else:
                consoles.append(port)
        return (consoles, serialports)

    @error.context_aware
    def cleanup(vm=None, guest_worker=None):
        """
        Cleanup function.
        :param vm: VM whose ports should be cleaned
        :param guest_worker: guest_worker which should be cleaned/exited
        """
        error.context("Cleaning virtio_ports on guest.")
        if guest_worker:
            guest_worker.cleanup()
        error.context("Cleaning virtio_ports on host.")
        if vm:
            for port in vm.virtio_ports:
                port.clean_port()
                port.close()
                port.mark_as_clean()

    #
    # Smoke tests
    #
    @error.context_aware
    def test_open():
        """
        Try to open virtioconsole port.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        guest_worker.cmd("virt.open('%s')" % (port.name))
        port.open()
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_check_zero_sym():
        """
        Check if port /dev/vport0p0 was created.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        if params.get('virtio_console_params') == 'serialport':
            vm, guest_worker = get_vm_with_worker(no_serialports=1)
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=1)
        guest_worker.cmd("virt.check_zero_sym()", 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_multi_open():
        """
        Try to open the same port twice.
        :note: On linux it should pass with virtconsole and fail with
               virtserialport. On Windows booth should fail
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        guest_worker.cmd("virt.close('%s')" % (port.name), 10)
        guest_worker.cmd("virt.open('%s')" % (port.name), 10)
        (match, data) = guest_worker._cmd("virt.open('%s')" % (port.name), 10)
        # Console on linux is permitted to open the device multiple times
        if port.is_console == "yes" and guest_worker.os_linux:
            if match != 0:  # Multiple open didn't pass
                raise error.TestFail("Unexpected fail of opening the console"
                                     " device for the 2nd time.\n%s" % data)
        else:
            if match != 1:  # Multiple open didn't fail:
                raise error.TestFail("Unexpended pass of opening the"
                                     " serialport device for the 2nd time.")
        port.open()
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_close():
        """
        Close the socket on the guest side
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        guest_worker.cmd("virt.close('%s')" % (port.name), 10)
        port.close()
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_polling():
        """
        Test correct results of poll with different cases.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        # Poll (OUT)
        port.open()
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLOUT),
                         2)

        # Poll (IN, OUT)
        port.sock.sendall("test")
        for test in [select.POLLIN, select.POLLOUT]:
            guest_worker.cmd("virt.poll('%s', %s)" % (port.name, test), 10)

        # Poll (IN HUP)
        # I store the socket informations and close the socket
        port.close()
        for test in [select.POLLIN, select.POLLHUP]:
            guest_worker.cmd("virt.poll('%s', %s)" % (port.name, test), 10)

        # Poll (HUP)
        guest_worker.cmd("virt.recv('%s', 4, 1024, False)" % (port.name), 10)
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLHUP),
                         2)

        # Reconnect the socket
        port.open()
        # Redefine socket in consoles
        guest_worker.cmd("virt.poll('%s', %s)" % (port.name, select.POLLOUT),
                         2)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_sigio():
        """
        Test whether virtio port generates sigio signals correctly.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        if port.is_open():
            port.close()

        # Enable sigio on specific port
        guest_worker.cmd("virt.async('%s', True, 0)" % (port.name), 10)
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test sigio when port open
        guest_worker.cmd("virt.set_pool_want_return('%s', select.POLLOUT)" %
                         (port.name), 10)
        port.open()
        match = guest_worker._cmd("virt.get_sigio_poll_return('%s')" %
                                  (port.name), 10)[0]
        if match == 1:
            raise error.TestFail("Problem with HUP on console port.")

        # Test sigio when port receive data
        guest_worker.cmd("virt.set_pool_want_return('%s', select.POLLOUT |"
                         " select.POLLIN)" % (port.name), 10)
        port.sock.sendall("0123456789")
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test sigio port close event
        guest_worker.cmd("virt.set_pool_want_return('%s', select.POLLHUP |"
                         " select.POLLIN)" % (port.name), 10)
        port.close()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test sigio port open event and persistence of written data on port.
        guest_worker.cmd("virt.set_pool_want_return('%s', select.POLLOUT |"
                         " select.POLLIN)" % (port.name), 10)
        port.open()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Test event when erase data.
        guest_worker.cmd("virt.clean_port('%s')" % (port.name), 10)
        port.close()
        guest_worker.cmd("virt.set_pool_want_return('%s', select.POLLOUT)"
                         % (port.name), 10)
        port.open()
        guest_worker.cmd("virt.get_sigio_poll_return('%s')" % (port.name), 10)

        # Disable sigio on specific port
        guest_worker.cmd("virt.async('%s', False, 0)" % (port.name), 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_lseek():
        """
        Tests the correct handling of lseek
        :note: lseek should fail
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # The virt.lseek returns PASS when the seek fails
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        guest_worker.cmd("virt.lseek('%s', 0, 0)" % (port.name), 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_rw_host_offline():
        """
        Try to read from/write to host on guest when host is disconnected.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        if port.is_open():
            port.close()

        guest_worker.cmd("virt.recv('%s', 0, 1024, False)" % port.name, 10)
        match, tmp = guest_worker._cmd("virt.send('%s', 10, True)" % port.name,
                                       10)
        if match is not None:
            raise error.TestFail("Write on guest while host disconnected "
                                 "didn't time out.\nOutput:\n%s"
                                 % tmp)

        port.open()

        if (port.sock.recv(1024) < 10):
            raise error.TestFail("Didn't received data from guest")
        # Now the cmd("virt.send('%s'... command should be finished
        guest_worker.cmd("print('PASS: nothing')", 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_rw_host_offline_big_data():
        """
        Try to read from/write to host on guest when host is disconnected
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        if port.is_open():
            port.close()

        port.clean_port()
        port.close()
        guest_worker.cmd("virt.clean_port('%s'),1024" % port.name, 10)
        match, tmp = guest_worker._cmd("virt.send('%s', (1024**3)*3, True, "
                                       "is_static=True)" % port.name, 30)
        if match is None:
            raise error.TestFail("Write on guest while host disconnected "
                                 "didn't time out.\nOutput:\n%s"
                                 % tmp)

        time.sleep(20)

        port.open()

        rlen = 0
        while rlen < (1024 ** 3 * 3):
            ret = select.select([port.sock], [], [], 10.0)
            if (ret[0] != []):
                rlen += len(port.sock.recv(((4096))))
            elif rlen != (1024 ** 3 * 3):
                raise error.TestFail("Not all data was received,"
                                     "only %d from %d" % (rlen, 1024 ** 3 * 3))
        guest_worker.cmd("print('PASS: nothing')", 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_rw_blocking_mode():
        """
        Try to read/write data in blocking mode.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # Blocking mode
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        port.open()
        guest_worker.cmd("virt.blocking('%s', True)" % port.name, 10)
        # Recv should timed out
        match, tmp = guest_worker._cmd("virt.recv('%s', 10, 1024, False)" %
                                       port.name, 10)
        if match == 0:
            raise error.TestFail("Received data even when none was sent\n"
                                 "Data:\n%s" % tmp)
        elif match is not None:
            raise error.TestFail("Unexpected fail\nMatch: %s\nData:\n%s" %
                                 (match, tmp))
        port.sock.sendall("1234567890")
        # Now guest received the data end escaped from the recv()
        guest_worker.cmd("print('PASS: nothing')", 10)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_rw_nonblocking_mode():
        """
        Try to read/write data in non-blocking mode.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # Non-blocking mode
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        port.open()
        guest_worker.cmd("virt.blocking('%s', False)" % port.name, 10)
        # Recv should return FAIL with 0 received data
        match, tmp = guest_worker._cmd("virt.recv('%s', 10, 1024, False)" %
                                       port.name, 10)
        if match == 0:
            raise error.TestFail("Received data even when none was sent\n"
                                 "Data:\n%s" % tmp)
        elif match is None:
            raise error.TestFail("Timed out, probably in blocking mode\n"
                                 "Data:\n%s" % tmp)
        elif match != 1:
            raise error.TestFail("Unexpected fail\nMatch: %s\nData:\n%s" %
                                 (match, tmp))
        port.sock.sendall("1234567890")
        time.sleep(0.01)
        try:
            guest_worker.cmd("virt.recv('%s', 10, 1024, False)"
                             % port.name, 10)
        except qemu_virtio_port.VirtioPortException, details:
            if '[Errno 11] Resource temporarily unavailable' in details:
                # Give the VM second chance
                time.sleep(0.01)
                guest_worker.cmd("virt.recv('%s', 10, 1024, False)"
                                 % port.name, 10)
            else:
                raise details
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_basic_loopback():
        """
        Simple loop back test with loop over two ports.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        if params.get('virtio_console_params') == 'serialport':
            vm, guest_worker = get_vm_with_worker(no_serialports=2)
            send_port, recv_port = get_virtio_ports(vm)[1][:2]
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=2)
            send_port, recv_port = get_virtio_ports(vm)[0][:2]

        data = "Smoke test data"
        send_port.open()
        recv_port.open()
        # Set nonblocking mode
        send_port.sock.setblocking(0)
        recv_port.sock.setblocking(0)
        guest_worker.cmd("virt.loopback(['%s'], ['%s'], 1024, virt.LOOP_NONE)"
                         % (send_port.name, recv_port.name), 10)
        send_port.sock.sendall(data)
        tmp = ""
        i = 0
        while i <= 10:
            i += 1
            ret = select.select([recv_port.sock], [], [], 1.0)
            if ret:
                try:
                    tmp += recv_port.sock.recv(1024)
                except IOError, failure_detail:
                    logging.warn("Got err while recv: %s", failure_detail)
            if len(tmp) >= len(data):
                break
        if tmp != data:
            raise error.TestFail("Incorrect data: '%s' != '%s'"
                                 % (data, tmp))
        guest_worker.safe_exit_loopback_threads([send_port], [recv_port])
        cleanup(vm, guest_worker)

    #
    # Loopback tests
    #
    @error.context_aware
    def test_loopback():
        """
        Virtio console loopback test.

        Creates loopback on the vm machine between send_pt and recv_pts
        ports and sends length amount of data through this connection.
        It validates the correctness of the sent data.
        :param cfg: virtio_console_params - semicolon separated loopback
                        scenarios, only $source_console_type and (multiple)
                        destination_console_types are mandatory.
                            '$source_console_type@buffer_length:
                             $destination_console_type1@$buffer_length:...:
                             $loopback_buffer_length;...'
        :param cfg: virtio_console_test_time - how long to send the data
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        # PREPARE
        test_params = params['virtio_console_params']
        test_time = int(params.get('virtio_console_test_time', 60))
        no_serialports = 0
        no_consoles = 0
        for param in test_params.split(';'):
            no_serialports = max(no_serialports, param.count('serialport'))
            no_consoles = max(no_consoles, param.count('console'))
        vm, guest_worker = get_vm_with_worker(no_consoles, no_serialports)
        no_errors = 0

        (consoles, serialports) = get_virtio_ports(vm)

        for param in test_params.split(';'):
            if not param:
                continue
            error.context("test_loopback: params %s" % param, logging.info)
            # Prepare
            param = param.split(':')
            idx_serialport = 0
            idx_console = 0
            buf_len = []
            if (param[0].startswith('console')):
                send_pt = consoles[idx_console]
                idx_console += 1
            else:
                send_pt = serialports[idx_serialport]
                idx_serialport += 1
            if (len(param[0].split('@')) == 2):
                buf_len.append(int(param[0].split('@')[1]))
            else:
                buf_len.append(1024)
            recv_pts = []
            for parm in param[1:]:
                if (parm.isdigit()):
                    buf_len.append(int(parm))
                    break   # buf_len is the last portion of param
                if (parm.startswith('console')):
                    recv_pts.append(consoles[idx_console])
                    idx_console += 1
                else:
                    recv_pts.append(serialports[idx_serialport])
                    idx_serialport += 1
                if (len(parm[0].split('@')) == 2):
                    buf_len.append(int(parm[0].split('@')[1]))
                else:
                    buf_len.append(1024)
            # There must be sum(idx_*) consoles + last item as loopback buf_len
            if len(buf_len) == (idx_console + idx_serialport):
                buf_len.append(1024)

            for port in recv_pts:
                port.open()

            send_pt.open()

            if len(recv_pts) == 0:
                raise error.TestFail("test_loopback: incorrect recv consoles"
                                     "definition")

            threads = []
            queues = []
            for i in range(0, len(recv_pts)):
                queues.append(deque())

            # Start loopback
            tmp = "'%s'" % recv_pts[0].name
            for recv_pt in recv_pts[1:]:
                tmp += ", '%s'" % (recv_pt.name)
            guest_worker.cmd("virt.loopback(['%s'], [%s], %d, virt.LOOP_POLL)"
                             % (send_pt.name, tmp, buf_len[-1]), 10)

            global EXIT_EVENT
            funcatexit.register(env, params.get('type'), __set_exit_event)

            # TEST
            thread = qemu_virtio_port.ThSendCheck(send_pt, EXIT_EVENT, queues,
                                                  buf_len[0])
            thread.start()
            threads.append(thread)

            for i in range(len(recv_pts)):
                thread = qemu_virtio_port.ThRecvCheck(recv_pts[i], queues[i],
                                                      EXIT_EVENT,
                                                      buf_len[i + 1])
                thread.start()
                threads.append(thread)

            err = ""
            end_time = time.time() + test_time
            no_threads = len(threads)
            transferred = [0] * no_threads
            while end_time > time.time():
                if not vm.is_alive():
                    err += "main(vmdied), "
                _transfered = []
                for i in xrange(no_threads):
                    if not threads[i].isAlive():
                        err += "main(th%s died), " % threads[i]
                    _transfered.append(threads[i].idx)
                if (_transfered == transferred and
                   transferred != [0] * no_threads):
                    err += "main(no_data), "
                transferred = _transfered
                if err:
                    logging.error("Error occurred while executing loopback "
                                  "(%d out of %ds)",
                                  test_time - int(end_time - time.time()),
                                  test_time)
                    break
                time.sleep(1)

            EXIT_EVENT.set()
            funcatexit.unregister(env, params.get('type'), __set_exit_event)
            # TEST END
            workaround_unfinished_threads = False
            logging.debug('Joining %s', threads[0])
            threads[0].join(5)
            if threads[0].isAlive():
                logging.error('Send thread stuck, destroing the VM and '
                              'stopping loopback test to prevent autotest '
                              'freeze.')
                vm.destroy()
                break
            if threads[0].ret_code:
                err += "%s, " % threads[0]
            tmp = "%d data sent; " % threads[0].idx
            for thread in threads[1:]:
                logging.debug('Joining %s', thread)
                thread.join(5)
                if thread.isAlive():
                    workaround_unfinished_threads = True
                    logging.debug("Unable to destroy the thread %s", thread)
                tmp += "%d, " % thread.idx
                if thread.ret_code:
                    err += "%s, " % thread
            logging.info("test_loopback: %s data received and verified",
                         tmp[:-2])
            if err:
                no_errors += 1
                logging.error("test_loopback: error occurred in threads: %s.",
                              err[:-2])

            guest_worker.safe_exit_loopback_threads([send_pt], recv_pts)

            for thread in threads:
                if thread.isAlive():
                    vm.destroy()
                    del threads[:]
                    raise error.TestError("Not all threads finished.")
            if workaround_unfinished_threads:
                logging.debug("All threads finished at this point.")
            del threads[:]
            if not vm.is_alive():
                raise error.TestFail("VM died, can't continue the test loop. "
                                     "Please check the log for details.")

        cleanup(vm, guest_worker)
        if no_errors:
            msg = ("test_loopback: %d errors occurred while executing test, "
                   "check log for details." % no_errors)
            logging.error(msg)
            raise error.TestFail(msg)

    @error.context_aware
    def test_interrupted_transfer():
        """
        This test creates loopback between 2 ports and interrupts transfer
        eg. by stopping the machine or by unplugging of the port.
        """
        def _stop_cont():
            """ Stop and resume VM """
            vm.pause()
            time.sleep(intr_time)
            vm.resume()

        def _disconnect():
            """ Disconnect and reconnect the port """
            _guest = random.choice((tuple(), (0,), (1,), (0, 1)))
            _host = random.choice((tuple(), (0,), (1,), (0, 1)))
            if not _guest and not _host:    # Close at least one port
                _guest = (0,)
            logging.debug('closing ports %s on host, %s on guest', _host,
                          _guest)
            for i in _host:
                threads[i].migrate_event.clear()
                logging.debug('Closing port %s on host', i)
                ports[i].close()
            for i in _guest:
                guest_worker.cmd("virt.close('%s')" % (ports[i].name), 10)
            time.sleep(intr_time)
            for i in _host:
                logging.debug('Opening port %s on host', i)
                ports[i].open()
                threads[i].migrate_event.set()
            for i in _guest:
                # 50 attemps per 0.1s
                guest_worker.cmd("virt.open('%s', attempts=50)"
                                 % (ports[i].name), 10)

        def _port_replug(device, port_idx):
            """ Unplug and replug port with the same name """
            # FIXME: In Linux vport*p* are used. Those numbers are changing
            # when replugging port from pci to different pci. We should
            # either use symlinks (as in Windows) or replug with the busname
            port = ports[port_idx]
            vm.monitor.cmd('device_del %s' % port.qemu_id)
            time.sleep(intr_time)
            vm.monitor.cmd('device_add %s,id=%s,chardev=dev%s,name=%s'
                           % (device, port.qemu_id, port.qemu_id, port.name))

        def _serialport_send_replug():
            """ hepler for executing replug of the sender port """
            _port_replug('virtserialport', 0)

        def _console_send_replug():
            """ hepler for executing replug of the sender port """
            _port_replug('virtconsole', 0)

        def _serialport_recv_replug():
            """ hepler for executing replug of the receiver port """
            _port_replug('virtserialport', 1)

        def _console_recv_replug():
            """ hepler for executing replug of the receiver port """
            _port_replug('virtconsole', 1)

        def _serialport_random_replug():
            """ hepler for executing replug of random port """
            _port_replug('virtserialport', random.choice((0, 1)))

        def _console_random_replug():
            """ hepler for executing replug of random port """
            _port_replug('virtconsole', random.choice((0, 1)))

        def _s3():
            """
            Suspend to mem (S3) and resume the VM.
            """
            session.sendline(set_s3_cmd)
            time.sleep(intr_time)
            if not vm.monitor.verify_status('suspended'):
                logging.debug('VM not yet suspended, periodic check started.')
                while not vm.monitor.verify_status('suspended'):
                    pass
            vm.monitor.cmd('system_wakeup')

        def _s4():
            """
            Hibernate (S4) and resume the VM.
            :note: data loss is handled differently in this case. First we
                   set data loss to (almost) infinity. After the resume we
                   periodically check the number of transferred and lost data.
                   When there is no loss and number of transferred data is
                   sufficient, we take it as the initial data loss is over.
                   Than we set the allowed loss to 0.
            """
            set_s4_cmd = params['set_s4_cmd']
            _loss = threads[1].sendidx
            _count = threads[1].idx
            # Prepare, hibernate and wake the machine
            threads[0].migrate_event.clear()
            threads[1].migrate_event.clear()
            oldport = vm.virtio_ports[0]
            portslen = len(vm.virtio_ports)
            vm.wait_for_login().sendline(set_s4_cmd)
            suspend_timeout = 240 + int(params.get("smp", 1)) * 60
            if not utils_misc.wait_for(vm.is_dead, suspend_timeout, 2, 2):
                raise error.TestFail("VM refuses to go down. Suspend failed.")
            time.sleep(intr_time)
            vm.create()
            for _ in xrange(10):    # Wait until new ports are created
                try:
                    if (vm.virtio_ports[0] != oldport and
                            len(vm.virtio_ports) == portslen):
                        break
                except IndexError:
                    pass
                time.sleep(1)
            else:
                raise error.TestFail("New virtio_ports were not created with"
                                     "the new VM or the VM failed to start.")
            if is_serialport:
                ports = get_virtio_ports(vm)[1]
            else:
                ports = get_virtio_ports(vm)[0]
            threads[0].port = ports[0]
            threads[1].port = ports[1]
            threads[0].migrate_event.set()  # Wake up sender thread immediately
            threads[1].migrate_event.set()
            guest_worker.reconnect(vm, 30)
            logging.debug("S4: watch 1s for initial data loss stabilization.")
            for _ in xrange(10):
                time.sleep(0.1)
                loss = threads[1].sendidx
                count = threads[1].idx
                dloss = _loss - loss
                dcount = count - _count
                logging.debug("loss=%s, verified=%s", dloss, dcount)
                if dcount < 100:
                    continue
                if dloss == 0:
                    # at least 100 chars were transferred without data loss
                    # the initial loss is over
                    break
                _loss = loss
                _count = count
            else:
                raise error.TestFail("Initial data loss is not over after 1s "
                                     "or no new data were received.")
            # now no loss is allowed
            threads[1].sendidx = 0
            # DEBUG: When using ThRecv debug, you must wake-up the recv thread
            # here (it waits only 1s for new data
            # threads[1].migrate_event.set()

        error.context("Preparing loopback")
        test_time = float(params.get('virtio_console_test_time', 10))
        intr_time = float(params.get('virtio_console_intr_time', 0))
        no_repeats = int(params.get('virtio_console_no_repeats', 1))
        interruption = params['virtio_console_interruption']
        is_serialport = (params.get('virtio_console_params') == 'serialport')
        buflen = int(params.get('virtio_console_buflen', 1))
        if is_serialport:
            vm, guest_worker = get_vm_with_worker(no_serialports=2)
            (_, ports) = get_virtio_ports(vm)
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=2)
            (ports, _) = get_virtio_ports(vm)

        # Set the interruption function and related variables
        send_resume_ev = None
        recv_resume_ev = None
        acceptable_loss = 0
        if interruption == 'stop':
            interruption = _stop_cont
        elif interruption == 'disconnect':
            interruption = _disconnect
            acceptable_loss = 100000
            send_resume_ev = threading.Event()
            recv_resume_ev = threading.Event()
        elif interruption == 'replug_send':
            if is_serialport:
                interruption = _serialport_send_replug
            else:
                interruption = _console_send_replug
            acceptable_loss = max(buflen * 10, 1000)
        elif interruption == 'replug_recv':
            if is_serialport:
                interruption = _serialport_recv_replug
            else:
                interruption = _console_recv_replug
            acceptable_loss = max(buflen * 5, 1000)
        elif interruption == 'replug_random':
            if is_serialport:
                interruption = _serialport_random_replug
            else:
                interruption = _console_random_replug
            acceptable_loss = max(buflen * 10, 1000)
        elif interruption == 's3':
            interruption = _s3
            acceptable_loss = 2000
            session = vm.wait_for_login()
            set_s3_cmd = params['set_s3_cmd']
            if session.cmd_status(params["check_s3_support_cmd"]):
                raise error.TestNAError("Suspend to mem (S3) not supported.")
        elif interruption == 's4':
            interruption = _s4
            session = vm.wait_for_login()
            if session.cmd_status(params["check_s4_support_cmd"]):
                raise error.TestNAError("Suspend to disk (S4) not supported.")
            acceptable_loss = 99999999      # loss is set in S4 rutine
            send_resume_ev = threading.Event()
            recv_resume_ev = threading.Event()
        else:
            raise error.TestNAError("virtio_console_interruption = '%s' "
                                    "is unknown." % interruption)

        send_pt = ports[0]
        recv_pt = ports[1]

        recv_pt.open()
        send_pt.open()

        threads = []
        queues = [deque()]

        # Start loopback
        error.context("Starting loopback", logging.info)
        err = ""
        # TODO: Use normal LOOP_NONE when bz796048 is resolved.
        guest_worker.cmd("virt.loopback(['%s'], ['%s'], %s, virt.LOOP_"
                         "RECONNECT_NONE)"
                         % (send_pt.name, recv_pt.name, buflen), 10)

        funcatexit.register(env, params.get('type'), __set_exit_event)

        threads.append(
            qemu_virtio_port.ThSendCheck(send_pt, EXIT_EVENT, queues,
                                         buflen, send_resume_ev))
        threads[-1].start()
        _ = params.get('virtio_console_debug')
        threads.append(qemu_virtio_port.ThRecvCheck(recv_pt, queues[0],
                                                    EXIT_EVENT, buflen,
                                                    acceptable_loss,
                                                    recv_resume_ev,
                                                    debug=_))
        threads[-1].start()

        logging.info('Starting the loop 2+%d*(%d+%d+intr_overhead)+2 >= %ss',
                     no_repeats, intr_time, test_time,
                     (4 + no_repeats * (intr_time + test_time)))
        # Lets transfer some data before the interruption
        time.sleep(2)
        if not threads[0].isAlive():
            raise error.TestFail("Sender thread died before interruption.")
        if not threads[0].isAlive():
            raise error.TestFail("Receiver thread died before interruption.")

        # 0s interruption without any measurements
        if params.get('virtio_console_micro_repeats'):
            error.context("Micro interruptions", logging.info)
            threads[1].sendidx = acceptable_loss
            for i in xrange(int(params.get('virtio_console_micro_repeats'))):
                interruption()

        error.context("Normal interruptions", logging.info)
        try:
            for i in xrange(no_repeats):
                error.context("Interruption nr. %s" % i)
                threads[1].sendidx = acceptable_loss
                interruption()
                count = threads[1].idx
                logging.debug('Transfered data: %s', count)
                # Be friendly to very short test_time values
                for _ in xrange(10):
                    time.sleep(test_time)
                    logging.debug('Transfered data2: %s', threads[1].idx)
                    if count == threads[1].idx and threads[1].isAlive():
                        logging.warn('No data received after %ds, extending '
                                     'test_time', test_time)
                    else:
                        break
                threads[1].reload_loss_idx()
                if count == threads[1].idx or not threads[1].isAlive():
                    if not threads[1].isAlive():
                        logging.error('RecvCheck thread stopped unexpectedly.')
                    if count == threads[1].idx:
                        logging.error(
                            'No data transferred after interruption!')
                    logging.info('Output from GuestWorker:\n%s',
                                 guest_worker.read_nonblocking())
                    try:
                        session = vm.login()
                        data = session.cmd_output('dmesg')
                        if 'WARNING:' in data:
                            logging.warning('There are warnings in dmesg:\n%s',
                                            data)
                    except Exception, inst:
                        logging.warn("Can't verify dmesg: %s", inst)
                    try:
                        vm.monitor.info('qtree')
                    except Exception, inst:
                        logging.warn("Failed to get info from qtree: %s", inst)
                    EXIT_EVENT.set()
                    vm.verify_kernel_crash()
                    raise error.TestFail('No data transferred after'
                                         'interruption.')
        except Exception, inst:
            err = "main thread, "
            logging.error('interrupted_loopback failed with exception: %s',
                          inst)

        error.context("Stopping loopback", logging.info)
        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get('type'), __set_exit_event)
        workaround_unfinished_threads = False
        threads[0].join(5)
        if threads[0].isAlive():
            workaround_unfinished_threads = True
            logging.error('Send thread stuck, destroing the VM and '
                          'stopping loopback test to prevent autotest freeze.')
            vm.destroy()
        for thread in threads[1:]:
            logging.debug('Joining %s', thread)
            thread.join(5)
            if thread.isAlive():
                workaround_unfinished_threads = True
                logging.debug("Unable to destroy the thread %s", thread)
        if not err:     # Show only on success
            logging.info('%d data sent; %d data received and verified; %d '
                         'interruptions %ds each.', threads[0].idx,
                         threads[1].idx, no_repeats, test_time)
        if threads[0].ret_code:
            err += "sender, "
        if threads[1].ret_code:
            err += "receiver, "

        # Ports might change (in suspend S4)
        if is_serialport:
            (send_pt, recv_pt) = get_virtio_ports(vm)[1][:2]
        else:
            (send_pt, recv_pt) = get_virtio_ports(vm)[0][:2]

        # VM might be recreated se we have to reconnect.
        guest_worker.safe_exit_loopback_threads([send_pt], [recv_pt])

        for thread in threads:
            if thread.isAlive():
                vm.destroy()
                del threads[:]
                raise error.TestError("Not all threads finished.")
        if workaround_unfinished_threads:
            logging.debug("All threads finished at this point.")

        del threads[:]

        cleanup(env.get_vm(params["main_vm"]), guest_worker)

        if err:
            raise error.TestFail("%s failed" % err[:-2])

    @error.context_aware
    def _process_stats(stats, scale=1.0):
        """
        Process the stats to human readable form.
        :param stats: List of measured data.
        """
        if not stats:
            return None
        for i in range((len(stats) - 1), 0, -1):
            stats[i] = stats[i] - stats[i - 1]
            stats[i] /= scale
        stats[0] /= scale
        stats = sorted(stats)
        return stats

    @error.context_aware
    def test_perf():
        """
        Tests performance of the virtio_console tunnel. First it sends the data
        from host to guest and than back. It provides informations about
        computer utilization and statistic informations about the throughput.

        :param cfg: virtio_console_params - semicolon separated scenarios:
                        '$console_type@$buffer_length:$test_duration;...'
        :param cfg: virtio_console_test_time - default test_duration time
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        test_params = params['virtio_console_params']
        test_time = int(params.get('virtio_console_test_time', 60))
        no_serialports = 0
        no_consoles = 0
        if test_params.count('serialport'):
            no_serialports = 1
        if test_params.count('serialport'):
            no_consoles = 1
        vm, guest_worker = get_vm_with_worker(no_consoles, no_serialports)
        (consoles, serialports) = get_virtio_ports(vm)
        consoles = [consoles, serialports]
        no_errors = 0

        for param in test_params.split(';'):
            if not param:
                continue
            error.context("test_perf: params %s" % param, logging.info)
            # Prepare
            param = param.split(':')
            duration = test_time
            if len(param) > 1:
                try:
                    duration = float(param[1])
                except ValueError:
                    pass
            param = param[0].split('@')
            if len(param) > 1 and param[1].isdigit():
                buf_len = int(param[1])
            else:
                buf_len = 1024
            param = (param[0] == 'serialport')
            port = consoles[param][0]

            port.open()

            data = ""
            for _ in range(buf_len):
                data += "%c" % random.randrange(255)

            funcatexit.register(env, params.get('type'), __set_exit_event)

            time_slice = float(duration) / 100

            # HOST -> GUEST
            guest_worker.cmd('virt.loopback(["%s"], [], %d, virt.LOOP_NONE)'
                             % (port.name, buf_len), 10)
            thread = qemu_virtio_port.ThSend(port.sock, data, EXIT_EVENT)
            stats = array.array('f', [])
            loads = utils.SystemLoad([(os.getpid(), 'autotest'),
                                      (vm.get_pid(), 'VM'), 0])
            try:
                loads.start()
                _time = time.time()
                thread.start()
                for _ in range(100):
                    stats.append(thread.idx)
                    time.sleep(time_slice)
                _time = time.time() - _time - duration
                logging.info("\n" + loads.get_cpu_status_string()[:-1])
                logging.info("\n" + loads.get_mem_status_string()[:-1])
                EXIT_EVENT.set()
                thread.join()
                if thread.ret_code:
                    no_errors += 1
                    logging.error("test_perf: error occurred in thread %s",
                                  thread)

                # Let the guest read-out all the remaining data
                while not guest_worker._cmd("virt.poll('%s', %s)"
                                            % (port.name, select.POLLIN),
                                            10)[0]:
                    time.sleep(1)

                guest_worker.safe_exit_loopback_threads([port], [])

                if (_time > time_slice):
                    logging.error("Test ran %fs longer which is more than one "
                                  "time slice", _time)
                else:
                    logging.debug("Test ran %fs longer", _time)
                stats = _process_stats(stats[1:], time_slice * 1048576)
                logging.debug("Stats = %s", stats)
                logging.info("Host -> Guest [MB/s] (min/med/max) = %.3f/%.3f/"
                             "%.3f", stats[0], stats[len(stats) / 2],
                             stats[-1])

                del thread

                # GUEST -> HOST
                EXIT_EVENT.clear()
                stats = array.array('f', [])
                guest_worker.cmd("virt.send_loop_init('%s', %d)"
                                 % (port.name, buf_len), 30)
                thread = qemu_virtio_port.ThRecv(port.sock, EXIT_EVENT,
                                                 buf_len)
                thread.start()
                loads.start()
                guest_worker.cmd("virt.send_loop()", 10)
                _time = time.time()
                for _ in range(100):
                    stats.append(thread.idx)
                    time.sleep(time_slice)
                _time = time.time() - _time - duration
                logging.info("\n" + loads.get_cpu_status_string()[:-1])
                logging.info("\n" + loads.get_mem_status_string()[:-1])
                guest_worker.cmd("virt.exit_threads()", 10)
                EXIT_EVENT.set()
                thread.join()
                if thread.ret_code:
                    no_errors += 1
                    logging.error("test_perf: error occurred in thread %s",
                                  thread)
                # Deviation is higher than single time_slice
                if (_time > time_slice):
                    logging.error("Test ran %fs longer which is more than one "
                                  "time slice", _time)
                else:
                    logging.debug("Test ran %fs longer", _time)
                stats = _process_stats(stats[1:], time_slice * 1048576)
                logging.debug("Stats = %s", stats)
                logging.info("Guest -> Host [MB/s] (min/med/max) = %.3f/%.3f/"
                             "%.3f", stats[0], stats[len(stats) / 2],
                             stats[-1])
            except Exception, inst:
                logging.error("test_perf: Failed with %s, starting cleanup",
                              inst)
                loads.stop()
                try:
                    guest_worker.cmd("virt.exit_threads()", 10)
                    EXIT_EVENT.set()
                    thread.join()
                    raise inst
                except Exception, inst:
                    logging.error("test_perf: Critical failure, killing VM %s",
                                  inst)
                    EXIT_EVENT.set()
                    vm.destroy()
                    del thread
                    raise inst
            funcatexit.unregister(env, params.get('type'), __set_exit_event)
            del thread
        cleanup(vm, guest_worker)
        if no_errors:
            msg = ("test_perf: %d errors occurred while executing test, "
                   "check log for details." % no_errors)
            logging.error(msg)
            raise error.TestFail(msg)

    #
    # Migration tests
    #
    @error.context_aware
    def _tmigrate(use_serialport, no_ports, no_migrations, blocklen, offline):
        """
        An actual migration test. It creates loopback on guest from first port
        to all remaining ports. Than it sends and validates the data.
        During this it tries to migrate the vm n-times.

        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param consoles: Field of virtio ports with the minimum of 2 items.
        :param parms: [media, no_migration, send-, recv-, loopback-buffer_len]
        """
        # PREPARE
        if use_serialport:
            vm, guest_worker = get_vm_with_worker(no_serialports=no_ports)
            ports = get_virtio_ports(vm)[1]
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=no_ports)
            ports = get_virtio_ports(vm)[0]

        # TODO BUG: sendlen = max allowed data to be lost per one migration
        # TODO BUG: using SMP the data loss is up to 4 buffers
        # 2048 = char.dev. socket size, parms[2] = host->guest send buffer size
        sendlen = 2 * 2 * max(qemu_virtio_port.SOCKET_SIZE, blocklen)
        if not offline:     # TODO BUG: online migration causes more loses
            # TODO: Online migration lose n*buffer. n depends on the console
            # troughput. FIX or analyse it's cause.
            sendlen = 1000 * sendlen
        for port in ports[1:]:
            port.open()

        ports[0].open()

        threads = []
        queues = []
        verified = []
        for i in range(0, len(ports[1:])):
            queues.append(deque())
            verified.append(0)

        tmp = "'%s'" % ports[1:][0].name
        for recv_pt in ports[1:][1:]:
            tmp += ", '%s'" % (recv_pt.name)
        guest_worker.cmd("virt.loopback(['%s'], [%s], %d, virt.LOOP_POLL)"
                         % (ports[0].name, tmp, blocklen), 10)

        funcatexit.register(env, params.get('type'), __set_exit_event)

        # TEST
        thread = qemu_virtio_port.ThSendCheck(ports[0], EXIT_EVENT, queues,
                                              blocklen,
                                              migrate_event=threading.Event())
        thread.start()
        threads.append(thread)

        for i in range(len(ports[1:])):
            _ = threading.Event()
            thread = qemu_virtio_port.ThRecvCheck(ports[1:][i], queues[i],
                                                  EXIT_EVENT, blocklen,
                                                  sendlen=sendlen,
                                                  migrate_event=_)
            thread.start()
            threads.append(thread)

        i = 0
        while i < 6:
            tmp = "%d data sent; " % threads[0].idx
            for thread in threads[1:]:
                tmp += "%d, " % thread.idx
            logging.debug("test_migrate: %s data received and verified",
                          tmp[:-2])
            i += 1
            time.sleep(2)

        for j in range(no_migrations):
            error.context("Performing migration number %s/%s"
                          % (j, no_migrations))
            vm = utils_test.migrate(vm, env, 3600, "exec", 0,
                                    offline)
            if not vm:
                raise error.TestFail("Migration failed")

            # Set new ports to Sender and Recver threads
            # TODO: get ports in this function and use the right ports...
            if use_serialport:
                ports = get_virtio_ports(vm)[1]
            else:
                ports = get_virtio_ports(vm)[0]
            for i in range(len(threads)):
                threads[i].port = ports[i]
                threads[i].migrate_event.set()

            # OS is sometime a bit dizzy. DL=30
            # guest_worker.reconnect(vm, timeout=30)

            i = 0
            while i < 6:
                tmp = "%d data sent; " % threads[0].idx
                for thread in threads[1:]:
                    tmp += "%d, " % thread.idx
                logging.debug("test_migrate: %s data received and verified",
                              tmp[:-2])
                i += 1
                time.sleep(2)
            if not threads[0].isAlive():
                if EXIT_EVENT.isSet():
                    raise error.TestFail("Exit event emitted, check the log "
                                         "for send/recv thread failure.")
                else:
                    EXIT_EVENT.set()
                    raise error.TestFail("Send thread died unexpectedly in "
                                         "migration %d" % (j + 1))
            for i in range(0, len(ports[1:])):
                if not threads[i + 1].isAlive():
                    EXIT_EVENT.set()
                    raise error.TestFail("Recv thread %d died unexpectedly in "
                                         "migration %d" % (i, (j + 1)))
                if verified[i] == threads[i + 1].idx:
                    EXIT_EVENT.set()
                    raise error.TestFail("No new data in %d console were "
                                         "transferred after migration %d"
                                         % (i, (j + 1)))
                verified[i] = threads[i + 1].idx
            logging.info("%d out of %d migration(s) passed", (j + 1),
                         no_migrations)
            # If we get to this point let's assume all threads were reconnected
            for thread in threads:
                thread.migrate_event.clear()
            # TODO detect recv-thread failure and throw out whole test

        # FINISH
        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get('type'), __set_exit_event)
        # Send thread might fail to exit when the guest stucks
        workaround_unfinished_threads = False
        threads[0].join(5)
        if threads[0].isAlive():
            workaround_unfinished_threads = True
            logging.error('Send thread stuck, destroing the VM and '
                          'stopping loopback test to prevent autotest freeze.')
            vm.destroy()
        tmp = "%d data sent; " % threads[0].idx
        err = ""

        for thread in threads[1:]:
            thread.join(5)
            if thread.isAlive():
                workaround_unfinished_threads = True
                logging.debug("Unable to destroy the thread %s", thread)
            tmp += "%d, " % thread.idx
            if thread.ret_code:
                err += "%s, " % thread
        logging.info("test_migrate: %s data received and verified during %d "
                     "migrations", tmp[:-2], no_migrations)
        if err:
            msg = "test_migrate: error occurred in threads: %s." % err[:-2]
            logging.error(msg)
            raise error.TestFail(msg)

        # CLEANUP
        guest_worker.safe_exit_loopback_threads([ports[0]], ports[1:])

        for thread in threads:
            if thread.isAlive():
                vm.destroy()
                del threads[:]
                raise error.TestError("Not all threads finished.")
        if workaround_unfinished_threads:
            logging.debug("All threads finished at this point.")
        del threads[:]
        cleanup(vm, guest_worker)

    def _test_migrate(offline):
        """
        Migration test wrapper, see the actual test_migrate_* tests for details
        """
        no_migrations = int(params.get("virtio_console_no_migrations", 5))
        no_ports = int(params.get("virtio_console_no_ports", 2))
        blocklen = int(params.get("virtio_console_blocklen", 1024))
        use_serialport = params.get('virtio_console_params') == "serialport"
        _tmigrate(use_serialport, no_ports, no_migrations, blocklen, offline)

    def test_migrate_offline():
        """
        Tests whether the virtio-{console,port} are able to survive the offline
        migration.
        :param cfg: virtio_console_no_migrations - how many times to migrate
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_blocklen - send/recv block length
        :param cfg: virtio_console_no_ports - minimum number of loopback ports
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        _test_migrate(offline=True)

    def test_migrate_online():
        """
        Tests whether the virtio-{console,port} are able to survive the online
        migration.
        :param cfg: virtio_console_no_migrations - how many times to migrate
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_blocklen - send/recv block length
        :param cfg: virtio_console_no_ports - minimum number of loopback ports
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        _test_migrate(offline=False)

    def _virtio_dev_add(vm, pci_id, port_id, console="no"):
        """
        Adds virtio serialport device.
        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param pci_id: Id of virtio-serial-pci device.
        :param port_id: Id of port.
        :param console: if "yes" inicialize console.
        """
        port = "serialport-"
        port_type = "virtserialport"
        if console == "yes":
            port = "console-"
            port_type = "virtconsole"
        port += "%d-%d" % (pci_id, port_id)
        ret = vm.monitors[0].cmd("device_add %s,"
                                 "bus=virtio_serial_pci%d.0,"
                                 "id=%s,"
                                 "name=%s"
                                 % (port_type, pci_id, port, port))
        if console == "no":
            vm.virtio_ports.append(qemu_virtio_port.VirtioSerial(port, port,
                                                                 None))
        else:
            vm.virtio_ports.append(qemu_virtio_port.VirtioConsole(port, port,
                                                                  None))
        if ret != "":
            logging.error(ret)

    def _virtio_dev_del(vm, pci_id, port_id):
        """
        Removes virtio serialport device.
        :param vm: Target virtual machine [vm, session, tmp_dir, ser_session].
        :param pci_id: Id of virtio-serial-pci device.
        :param port_id: Id of port.
        """
        for port in vm.virtio_ports:
            if port.name.endswith("-%d-%d" % (pci_id, port_id)):
                ret = vm.monitors[0].cmd("device_del %s" % (port.name))
                vm.virtio_ports.remove(port)
                if ret != "":
                    logging.error(ret)
                return
        raise error.TestFail("Removing port which is not in vm.virtio_ports"
                             " ...-%d-%d" % (pci_id, port_id))

    @error.context_aware
    def test_hotplug():
        """
        Check the hotplug/unplug of virtio-consoles ports.
        TODO: co vsechno to opravdu testuje?
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_console_pause - pause between monitor commands
        """
        # TODO: Support the new port name_prefix
        # TODO: 101 of 100 ports are initialised (might be related to above^^)

        # TODO: Rewrite this test. It was left as it was before the virtio_port
        # conversion and looked too messy to repair it during conversion.
        # TODO: Split this test into multiple variants
        # TODO: Think about customizable params
        # TODO: use qtree to detect the right virtio-serial-pci name
        # TODO: QMP
        if params.get("virtio_console_params") == "serialport":
            console = "no"
        else:
            console = "yes"
        pause = int(params.get("virtio_console_pause", 1))
        logging.info("Timeout between hotplug operations t=%fs", pause)

        vm = get_vm_with_ports(1, 1, spread=0, quiet=True, strict=True)
        consoles = get_virtio_ports(vm)
        # send/recv might block for ever, set non-blocking mode
        consoles[0][0].open()
        consoles[1][0].open()
        consoles[0][0].sock.setblocking(0)
        consoles[1][0].sock.setblocking(0)
        logging.info("Test correct initialization of hotplug ports")
        for bus_id in range(1, 5):  # count of pci device
            ret = vm.monitors[0].cmd("device_add virtio-serial-pci,"
                                     "id=virtio_serial_pci%d" % (bus_id))
            if ret != "":
                logging.error(ret)
            for i in range(bus_id * 5 + 5):     # max ports 30
                _virtio_dev_add(vm, bus_id, i, console)
                time.sleep(pause)
        # Test correct initialization of hotplug ports
        time.sleep(10)  # Timeout for port initialization
        guest_worker = qemu_virtio_port.GuestWorker(vm)

        logging.info("Delete ports when ports are used")
        # Delete ports when ports are used.
        guest_worker.cmd("virt.loopback(['%s'], ['%s'], 1024,"
                         "virt.LOOP_POLL)" % (consoles[0][0].name,
                                              consoles[1][0].name), 10)
        funcatexit.register(env, params.get('type'), __set_exit_event)

        send = qemu_virtio_port.ThSend(consoles[0][0].sock, "Data", EXIT_EVENT,
                                       quiet=True)
        recv = qemu_virtio_port.ThRecv(consoles[1][0].sock, EXIT_EVENT,
                                       quiet=True)
        send.start()
        time.sleep(2)
        recv.start()

        # Try to delete ports under load
        ret = vm.monitors[0].cmd("device_del %s" % consoles[1][0].name)
        ret += vm.monitors[0].cmd("device_del %s" % consoles[0][0].name)
        vm.virtio_ports = vm.virtio_ports[2:]
        if ret != "":
            logging.error(ret)

        EXIT_EVENT.set()
        funcatexit.unregister(env, params.get('type'), __set_exit_event)
        send.join()
        recv.join()
        guest_worker.cmd("virt.exit_threads()", 10)
        guest_worker.cmd('guest_exit()', 10)

        logging.info("Trying to add maximum count of ports to one pci device")
        # Try to add ports
        for i in range(30):     # max port 30
            _virtio_dev_add(vm, 0, i, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd('guest_exit()', 10)

        logging.info("Trying delete and add again part of ports")
        # Try to delete ports
        for i in range(25):     # max port 30
            _virtio_dev_del(vm, 0, i)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd('guest_exit()', 10)

        # Try to add ports
        for i in range(5):      # max port 30
            _virtio_dev_add(vm, 0, i, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd('guest_exit()', 10)

        logging.info("Trying to add and delete one port 100 times")
        # Try 100 times add and delete one port.
        for i in range(100):
            _virtio_dev_del(vm, 0, 0)
            time.sleep(pause)
            _virtio_dev_add(vm, 0, 0, console)
            time.sleep(pause)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        cleanup(guest_worker=guest_worker)
        # VM is broken (params mismatches actual state)
        vm.destroy()

    @error.context_aware
    def test_hotplug_virtio_pci():
        """
        Tests hotplug/unplug of the virtio-serial-pci bus.
        :param cfg: virtio_console_pause - pause between monitor commands
        :param cfg: virtio_console_loops - how many loops to run
        """
        # TODO: QMP
        # TODO: check qtree for device presence
        pause = int(params.get("virtio_console_pause", 10))
        vm = get_vm_with_ports()
        idx = 1
        for i in xrange(int(params.get("virtio_console_loops", 2))):
            error.context("Hotpluging virtio_pci (iteration %d)" % i)
            ret = vm.monitors[0].cmd("device_add virtio-serial-pci,"
                                     "id=virtio_serial_pci%d" % (idx))
            time.sleep(pause)
            ret += vm.monitors[0].cmd("device_del virtio_serial_pci%d"
                                      % (idx))
            time.sleep(pause)
            if ret != "":
                raise error.TestFail("Error occurred while hotpluging virtio-"
                                     "pci. Iteration %s, monitor output:\n%s"
                                     % (i, ret))

    #
    # Destructive tests
    #
    @error.context_aware
    def test_rw_notconnect_guest():
        """
        Try to send to/read from guest on host while guest not recvs/sends any
        data.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        vm = env.get_vm(params["main_vm"])
        use_serialport = params.get('virtio_console_params') == "serialport"
        if use_serialport:
            vm = get_vm_with_ports(no_serialports=1, strict=True)
        else:
            vm = get_vm_with_ports(no_consoles=1, strict=True)
        if use_serialport:
            port = get_virtio_ports(vm)[1][0]
        else:
            port = get_virtio_ports(vm)[0][0]
        if not port.is_open():
            port.open()
        else:
            port.close()
            port.open()

        port.sock.settimeout(20.0)

        loads = utils.SystemLoad([(os.getpid(), 'autotest'),
                                (vm.get_pid(), 'VM'), 0])
        try:
            loads.start()

            try:
                sent1 = 0
                for _ in range(1000000):
                    sent1 += port.sock.send("a")
            except socket.timeout:
                logging.info("Data sending to closed port timed out.")

            logging.info("Bytes sent to client: %d", sent1)
            logging.info("\n" + loads.get_cpu_status_string()[:-1])

            logging.info("Open and then close port %s", port.name)
            guest_worker = qemu_virtio_port.GuestWorker(vm)
            # Test of live and open and close port again
            guest_worker.cleanup()
            port.sock.settimeout(20.0)

            loads.start()
            try:
                sent2 = 0
                for _ in range(40000):
                    sent2 = port.sock.send("a")
            except socket.timeout:
                logging.info("Data sending to closed port timed out.")

            logging.info("Bytes sent to client: %d", sent2)
            logging.info("\n" + loads.get_cpu_status_string()[:-1])
            loads.stop()
        except Exception, inst:
            logging.error('test_rw_notconnect_guest failed: %s', inst)
            if loads:
                loads.stop()
            port.sock.settimeout(None)
            guest_worker = qemu_virtio_port.GuestWorker(vm)
            cleanup(vm, guest_worker)
            raise inst
        if (sent1 != sent2):
            logging.warning("Inconsistent behavior: First sent %d bytes and "
                            "second sent %d bytes", sent1, sent2)

        port.sock.settimeout(None)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_rmmod():
        """
        Remove and load virtio_console kernel module.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        """
        (vm, guest_worker, port) = get_vm_with_single_port(
            params.get('virtio_console_params'))
        guest_worker.cleanup()
        session = vm.wait_for_login()
        if session.cmd_status('lsmod | grep virtio_console'):
            raise error.TestNAError("virtio_console not loaded, probably "
                                    " not compiled as module. Can't test it.")
        session.cmd("rmmod -f virtio_console")
        session.cmd("modprobe virtio_console")
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        guest_worker.cmd("virt.clean_port('%s'),1024" % port.name, 2)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_max_ports():
        """
        Try to start and initialize machine with maximum supported number of
        virtio ports. (30)
        :param cfg: virtio_console_params - which type of virtio port to test
        """
        port_count = 30
        if params.get('virtio_console_params') == "serialport":
            logging.debug("Count of serialports: %d", port_count)
            vm = get_vm_with_ports(0, port_count, quiet=True)
        else:
            logging.debug("Count of consoles: %d", port_count)
            vm = get_vm_with_ports(port_count, 0, quiet=True)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_max_serials_and_conosles():
        """
        Try to start and initialize machine with maximum supported number of
        virtio ports with 15 virtconsoles and 15 virtserialports.
        """
        port_count = 15
        logging.debug("Count of virtports: %d %d", port_count, port_count)
        vm = get_vm_with_ports(port_count, port_count, quiet=True)
        guest_worker = qemu_virtio_port.GuestWorker(vm)
        cleanup(vm, guest_worker)

    @error.context_aware
    def test_stressed_restart():
        """
        Try to gently shutdown the machine while sending data through virtio
        port.
        :note: VM should shutdown safely.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        :param cfg: virtio_console_method - reboot method (shell, system_reset)
        """
        if params.get('virtio_console_params') == 'serialport':
            vm, guest_worker = get_vm_with_worker(no_serialports=1)
            _ports, ports = get_virtio_ports(vm)
        else:
            vm, guest_worker = get_vm_with_worker(no_consoles=1)
            ports, _ports = get_virtio_ports(vm)
        ports.extend(_ports)

        session = vm.wait_for_login()
        for port in ports:
            port.open()
        # If more than one, send data on the other ports
        process = []
        for port in ports[1:]:
            guest_worker.cmd("virt.close('%s')" % (port.name), 2)
            guest_worker.cmd("virt.open('%s')" % (port.name), 2)
            try:
                process.append(Popen("dd if=/dev/random of='%s' bs=4096 "
                                     "&>/dev/null &" % port.path))
            except Exception:
                pass
        # Start sending data, it won't finish anyway...
        guest_worker._cmd("virt.send('%s', 1024**3, True, is_static=True)"
                          % ports[0].name, 1)
        # Let the computer transfer some bytes :-)
        time.sleep(2)

        # Power off the computer
        try:
            vm.reboot(session=session,
                      method=params.get('virtio_console_method', 'shell'),
                      timeout=720)
        except Exception, details:
            for process in process:
                process.terminate()
            for port in vm.virtio_ports:
                port.close()
            raise error.TestFail("Fail to reboot VM:\n%s" % details)

        # close the virtio ports and process
        for process in process:
            process.terminate()
        for port in vm.virtio_ports:
            port.close()
        error.context("Executing basic loopback after reboot.", logging.info)
        test_basic_loopback()

    @error.context_aware
    def test_unplugged_restart():
        """
        Try to unplug all virtio ports and gently restart machine
        :note: VM should shutdown safely.
        :param cfg: virtio_console_params - which type of virtio port to test
        :param cfg: virtio_port_spread - how many devices per virt pci (0=all)
        :param cfg: virtio_console_method - reboot method (shell, system_reset)
        """
        if params.get('virtio_console_params') == 'serialport':
            vm = get_vm_with_ports(no_serialports=1)
        else:
            vm = get_vm_with_ports(no_consoles=1)
        ports, _ports = get_virtio_ports(vm)
        ports.extend(_ports)

        # Remove all ports:
        while vm.virtio_ports:
            port = vm.virtio_ports.pop()
            ret = vm.monitor.cmd("device_del %s" % port.qemu_id)
            if ret != "":
                raise error.TestFail("Can't unplug port %s: %s" % (port, ret))
        session = vm.wait_for_login()

        # Power off the computer
        try:
            vm.reboot(session=session,
                      method=params.get('virtio_console_method', 'shell'),
                      timeout=720)
        except Exception, details:
            raise error.TestFail("Fail to reboot VM:\n%s" % details)

        # TODO: Hotplug ports and verify that they are usable
        # VM is missing ports, which are in params.
        vm.destroy(gracefully=True)

    @error.context_aware
    def test_failed_boot():
        """
        Start VM and check if it failed with the right error message.
        :param cfg: virtio_console_params - Expected error message.
        """
        exp_error_message = params['virtio_console_params']
        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        try:
            vm.create()
        except Exception, details:
            if exp_error_message in str(details):
                logging.info("Expected qemu failure. Test PASSED.")
                return
            else:
                raise error.TestFail("VM failed to start but error messages "
                                     "don't match.\nExpected:\n%s\nActual:\n%s"
                                     % (exp_error_message, details))
        raise error.TestFail("VM started even though it should fail.")

    #
    # Debug and dummy tests
    #
    @error.context_aware
    def test_delete_guest_script():
        """
        This dummy test only removes the guest_worker_script. Use this it
        when you use the old image with a new guest_worker version.
        :note: The script name might differ!
        """
        vm = env.get_vm(params["main_vm"])
        session = vm.wait_for_login()
        out = session.cmd_output("echo on")
        if "on" in out:     # Linux
            session.cmd_status("killall python")
            session.cmd_status("rm -f /tmp/guest_daemon_*")
            session.cmd_status("rm -f /tmp/virtio_console_guest.py*")
        else:       # Windows
            session.cmd_status("del /F /Q C:\\virtio_console_guest.py*")

    #
    # Main
    # Executes test specified by virtio_console_test variable in cfg
    #
    fce = None
    _fce = "test_" + params.get('virtio_console_test', '').strip()
    error.context("Executing test: %s" % _fce, logging.info)
    if _fce not in locals():
        raise error.TestNAError("Test %s doesn't exist. Check 'virtio_console_"
                                "test' variable in subtest.cfg" % _fce)
    else:
        try:
            fce = locals()[_fce]
            return fce()
        except Exception, details:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            logging.error("Original traceback:\n" +
                          "".join(traceback.format_exception(
                                  exc_type, exc_value,
                                  exc_traceback.tb_next)))
            if isinstance(details, error.TestError):
                raise error.TestError('%s error: %s' % (_fce, details))
            elif isinstance(details, error.TestNAError):
                raise error.TestNAError('%s skipped: %s' % (_fce, details))
            else:
                raise error.TestFail('%s failed: %s' % (_fce, details))
