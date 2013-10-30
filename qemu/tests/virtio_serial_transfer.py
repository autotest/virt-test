import time, logging, os
from autotest.client.shared import error
from virttest import utils_test, utils_misc, data_dir, qemu_virtio_port




@error.context_aware
def run_virtio_serial_transfer(test, params, env):
    """
    Qemu virtio serial transfer test:
    1) Boot up a guest with virtio serial device
    2) Send data from guest through virtio serial port
    3) Get the data from guest. And check if the data is the same as we
       get from the virtio serial port
    4) Send the data back to guest through virtio serial port
    5) Get the data from guest. And check if the data is the same as we
       transfer from the virtio serial port

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def recv_loop():
        global tmp_data
        while not stop_flag:
            tmp_data += vs_port.sock.recv(4096)


    def send_loop(data):
        while not stop_flag:
            vs_port.sock.send(data)


    def start_thread(func, args):
        start_thread = utils_test.BackgroundTest(func, args)
        start_thread.start()
        return start_thread


    def stop_thread(thread_need_stop, recv_thread=True):
        global stop_flag
        stop_flag = True
        try:
            if recv_thread:
                guest_worker.cmd("virt.send('%s', length=4096)" % vs_port.name)
            else:
                guest_worker.cmd("virt.recv('%s', length=%s)" % (vs_port.name,
                                                                 data_length),
                                 timeout=data_send_timeout)
        except qemu_virtio_port.VirtioPortException:
            pass

        thread_need_stop.join()
        guest_worker.cleanup_ports()
        stop_flag = False


    vm = env.get_vm(params["main_vm"])
    error.context("Boot a guest", logging.info)
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    test_timeout = int(params.get("send_timeout", 600))
    data_length = int(params["data_length"])
    data_send_timeout = max(data_length / 1024, 10)
    guest_save_file = params["guest_save_file"]
    host_save_file = params["host_save_file"]
    host_save_file = utils_misc.get_path(data_dir.get_tmp_dir(),
                                         host_save_file)
    cleanup_cmd = params.get("cleanup_cmd")
    global tmp_data
    global stop_flag
    tmp_data = ""
    stop_flag = False

    session = vm.wait_for_login(timeout=timeout)


    vs_port = vm.virtio_ports[0]
    vs_port.open()

    guest_worker = qemu_virtio_port.GuestWorker(vm)
    guest_worker.cleanup_ports()

    error.context("Send file from guest to host for %ss" % test_timeout,
                  logging.info)
    recv_thread = start_thread(recv_loop, ())
    end_time = time.time() + test_timeout
    while time.time() < end_time:
        send_cmd = "virt.send('%s', length=%s)" % (vs_port.name, data_length)
        guest_worker.cmd(send_cmd, timeout=data_send_timeout)
        tmp_data = ""
    stop_thread(recv_thread, True)

    error.context("Check data transfer through virtio serial port from guest"
                  " to host", logging.info)
    send_cmd = ("virt.send('%s', length=%s, "
                "writefile='%s')" % (vs_port.name,
                                     data_length, guest_save_file))
    tmp_data = ""
    stop_flag = False
    recv_thread = start_thread(recv_loop, ())
    guest_worker.cmd(send_cmd, timeout=data_send_timeout)
    while len(tmp_data) < data_length:
        logging.debug("Wait for reading process get all data.")
    data = tmp_data
    stop_thread(recv_thread, True)

    vm.copy_files_from(guest_save_file, host_save_file)

    host_file = open(host_save_file, 'r')
    guest_data = host_file.read()
    host_file.close()
    # Save the data to file for furthur debug
    guest_data_send = open(utils_misc.get_path(test.debugdir,
                                               'guest_data_send'), 'wb')
    guest_data_send.write(guest_data)
    guest_data_send.close()
    host_data_get = open(utils_misc.get_path(test.debugdir,
                                             'host_data_get'), 'wb')
    host_data_get.write(data)
    host_data_get.close()
    if guest_data != data:
        raise error.TestFail("Data mismatched. Please check the log files.")

    os.remove(host_save_file)
    error.context("Send file from host to guest for %ss" % test_timeout,
                  logging.info)

    send_thread = start_thread(send_loop, (data,))
    end_time = time.time() + test_timeout
    while time.time() < end_time:
        guest_worker.cmd("virt.recv('%s', length=%s)" % (vs_port.name,
                                                         data_length),
                          timeout=data_send_timeout)
    stop_thread(send_thread, False)

    error.context("Check data transfer through virtio serial port from host to"
                  " guest", logging.info)


    send_thread = start_thread(vs_port.sock.send, (data,))
    recv_cmd = "virt.recv('%s', length=%s, writefile='%s')" % (vs_port.name,
                                                               data_length,
                                                               guest_save_file)
    guest_worker.cmd(recv_cmd, timeout=data_send_timeout)
    send_thread.join()

    vm.copy_files_from(guest_save_file, host_save_file)

    host_file = open(host_save_file, 'r')
    guest_data = host_file.read()
    host_file.close()
    # Save the data to file for furthur debug
    guest_data_get = open(utils_misc.get_path(test.debugdir,
                                              'guest_data_get'), 'wb')
    guest_data_get.write(guest_data)
    guest_data_get.close()
    host_data_send = open(utils_misc.get_path(test.debugdir,
                                              'host_data_send'), 'wb')
    host_data_send.write(data)
    host_data_send.close()

    if guest_data != data:
        raise error.TestFail("Data mismatched. Please check the log files.")

    os.remove(host_save_file)

    if cleanup_cmd:
        session.cmd_status_output(cleanup_cmd)
    guest_worker.cleanup()
    vs_port.close()
    session.close()
