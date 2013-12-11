import logging
import re
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_net, utils_test, utils_misc


@error.context_aware
def run_mq_change_qnum(test, params, env):
    """
    MULTI_QUEUE chang queues number test

    1) Boot up VM, and login guest
    2) Check guest pci msi support and reset it as expection
    3) Run bg_stress_test(pktgen, netperf or file copy) if needed
    4) Change queues number repeatly during stress test running

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def change_queues_number(session, ifname, q_number, queues_status=None):
        """
        Change queues number
        """
        mq_set_cmd = "ethtool -L %s combined %d" % (ifname, q_number)
        if not queues_status:
            queues_status = get_queues_status(session, ifname)

        if q_number != queues_status[1] and q_number <= queues_status[0]:
            expect_status = 0
        else:
            expect_status = 1

        status, output =  session.cmd_status_output(mq_set_cmd)
        cur_queues_status = get_queues_status(session, ifname)
        if status != expect_status:
            err_msg = "Change queues number failed, "
            err_msg += "current queues set is %s, " % queues_status[1]
            err_msg += "max allow queues set is %s, " % queues_status[0]
            err_msg += "when run cmd: '%s', " % mq_set_cmd
            err_msg += "expect exit status is: %s, " % expect_status
            err_msg += "output: '%s'" % output
            raise error.TestFail(err_msg)
        if not status and cur_queues_status == queues_status:
            raise error.TestFail("params is right, but change queues failed")
        elif status and cur_queues_status != queues_status:
            raise error.TestFail("No need change queues number")
        return [ int(_) for _ in cur_queues_status ]


    def get_queues_status(session, ifname, timeout=240):
        """
        Get queues status
        """
        mq_get_cmd = "ethtool -l %s" % ifname
        nic_mq_info = session.cmd_output(mq_get_cmd, timeout=timeout)
        queues_reg = re.compile(r"Combined:\s+(\d)", re.I)
        queues_info = queues_reg.findall(" ".join(nic_mq_info.splitlines()))
        if len(queues_info) != 2:
            err_msg = "Oops, get guest queues info failed, "
            err_msg += "make sure your guest support MQ.\n"
            err_msg += "Check cmd is: '%s', " % mq_get_cmd
            err_msg += "Command output is: '%s'." %  nic_mq_info
            raise error.TestNAError(err_msg)
        return [ int(x) for x in queues_info ]


    error.context("Init guest and try to login", logging.info)
    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)

    if params.get("pci_nomsi", "no") == "yes":
        error.context("Disable pci msi in guest", logging.info)
        utils_test.update_boot_option(vm, args_added="pci=nomsi")
        vm.wait_for_login(timeout=login_timeout)

    session_serial = vm.wait_for_serial_login(timeout=login_timeout)
    bg_stress_test = params.get("run_bgstress")
    try:
        if bg_stress_test:
            error.context("Run test %s background" % bg_stress_test,
                          logging.info)
            stress_thread = ""
            wait_time = float(params.get("wait_bg_time", 60))
            bg_stress_run_flag = params.get("bg_stress_run_flag")
            env[bg_stress_run_flag] = False
            stress_thread = utils.InterruptedThread(
                    utils_test.run_virt_sub_test, (test, params, env),
                    {"sub_type": bg_stress_test})
            stress_thread.start()
            utils_misc.wait_for(lambda : env.get(bg_stress_run_flag),
                                wait_time, 0, 5,
                                "Wait %s start background" % bg_stress_test)

        error.context("Change queues number repeatly", logging.info)
        repeat_counts = int(params.get("repeat_counts", 10))
        for nic_index, nic in enumerate(vm.virtnet):
            if not "virtio" in nic['nic_model']:
                continue;
            queues = int(vm.virtnet[nic_index].queues)
            if queues == 1:
                logging.info("Nic with single queue, skip and continue")
                continue
            ifname = utils_net.get_linux_ifname(session_serial,
                                                vm.virtnet[nic_index].mac)
            default_change_list = xrange(1, int(queues))
            change_list = params.get("change_list")
            if change_list:
                change_list = change_list.split(",")
            else:
                change_list = default_change_list

            for repeat_num in xrange(1, repeat_counts + 1):
                error.context("Change queues number -- %sth" % repeat_num,
                              logging.info)
                queues_status = get_queues_status(session_serial, ifname)
                for q_number in change_list:
                    queues_status = change_queues_number(session_serial,
                                                         ifname,
                                                         int(q_number),
                                                         queues_status)
        if bg_stress_test:
            env[bg_stress_run_flag] = False
            if stress_thread:
                try:
                    stress_thread.join()
                except Exception, e:
                    err_msg = "Run %s test background error!\n "
                    err_msg += "Error Info: '%s'"
                    raise error.TestError(err_msg % (bg_stress_test, e))

    finally:
        env[bg_stress_run_flag] = False
        if session_serial:
            session_serial.close()
