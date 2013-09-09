import logging
import re
import time
from autotest.client.shared import error
from virttest import utils_test, utils_misc


@error.context_aware
def run_cpu_add(test, params, env):
    """
    Runs CPU hotplug test:

    1) Boot the vm with -smp X,maxcpus=Y
    2) After logged into the vm, check CPUs number
    3) Stop the guest if config 'stop_before_hotplug'
    4) Do cpu hotplug
    5) Resume the guest if config 'stop_before_hotplug'
    6) Recheck guest get hot-pluged CPUs
    7) Do cpu online/offline in guest if config
    8) Run sub test after CPU Hotplug
    9) Recheck guest cpus after sub test

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    def qemu_guest_cpu_match(vm, vcpu_been_pluged=0, wait_time=60):
        """
        Check Whether the vcpus are matche
        """
        total_cpus_expected = int(vm.cpuinfo.smp) + int(vcpu_been_pluged)
        if utils_misc.wait_for(lambda: ((total_cpus_expected ==
                                         vm.get_cpu_count()) and
                                        (vm.get_cpu_count() ==
                                         len(vm.vcpu_threads))),
                               wait_time, first=10, step=5.0):
            logging.info("Cpu number in cmd_line, qemu and guest are match")
            return True
        err_msg = "Cpu mismatch! "
        err_msg += "after hotplug %s vcpus, " % vcpu_been_pluged
        err_msg += "there shoule be %s vcpus exist, " % total_cpus_expected
        err_msg += "in qemu %s vcpus threads works, " % len(vm.vcpu_threads)
        err_msg += "in guest %s cpus works." % vm.get_cpu_count()
        raise error.TestFail(err_msg)

    def cpu_online_offline(session, cpu_id, online=""):
        """
        Do cpu online/offline in guest
        """
        if online == "online":
            online = 1
        else:
            online = 0
        online_file = "/sys/devices/system/cpu/cpu%s/online" % cpu_id
        if session.cmd_status("test -f %s" % online_file):
            logging.info("online file %s not exist, just pass the cpu%s" %
                         (online_file, cpu_id))
            return
        session.cmd("echo %s > %s " % (online, online_file))

    def onoff_para_opt(onoff_params):
        """
        Online offline params anaylize
        Return a cpu list need do online offline
        """
        onoff_list = []
        offline = onoff_params.split(",")
        for item in offline:
            if "-" in item:
                onoff_list += range(int(item.split("-")[0]),
                                    int(item.split("-")[1]))
            else:
                onoff_list.append(item)
        return [str(i) for i in onoff_list]

    timeout = int(params.get("login_timeout", 360))
    onoff_iterations = int(params.get("onoff_iterations", 2))
    vcpu_need_hotplug = int(params.get("vcpu_need_hotplug", 1))

    error.context("Boot the vm, with '-smp X,maxcpus=Y' option", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    maxcpus = vm.cpuinfo.maxcpus

    error.context("Check if cpus in guest matche qemu cmd before hotplug",
                  logging.info)
    qemu_guest_cpu_match(vm)

    # do pre_operation like stop, before vcpu Hotplug
    stop_before_hotplug = params.get("stop_before_hotplug", "no")
    if stop_before_hotplug == 'yes':
        error.context("Stop the guest before hotplug vcpu", logging.info)
        vm.pause()

    error.context("Do cpu hotplug", logging.info)
    if vm.monitor.protocol == 'human':
        human_check_info = params.get("human_error_recheck", None)
        qmp_check_info = None
        hotplug_add_cmd = ""
    elif vm.monitor.protocol == 'qmp':
        qmp_check_info = params.get("qmp_error_recheck", None)
        hotplug_add_cmd = params.get("vcpu_add_cmd", "")
        if hotplug_add_cmd:
            human_check_info = params.get("human_error_recheck", None)
        else:
            human_check_info = None

    vcpu_been_pluged = 0
    for i in range(vcpu_need_hotplug):
        hotplug_vcpu_params = params.object_params("hotplug_vcpu%s" % i)
        plug_cpu_id = len(vm.vcpu_threads)
        plug_cpu_id = hotplug_vcpu_params.get("id", plug_cpu_id)

        (status, output) = vm.hotplug_vcpu(plug_cpu_id, hotplug_add_cmd)

        if status:
            if not qmp_check_info and not human_check_info:
                vcpu_been_pluged += 1
                logging.info("Cpu%s hotplug successfully" % plug_cpu_id)
                logging.info("Now '%s' cpus have been hotpluged" %
                             vcpu_been_pluged)
                continue
            else:
                err_msg = "Qemu should report error, but hotplug successfully"
                raise error.TestFail(err_msg)
        else:
            if not output:
                warn_msg = "Qemu should report some warning information"
                raise error.TestWarn(warn_msg)
            if qmp_check_info and re.findall(qmp_check_info, output, re.I):
                msg = "Hotplug vcpu(id:'%s') error, qemu report the error."
                logging.info(msg % plug_cpu_id)
                logging.debug("QMP error info: '%s'" % output)
                continue
            elif (human_check_info and
                  re.findall(human_check_info, output, re.I)):
                msg = "Hotplug vcpu(id:'%s') error, qemu report the error"
                logging.info(msg % plug_cpu_id)
                logging.debug("Error info: '%s'" % output)
                continue
            else:
                err_msg = "Hotplug error! "
                err_msg += "the hotplug cpu_id is: '%s', " % plug_cpu_id
                err_msg += "the maxcpus allowed is: '%s', " % maxcpus
                err_msg += "qemu cpu list is:'%s'" % vm.monitor.info("cpus")
                logging.debug("The error info is:\n '%s'" % output)
                raise error.TestFail(err_msg)

    if stop_before_hotplug:
        error.context("Resume the guest after cpu hotplug", logging.info)
        vm.resume()

    if params.get("reboot_after_hotplug", False):
        error.context("Reboot guest after hotplug vcpu", logging.info)
        vm.reboot()

    if vcpu_been_pluged != 0:
        error.context("Check whether cpus are match after hotplug",
                      logging.info)
        qemu_guest_cpu_match(vm, vcpu_been_pluged)

    error.context("Do cpu online/offline in guest", logging.info)
    # Window guest doesn't support online/offline test
    if params['os_type'] == "windows":
        logging.info("For windows guest not do online/offline test")
        return

    online_list = []
    offline_list = []
    offline = params.get("offline", "")
    online = params.get("online", "")
    repeat_time = int(params.get("repeat_time", 0))

    if offline:
        offline_list = onoff_para_opt(offline)
        logging.debug("Cpu offline list is %s " % offline_list)
    if online:
        online_list = onoff_para_opt(online)
        logging.debug("Cpu online list is %s " % offline_list)

    for i in range(repeat_time):
        for offline_cpu in offline_list:
            cpu_online_offline(session, offline_cpu)
            time.sleep(onoff_iterations)
        for online_cpu in online_list:
            cpu_online_offline(session, online_cpu, "online")
            time.sleep(onoff_iterations)

    # do sub test after cpu hotplug
    if (params.get("run_sub_test", "no") == "yes" and
            'sub_test_name' in params):
        sub_test = params['sub_test_name']
        error.context("Run subtest %s after cpu hotplug" % sub_test,
                      logging.info)
        if (sub_test == "guest_suspend" and
                params["guest_suspend_type"] == "disk"):
            vm.params["smp"] = int(vm.cpuinfo.smp) + vcpu_been_pluged
            vcpu_been_pluged = 0
        utils_test.run_virt_sub_test(test, params, env, sub_type=sub_test)
        if sub_test == "shutdown":
            logging.info("Guest shutdown normally after cpu hotplug")
            return
        if params.get("session_need_update", "no") == "yes":
            session = vm.wait_for_login(timeout=timeout)

    if params.get("vcpu_num_rechek", "yes") == "yes":
        error.context("Recheck cpu numbers after operation", logging.info)
        qemu_guest_cpu_match(vm, vcpu_been_pluged)

    if session:
        session.close()
