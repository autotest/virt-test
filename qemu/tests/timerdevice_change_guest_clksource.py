import logging
import re
from autotest.client.shared import error
from virttest import data_dir, storage, utils_disk, env_process


@error.context_aware
def run(test, params, env):
    """
    Timer device check guest after update kernel line without kvmclock:

    1) Boot a guest with kvm-clock
    2) Check the current clocksource in guest
    3) Check the available clocksource in guest
    4) Update "clocksource=" parameter in guest kernel cli
    5) Boot guest system
    6) Check the current clocksource in guest

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    def verify_guest_clock_source(session, expected):
        error.context("Check the current clocksource in guest", logging.info)
        cmd = "cat /sys/devices/system/clocksource/"
        cmd += "clocksource0/current_clocksource"
        if not expected in session.cmd(cmd):
            raise error.TestFail(
                "Guest didn't use '%s' clocksource" % expected)

    error.context("Boot a guest with kvm-clock", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    error.context("Check the current clocksource in guest", logging.info)
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
            logging.warn("Update the first kernel entry to"
                         " kvm-clock only")
            kernel_cfg = re.findall(kernel_cfg_pattern,
                                    kernel_cfg_original)[0]
        except IndexError, detail:
            raise error.TestError("Couldn't find the kernel config, regex"
                                  " pattern is '%s', detail: '%s'" %
                                  (kernel_cfg_pattern, detail))

        if "clocksource=" in kernel_cfg:
            kernel_cfg_new = re.sub("clocksource=[a-z\- ]+", " ", kernel_cfg)
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

    error.context("Check the available clocksource in guest", logging.info)
    cmd = "cat /sys/devices/system/clocksource/"
    cmd += "clocksource0/available_clocksource"
    try:
        available_clksrc_list = session.cmd(cmd).splitlines()[-1].split()
        available_clksrc_list = [_.strip() for _ in available_clksrc_list]
    except Exception, detail:
        raise error.TestFail("Couldn't get guest available clock source."
                             " Detail: '%s'" % detail)

    try:
        for clksrc in available_clksrc_list:
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
                kernel_cfg_new = re.sub("clocksource=[a-z \-_]+",
                                        "clocksource=%s " % clksrc, kernel_cfg)
            else:
                kernel_cfg_new = "%s %s" % (kernel_cfg,
                                            "clocksource=%s" % clksrc)
            disk_obj.replace_image_file_content(grub_file, kernel_cfg,
                                                kernel_cfg_new)

            error.context("Boot the guest", logging.info)
            if clksrc != "kvm-clock":
                cpu_model_flags = params.get("cpu_model_flags")
                if "-kvmclock" not in cpu_model_flags:
                    params["cpu_model_flags"] = cpu_model_flags + ",-kvmclock"
            vm_name = params["main_vm"]
            env_process.preprocess_vm(test, params, env, vm_name)
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            session = vm.wait_for_login(timeout=timeout)

            error.context("Check the current clocksource in guest",
                          logging.info)
            verify_guest_clock_source(session, clksrc)
    finally:
        try:
            error.context("Shutdown guest")
            vm.destroy()
            error.context("Restore guest kernel cli", logging.info)
            image_filename = storage.get_image_filename(params,
                                                        data_dir.get_data_dir())
            grub_file = params.get("grub_file", "/boot/grub2/grub.cfg")
            kernel_cfg_pattern = params.get("kernel_cfg_pos_reg",
                                            r".*vmlinuz-\d+.*")

            disk_obj = utils_disk.GuestFSModiDisk(image_filename)
            kernel_cfg_original = disk_obj.read_file(grub_file)
            try:
                kernel_cfg = re.findall(kernel_cfg_pattern,
                                        kernel_cfg_original)[0]
            except IndexError, detail:
                raise error.TestError("Couldn't find the kernel config, regex"
                                      " pattern is '%s', detail: '%s'" %
                                      (kernel_cfg_pattern, detail))

            if "clocksource=" in kernel_cfg:
                kernel_cfg_new = re.sub(
                    "clocksource=[a-z \-_]+", " ", kernel_cfg)
                disk_obj.replace_image_file_content(grub_file, kernel_cfg,
                                                    kernel_cfg_new)
        except Exception, detail:
            logging.error("Failed to restore guest kernel cli."
                          " Detail: '%s'" % detail)
