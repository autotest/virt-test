import logging, re, time
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir, storage, utils_disk, utils_test, env_process

@error.context_aware
def run_timerdevice_boot(test, params, env):
    """
    Timer device boot guest:

    1) Sync the host system time with ntp server
    2) Boot the guest with specific clock source
    3) Check the clock source currently used on guest
    4) Do some file operation on guest (Optional)
    5) Check the system time on guest and host (Optional)
    6) Check the hardware time on guest and host (Optional)
    7) Sleep period of time before reboot (Optional)
    8) Reboot guest (Optional)
    9) Check the system time on guest and host (Optional)
    10) Check the hardware time on guest and host (Optional)

    @param test: QEMU test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    def verify_guest_clock_source(session, expected):
        error.context("Check the current clocksource in guest", logging.info)
        cmd = "cat /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        if not expected in session.cmd(cmd):
            raise error.TestFail("Guest didn't use '%s' clocksource" % expected)


    error.context("Sync the host system time with ntp server", logging.info)
    utils.system("ntpdate clock.redhat.com")

    error.context("Boot a guest with kvm-clock", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    timerdevice_clksource = params.get("timerdevice_clksource")
    if timerdevice_clksource:
        try:
            verify_guest_clock_source(session, timerdevice_clksource)
        except Exception:
            clksrc = timerdevice_clksource
            error.context("Shutdown guest")
            vm.destroy()
            env.unregister_vm(vm.name)
            error.context("Update guest kernel cli to '%s'" % clksrc,
                          logging.info)
            image_filename = storage.get_image_filename(params,
                                                    data_dir.get_data_dir())
            grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
            kernel_cfg_pattern = params.get("kernel_cfg_pos_reg",
                                             r".*vmlinuz-\d+.*")

            disk_obj = utils_disk.GuestFSModiDisk(image_filename)
            kernel_cfg_original = disk_obj.read_file(grub_file)
            try:
                logging.warn("Update the first kernel entry to"
                             " '%s' only" % clksrc)
                kernel_cfg = re.findall(kernel_cfg_pattern,
                                        kernel_cfg_original)[0]
            except IndexError, detail:
                raise error.TestError("Couldn't find the kernel config, regex"
                                      " pattern is '%s', detail: '%s'" %
                                      (kernel_cfg_pattern, detail))

            if "clocksource=" in kernel_cfg:
                kernel_cfg_new = re.sub("clocksource=.*?\s",
                                    "clocksource=%s" % clksrc, kernel_cfg)
            else:
                kernel_cfg_new = "%s %s" % (kernel_cfg,
                                            "clocksource=%s" % clksrc)

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

            error.context("Check the current clocksource in guest",
                          logging.info)
            verify_guest_clock_source(session, clksrc)

        error.context("Kill all ntp related processes")
        session.cmd("pkill ntp; true")


    if params.get("timerdevice_file_operation") == "yes":
        error.context("Do some file operation on guest", logging.info)
        session.cmd("dd if=/dev/zero of=/tmp/timer-test-file bs=1M count=100")
        return

    # Command to run to get the current time
    time_command = params["time_command"]
    # Filter which should match a string to be passed to time.strptime()
    time_filter_re = params["time_filter_re"]
    # Time format for time.strptime()
    time_format = params["time_format"]
    timerdevice_drift_threshold = params.get("timerdevice_drift_threshold", 3)

    error.context("Check the system time on guest and host", logging.info)
    (host_time, guest_time) = utils_test.get_time(session, time_command,
                                                  time_filter_re, time_format)
    drift = abs(float(host_time) - float(guest_time))
    if drift > timerdevice_drift_threshold:
        raise error.TestFail("The guest's system time is different with"
                             " host's. Host time: '%s', guest time:"
                             " '%s'" % (host_time, guest_time))

    get_hw_time_cmd = params.get("get_hw_time_cmd")
    if get_hw_time_cmd:
        error.context("Check the hardware time on guest and host", logging.info)
        host_time = utils.system_output(get_hw_time_cmd)
        guest_time = session.cmd(get_hw_time_cmd)
        drift = abs(float(host_time) - float(guest_time))
        if drift > timerdevice_drift_threshold:
            raise error.TestFail("The guest's hardware time is different with"
                                 " host's. Host time: '%s', guest time:"
                                 " '%s'" % (host_time, guest_time))

    if params.get("timerdevice_reboot_test") == "yes":
        sleep_time = params.get("timerdevice_sleep_time")
        if sleep_time:
            error.context("Sleep '%s' secs before reboot" % sleep_time,
                          logging.info)
            sleep_time = int(sleep_time)
            time.sleep(sleep_time)

        session = vm.reboot()
        error.context("Check the system time on guest and host", logging.info)
        (host_time, guest_time) = utils_test.get_time(session, time_command,
                                                  time_filter_re, time_format)
        drift = abs(float(host_time) - float(guest_time))
        if drift > timerdevice_drift_threshold:
            raise error.TestFail("The guest's system time is different with"
                                 " host's. Host time: '%s', guest time:"
                                 " '%s'" % (host_time, guest_time))

        get_hw_time_cmd = params.get("get_hw_time_cmd")
        if get_hw_time_cmd:
            error.context("Check the hardware time on guest and host", logging.info)
            host_time = utils.system_output(get_hw_time_cmd)
            guest_time = session.cmd(get_hw_time_cmd)
            drift = abs(float(host_time) - float(guest_time))
            if drift > timerdevice_drift_threshold:
                raise error.TestFail("The guest's hardware time is different with"
                                     " host's. Host time: '%s', guest time:"
                                     " '%s'" % (host_time, guest_time))
