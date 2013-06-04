import logging, os, time
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_test, utils_net


@error.context_aware
def run_nicdriver_unload(test, params, env):
    """
    Test nic driver load/unload.

    1) Boot a VM.
    2) Get the NIC driver name.
    3) Multi-session TCP transfer on test interface.
    4) Repeatedly unload/load NIC driver during file transfer.
    5) Check whether the test interface should still work.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """


    timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=timeout)

    error.context("Get NIC interface name in guest.", logging.info)
    ethname = utils_net.get_linux_ifname(session_serial,
                                               vm.get_mac_address(0))

    # get ethernet driver from '/sys' directory.
    # ethtool can do the same thing and doesn't care about os type.
    # if we make sure all guests have ethtool, we can make a change here.
    sys_path = params.get("sys_path") % (ethname)

    # readlink in RHEL4.8 doesn't have '-e' param, should use '-f' in RHEL4.8.
    readlink_cmd = params.get("readlink_command", "readlink -e")
    driver = os.path.basename(session_serial.cmd("%s %s" % (readlink_cmd,
                                                 sys_path)).strip())

    logging.info("driver is %s", driver)

    try:
        threads = []
        for i in range(int(params.get("sessions_num", "10"))):
            txt = "File transfer on test interface. Therad %s" % i
            error.context(txt, logging.info)
            thread = utils.InterruptedThread(utils_test.run_file_transfer,
                                             (test, params, env))
            thread.start()
            threads.append(thread)

        time.sleep(10)
        logging.info("Repeatedly unload/load NIC driver during file transfer.")
        while threads[0].isAlive():
            session_serial.cmd("sleep 10")
            error.context("Shutdown the driver for NIC interface.", logging.info)
            session_serial.cmd("ifconfig %s down" % ethname)
            error.context("Unload  NIC driver.", logging.info)
            session_serial.cmd("modprobe -r %s" % driver)
            error.context("Load NIC driver.", logging.info)
            session_serial.cmd("modprobe %s" % driver)
            error.context("Activate NIC driver.", logging.info)
            session_serial.cmd("ifconfig %s up" % ethname)
    except Exception:
        for thread in threads:
            thread.join(suppress_exception=True)
            raise
    else:
        for thread in threads:
            thread.join()
