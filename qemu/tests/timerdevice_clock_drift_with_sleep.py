import logging
import re
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir, storage, utils_disk, env_process


@error.context_aware
def run_timerdevice_clock_drift_with_sleep(test, params, env):
    """
    Timer device measure clock drift after sleep in guest with kvmclock:

    1) Sync the host system time with ntp server
    2) Boot a guest with multiple vcpus, using kvm-clock
    3) Check the clock source currently used on guest
    4) Stop auto sync service in guest (Optional)
    5) Sync time from guest to ntpserver
    6) Pin (only 1/none/all) vcpus to host cpu.
    7) Sleep a while and check the time drift on guest

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def verify_elapsed_time():
        usleep_cmd = r'echo "for n in \$(seq 1000);'
        usleep_cmd += ' do usleep 10000; done"'' > /tmp/usleep.sh'
        session.cmd(usleep_cmd)

        get_time_cmd = 'for (( i=0; i<$(grep "processor" /proc/cpuinfo'
        get_time_cmd += ' | wc -l); i+=1 )); do /usr/bin/time -f"%e"'
        get_time_cmd += ' taskset -c $i sh /tmp/usleep.sh; done'
        output = session.cmd_output(get_time_cmd, timeout=timeout)

        times_list = output.splitlines()[1:]
        times_list = [_ for _ in times_list if _ > 10.0 or _ < 11.0]

        if times_list:
            raise error.TestFail("Unexpected time drift found:"
                                 " Detail: '%s'" % output)

    error.context("Sync the host system time with ntp server", logging.info)
    utils.system("yum install -y ntpdate; ntpdate clock.redhat.com")

    error.context("Boot the guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Check the clock source currently used on guest",
                  logging.info)
    cmd = "cat /sys/devices/system/clocksource/"
    cmd += "clocksource0/current_clocksource"
    if not "kvm-clock" in session.cmd(cmd):
        grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
        if "clocksource=" not in session.cmd("cat %s" % grub_file):
            raise error.TestFail("Guest didn't use 'kvm-clock' clocksource")

        error.context("Shutdown guest")
        vm.destroy()
        env.unregister_vm(vm.name)
        error.context("Update guest kernel cli to kvm-clock",
                      logging.info)
        image_filename = storage.get_image_filename(params,
                                                    data_dir.get_data_dir())
        kernel_cfg_pattern = params.get("kernel_cfg_pos_reg",
                                        r".*vmlinuz-\d+.*")

        disk_obj = utils_disk.GuestFSModiDisk(image_filename)
        kernel_cfg_original = disk_obj.read_file(grub_file)
        try:
            logging.warn("Update the first kernel entry to kvm-clock only")
            kernel_cfg = re.findall(kernel_cfg_pattern,
                                    kernel_cfg_original)[0]
        except IndexError, detail:
            raise error.TestError("Couldn't find the kernel config, regex"
                                  " pattern is '%s', detail: '%s'" %
                                  (kernel_cfg_pattern, detail))

        if "clocksource=" in kernel_cfg:
            kernel_cfg_new = re.sub(r"clocksource=[a-z\- ]+", " ", kernel_cfg)
            disk_obj.replace_image_file_content(grub_file, kernel_cfg,
                                                kernel_cfg_new)

        error.context("Boot the guest", logging.info)
        vm_name = params["main_vm"]
        cpu_model_flags = params.get("cpu_model_flags")
        params["cpu_model_flags"] = cpu_model_flags + ",-kvmclock"
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)

    error.context("Stop auto sync service in guest", logging.info)
    cmd = "(service chronyd status | grep 'Loaded: loaded')"
    cmd += " && service chronyd stop"
    session.cmd_status_output(cmd)

    error.context("Sync time from guest to ntpserver", logging.info)
    session.cmd("yum install -y ntpdate; ntpdate clock.redhat.com",
                timeout=timeout)

    error.context("Sleep a while and check the time drift on guest"
                  " (without any pinned vcpu)", logging.info)
    verify_elapsed_time()

    error.context("Pin every vcpu to physical cpu", logging.info)
    host_cpu_cnt_cmd = params["host_cpu_cnt_cmd"]
    host_cpu_num = utils.system_output(host_cpu_cnt_cmd).strip()
    host_cpu_list = (_ for _ in range(int(host_cpu_num)))
    cpu_pin_list = zip(vm.vcpu_threads, host_cpu_list)
    if len(cpu_pin_list) < len(vm.vcpu_threads):
        raise error.TestNAError("There isn't enough physical cpu to"
                                " pin all the vcpus")
    check_one_cpu_pinned = False
    for vcpu, pcpu in cpu_pin_list:
        utils.system("taskset -p -c %s %s" % (pcpu, vcpu))
        if not check_one_cpu_pinned:
            error.context("Sleep a while and check the time drift on"
                          "guest (with one pinned vcpu)", logging.info)
            verify_elapsed_time()
            check_one_cpu_pinned = True

    error.context("Sleep a while and check the time drift on"
                  "guest (with all pinned vcpus)", logging.info)
    verify_elapsed_time()
