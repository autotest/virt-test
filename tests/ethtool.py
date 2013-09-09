import logging
import re
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_net, utils_misc, remote, aexpect


@error.context_aware
def run_ethtool(test, params, env):
    """
    Test offload functions of ethernet device using ethtool

    1) Log into a guest.
    2) Saving ethtool configuration.
    3) Enable sub function of NIC.
    4) Execute callback function.
    5) Disable sub function of NIC.
    6) Run callback function again.
    7) Run file transfer test.
       7.1) Creating file in source host.
       7.2) Listening network traffic with tcpdump command.
       7.3) Transfer file.
       7.4) Comparing md5sum of the files on guest and host.
    8) Repeat step 3 - 7.
    9) Restore original configuration.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.

    @todo: Not all guests have ethtool installed, so
        find a way to get it installed using yum/apt-get/
        whatever
    """
    def send_cmd_safe(session, cmd):
        logging.debug("Sending command: %s", cmd)
        session.sendline(cmd)
        output = ""
        got_prompt = False
        start_time = time.time()
        # Wait for shell prompt until timeout.
        while ((time.time() - start_time) < login_timeout and not got_prompt):
            time.sleep(0.2)
            session.sendline()
            try:
                output += session.read_up_to_prompt()
                got_prompt = True
            except aexpect.ExpectTimeoutError:
                pass
        return output

    def ethtool_get(session, f_type):
        feature_pattern = {
            'tx': 'tx.*checksumming',
            'rx': 'rx.*checksumming',
            'sg': 'scatter.*gather',
            'tso': 'tcp.*segmentation.*offload',
            'gso': 'generic.*segmentation.*offload',
            'gro': 'generic.*receive.*offload',
            'lro': 'large.*receive.*offload',
        }
        o = session.cmd("ethtool -k %s" % ethname)
        try:
            result = re.findall("%s: (.*)" % feature_pattern.get(f_type), o)[0]
            logging.debug("(%s) %s: %s", ethname, f_type, result)
            return result
        except IndexError:
            logging.debug("(%s) %s: failed to get status", ethname, f_type)

    def ethtool_set(session, f_type, status):
        """
        Set ethernet device offload status

        @param f_type: Offload type name
        @param status: New status will be changed to
        """
        txt = "Set ethernet device offload status."
        txt += " (%s) %s: set status %s" % (ethname, f_type, status)
        error.context(txt, logging.info)
        if status not in ["off", "on"]:
            return False

        if ethtool_get(session, f_type) == status:
            return True

        err_msg = "(%s) %s: set status %s failed" % (ethname, f_type, status)
        cmd = "ethtool -K %s %s %s" % (ethname, f_type, status)
        try:
            send_cmd_safe(session, cmd)
        except aexpect.ShellCmdError, e:
            logging.error("%s, detail: %s", err_msg, e)
            return False

        if ethtool_get(session, f_type) == status:
            return True

        logging.error(err_msg)
        return True

    def ethtool_save_params(session):
        error.context("Saving ethtool configuration", logging.info)
        for i in supported_features:
            feature_status[i] = ethtool_get(session, i)

    def ethtool_restore_params(session):
        error.context("Restoring ethtool configuration", logging.info)
        for i in supported_features:
            ethtool_set(session, i, feature_status[i])

    def compare_md5sum(name):
        txt = "Comparing md5sum of the files on guest and host"
        error.context(txt, logging.info)
        host_result = utils.hash_file(name, method="md5")
        try:
            o = session.cmd_output("md5sum %s" % name)
            guest_result = re.findall("\w+", o)[0]
        except IndexError:
            logging.error("Could not get file md5sum in guest")
            return False
        logging.debug("md5sum: guest(%s), host(%s)", guest_result, host_result)
        return guest_result == host_result

    def transfer_file(src):
        """
        Transfer file by scp, use tcpdump to capture packets, then check the
        return string.

        @param src: Source host of transfer file
        @return: Tuple (status, error msg/tcpdump result)
        """
        sess = vm.wait_for_login(timeout=login_timeout)
        session.cmd_output("rm -rf %s" % filename)
        dd_cmd = ("dd if=/dev/urandom of=%s bs=1M count=%s" %
                  (filename, params.get("filesize")))
        failure = (False, "Failed to create file using dd, cmd: %s" % dd_cmd)
        txt = "Creating file in source host, cmd: %s" % dd_cmd
        error.context(txt, logging.info)
        ethname = utils_net.get_linux_ifname(session,
                                             vm.get_mac_address(0))
        tcpdump_cmd = "tcpdump -lep -i %s -s 0 tcp -vv port ssh" % ethname
        if src == "guest":
            tcpdump_cmd += " and src %s" % guest_ip
            copy_files_func = vm.copy_files_from
            try:
                sess.cmd_output(dd_cmd, timeout=360)
            except aexpect.ShellCmdError, e:
                return failure
        else:
            tcpdump_cmd += " and dst %s" % guest_ip
            copy_files_func = vm.copy_files_to
            try:
                utils.system(dd_cmd)
            except error.CmdError, e:
                return failure

        # only capture the new tcp port after offload setup
        original_tcp_ports = re.findall("tcp.*:(\d+).*%s" % guest_ip,
                                        utils.system_output("/bin/netstat -nap"))

        for i in original_tcp_ports:
            tcpdump_cmd += " and not port %s" % i

        txt = "Listening traffic using command: %s" % tcpdump_cmd
        error.context(txt, logging.info)
        sess.sendline(tcpdump_cmd)
        if not utils_misc.wait_for(
                lambda: session.cmd_status("pgrep tcpdump") == 0, 30):
            return (False, "Tcpdump process wasn't launched")

        txt = "Transferring file %s from %s" % (filename, src)
        error.context(txt, logging.info)
        try:
            copy_files_func(filename, filename)
        except remote.SCPError, e:
            return (False, "File transfer failed (%s)" % e)

        session.cmd("killall tcpdump")
        try:
            tcpdump_string = sess.read_up_to_prompt(timeout=60)
        except aexpect.ExpectError:
            return (False, "Failed to read tcpdump's output")

        if not compare_md5sum(filename):
            return (False, "Failure, md5sum mismatch")
        return (True, tcpdump_string)

    def tx_callback(status="on"):
        s, o = transfer_file("guest")
        if not s:
            logging.error(o)
            return False
        return True

    def rx_callback(status="on"):
        s, o = transfer_file("host")
        if not s:
            logging.error(o)
            return False
        return True

    def so_callback(status="on"):
        s, o = transfer_file("guest")
        if not s:
            logging.error(o)
            return False
        error.context("Check if contained large frame", logging.info)
        # MTU: default IPv4 MTU is 1500 Bytes, ethernet header is 14 Bytes
        return (status == "on") ^ (len([i for i in re.findall(
                                   "length (\d*):", o) if int(i) > mtu]) == 0)

    def ro_callback(status="on"):
        s, o = transfer_file("host")
        if not s:
            logging.error(o)
            return False
        return True

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error.context("Log into a guest.", logging.info)
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    # Let's just error the test if we identify that there's no ethtool
    # installed
    error.context("Check whether ethtool installed in guest.")
    session.cmd("ethtool -h")
    mtu = 1514
    feature_status = {}
    filename = "/tmp/ethtool.dd"
    guest_ip = vm.get_address()
    error.context("Try to get ethernet device name in guest.")
    ethname = utils_net.get_linux_ifname(session, vm.get_mac_address(0))

    supported_features = params.get("supported_features")
    if supported_features:
        supported_features = supported_features.split()
    else:
        raise error.TestError("No supported features set on the parameters")

    test_matrix = {
        # type:(callback,    (dependence), (exclude)
        "tx": (tx_callback, (), ()),
        "rx": (rx_callback, (), ()),
        "sg": (tx_callback, ("tx",), ()),
        "tso": (so_callback, ("tx", "sg",), ("gso",)),
        "gso": (so_callback, (), ("tso",)),
        "gro": (ro_callback, ("rx",), ("lro",)),
        "lro": (rx_callback, (), ("gro",)),
    }
    ethtool_save_params(session)
    failed_tests = []
    try:
        for f_type in supported_features:
            callback = test_matrix[f_type][0]

            for i in test_matrix[f_type][2]:
                if not ethtool_set(session, i, "off"):
                    e_msg = "Failed to disable %s" % i
                    logging.error(e_msg)
                    failed_tests.append(e_msg)

            for i in [f for f in test_matrix[f_type][1]] + [f_type]:
                if not ethtool_set(session, i, "on"):
                    e_msg = "Failed to enable %s" % i
                    logging.error(e_msg)
                    failed_tests.append(e_msg)
            txt = "Run callback function %s" % callback.func_name
            error.context(txt, logging.info)
            if not callback(status="on"):
                e_msg = "Callback failed after enabling %s" % f_type
                logging.error(e_msg)
                failed_tests.append(e_msg)

            if not ethtool_set(session, f_type, "off"):
                e_msg = "Failed to disable %s" % f_type
                logging.error(e_msg)
                failed_tests.append(e_msg)
            txt = "Run callback function %s" % callback.func_name
            error.context(txt, logging.info)
            if not callback(status="off"):
                e_msg = "Callback failed after disabling %s" % f_type
                logging.error(e_msg)
                failed_tests.append(e_msg)

        if failed_tests:
            raise error.TestFail("Failed tests: %s" % failed_tests)

    finally:
        try:
            if session:
                session.close()
        except Exception, detail:
            logging.error("Fail to close session: '%s'", detail)

        try:
            session = vm.wait_for_serial_login(timeout=login_timeout)
            ethtool_restore_params(session)
        except Exception, detail:
            logging.warn("Could not restore parameter of"
                         " eth card: '%s'", detail)
