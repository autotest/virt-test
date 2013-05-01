import logging, re, time, os
from autotest.client.shared import error, utils
from virttest import utils_misc

@error.context_aware
def run_rh_kernel_update(test, params, env):
    """
    Update kernel from brewweb link(For internal usage):
    1) Boot the vm
    2) Get latest kernel package link from brew
    3) Verify the version of guest kernel
    4) Compare guest kernel version and brew's
    5) Backup grub.cfg file
    6) Install guest kernel firmware (Optional)
    7) Install guest kernel
    8) Backup grub.cfg after installing new kernel
    9) Installing virtio driver (Optional)
    10) Backup initrd file
    11) Update initrd file
    12) Make the new installed kernel as default
    13) Backup grup.cfg after setting new kernel as default
    14) Update the guest kernel cmdline (Optional)
    15) Reboot guest after updating kernel
    16) Verifying the virtio drivers (Optional)

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_brew_url(mnt_path):
        # get the url from the brew mnt path
        url = "http://download.devel.redhat.com" + mnt_path[11:]
        logging.debug("Brew URL is %s" % url)
        return url


    def install_rpm(session, url, upgrade=False):
        # install a package from brew
        cmd = "rpm -ivhf %s" % url
        if upgrade:
            # Upgrades or installs kernel to a newer version, then remove
            # old version.
            cmd = "rpm -Uvhf %s" % url
        s, o = session.cmd_status_output(cmd, timeout=600)
        if s != 0 and ("already" not in o):
            raise error.TestFail("Fail to install %s:%s" % (url, o))

        return True
        # FIXME: need to add the check for newer version


    def copy_and_install_rpm(session, url, upgrade=False):
        rpm_name = os.path.basename(url)
        if url.startswith("http"):
            download_cmd = "wget %s" % url
            utils.system_output(download_cmd)
            rpm_src = rpm_name
        else:
            rpm_src = utils_misc.get_path(test.bindir, url)
        vm.copy_files_to(rpm_src, "/tmp/%s" % rpm_name)
        install_rpm(session, "/tmp/%s" % rpm_name, upgrade)


    def get_kernel_rpm_link():
        method = params.get("method", "link")
        if method not in ["link", "brew"]:
            raise error.TestError("Unknown installation method %s" % method)

        if method == "link":
            return (params.get("kernel_version"),
                    params.get("kernel_rpm"),
                    params.get("firmware_rpm"))

        error.context("Get latest kernel package link from brew", logging.info)
        # fetch the newest packages from brew
        # FIXME: really brain dead method to fetch the kernel version
        #        kernel_vesion = re... + hint from configuration file
        #        is there any smart way to fetch the `uname -r` from
        #        brew build?
        rh_kernel_hint = "[\d+][^\s]+"
        kernel_re = params.get("kernel_re")
        tag = params.get("brew_tag")

        latest_pkg_cmd = "brew latest-pkg %s kernel" % tag
        o = utils.system_output(latest_pkg_cmd, timeout=360)
        build = re.findall("kernel[^\s]+", o)[0]
        logging.debug("Latest package on brew for tag %s is %s" %
                      (tag, build))

        buildinfo = utils.system_output("brew buildinfo %s" % build,
                                        timeout=360)

        # install kernel-firmware
        firmware_url = None
        if "firmware" in buildinfo:
            logging.info("Found kernel-firmware")
            fw_pattern = ".*firmware.*"
            try:
                fw_brew_link = re.findall(fw_pattern, buildinfo)[0]
            except IndexError:
                raise error.TestError("Could not get kernel-firmware package"
                              " brew link matching pattern '%s'" % fw_pattern)
            firmware_url = get_brew_url(fw_brew_link)

        knl_pattern = kernel_re % rh_kernel_hint
        try:
            knl_brew_link = re.findall(knl_pattern, buildinfo, re.I)[0]
        except IndexError:
            raise error.TestError("Could not get kernel package brew link"
                                  " matching pattern '%s'" % knl_pattern)
        kernel_url = get_brew_url(knl_brew_link)

        debug_re = kernel_re % ("(%s)" % rh_kernel_hint)
        try:
            kernel_version = re.findall(debug_re, kernel_url, re.I)[0]
        except IndexError:
            raise error.TestError("Could not get kernel version matching"
                                  " pattern '%s'" % debug_re)
        kernel_version += "." + params.get("kernel_suffix", "")

        return kernel_version, kernel_url, firmware_url


    def get_guest_kernel_version():
        error.context("Verify the version of guest kernel", logging.info)
        s, o = session.cmd_status_output("uname -r")
        return o.strip()


    def is_virtio_driver_installed():
        s, o = session.cmd_status_output("lsmod | grep virtio")
        if s != 0:
            return False

        for driver in virtio_drivers:
            if driver not in o:
                logging.debug("%s has not been installed." % driver)
                return False
            logging.debug("%s has already been installed." % driver)

        return True


    def compare_kernel_version(kernel_version, guest_version):
        error.context("Compare guest kernel version and brew's", logging.info)
        # return True: when kernel_version <= guest_version
        if guest_version == kernel_version:
            logging.info("The kernel version is matched %s" % guest_version)
            return True

        kernel_s = re.split('[.-]', kernel_version)
        guest_s = re.split('[.-]', guest_version)
        kernel_v = [int(i) for i in kernel_s if i.isdigit()]
        guest_v = [int(i) for i in guest_s if i.isdigit()]
        for i in range(min(len(kernel_v), len(guest_v))):
            if kernel_v[i] < guest_v[i]:
                logging.debug("The kernel version: '%s' is old than"
                         " guest version %s" % (kernel_version, guest_version))
                return True
            elif kernel_v[i] > guest_v[i]:
                return False

        if len(kernel_v) < len(guest_v):
            logging.debug("The kernel_version: %s is old than guest_version"
                         " %s" % (kernel_version, guest_version))
            return True

        return False


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    install_virtio = params.get("install_virtio", "yes")
    verify_virtio = params.get("verify_virtio", "yes")
    args_removed = params.get("args_removed", "").split()
    args_added = params.get("args_added", "").split()
    restore_initrd_cmd = ""
    virtio_drivers = params.get("virtio_drivers_list", "").split()
    kernel_version, kernel_rpm, firmware_rpm = get_kernel_rpm_link()

    logging.info("Kernel version:  %s" % kernel_version)
    logging.info("Kernel rpm    :  %s" % kernel_rpm)
    logging.info("Firmware rpm  :  %s" % firmware_rpm)

    grub_cfg_path = "/boot/grub/grub.conf"
    cp_grubcf_cmd = "/bin/cp %s %s-bk" %(grub_cfg_path, grub_cfg_path)
    restore_grubcf_cmd = "/bin/cp %s-bk %s" %(grub_cfg_path, grub_cfg_path)
    count = 0

    try:
        error.context("Backup grub.cfg file")
        s, o = session.cmd_status_output(cp_grubcf_cmd)
        if s != 0:
            logging.error(o)
            raise error.TestError("Fail to backup the grub.cfg")
        count = 1

        # judge if need to install a new kernel
        ifupdatekernel = True
        guest_version = get_guest_kernel_version()
        if compare_kernel_version(kernel_version, guest_version):
            ifupdatekernel = False
            # set kernel_version to current version for later step to use
            kernel_version = guest_version
            if is_virtio_driver_installed():
                install_virtio = "no"
        else:
            logging.info("The guest kerenl is %s but expected is %s" %
                         (guest_version, kernel_version))

            rpm_install_func = install_rpm
            if params.get("install_rpm_from_local") == "yes":
                rpm_install_func = copy_and_install_rpm

            if firmware_rpm:
                error.context("Install guest kernel firmware", logging.info)
                rpm_install_func(session, firmware_rpm, upgrade=True)
            error.context("Install guest kernel", logging.info)
            status = rpm_install_func(session, kernel_rpm)
            if status:
                count = 2

            error.context("Backup grub.cfg after installing new kernel",
                          logging.info)
            s, o = session.cmd_status_output(cp_grubcf_cmd)
            if s != 0:
                msg = ("Fail to backup the grub.cfg after updating kernel,"
                       " guest output: '%s'" % o)
                logging.error(msg)
                raise error.TestError(msg)


        kernel_path = "/boot/vmlinuz-%s" % kernel_version

        if install_virtio == "yes":
            error.context("Installing virtio driver", logging.info)

            initrd_prob_cmd = "grubby --info=%s" % kernel_path
            s, o = session.cmd_status_output(initrd_prob_cmd)
            if s != 0:
                msg = ("Could not get guest kernel information,"
                       " guest output: '%s'" % o)
                logging.error(msg)
                raise error.TestError(msg)

            try:
                initrd_path = re.findall("initrd=(.*)", o)[0]
            except IndexError:
                raise error.TestError("Could not get initrd path from guest,"
                                      " guest output: '%s'" % o)

            driver_list = ["--with=%s " % drv for drv in virtio_drivers]
            mkinitrd_cmd = "mkinitrd -f %s " % initrd_path
            mkinitrd_cmd += "".join(driver_list)
            mkinitrd_cmd += " %s" % kernel_version
            cp_initrd_cmd = "/bin/cp %s %s-bk" % (initrd_path, initrd_path)
            restore_initrd_cmd = "/bin/cp %s-bk %s" % (initrd_path,
                                                       initrd_path)

            error.context("Backup initrd file")
            s, o = session.cmd_status_output(cp_initrd_cmd, timeout=200)
            if s != 0:
                logging.error("Failed to backup guest initrd,"
                              " guest output: '%s'", o)

            error.context("Update initrd file", logging.info)
            s, o = session.cmd_status_output(mkinitrd_cmd, timeout=200)
            if s != 0:
                msg = "Failed to install virtio driver, guest output '%s'" % o
                logging.error(msg)
                raise error.TestFail(msg)

            count = 3

        # make sure the newly installed kernel as default
        if ifupdatekernel:
            error.context("Make the new installed kernel as default",
                          logging.info)
            make_def_cmd = "grubby --set-default=%s " % kernel_path
            s, o = session.cmd_status_output(make_def_cmd)
            if s != 0:
                msg = ("Fail to set %s as default kernel,"
                       " guest output: '%s'" % (kernel_path, o))
                logging.error(msg)
                raise error.TestError(msg)

            count = 4
            error.context("Backup grup.cfg after setting new kernel as default")
            s, o = session.cmd_status_output(cp_grubcf_cmd)
            if s != 0:
                msg = ("Fail to backup the grub.cfg, guest output: '%s'" % o)
                logging.error(msg)
                raise error.TestError(msg)

        # remove or add the required arguments

        error.context("Update the guest kernel cmdline", logging.info)
        remove_args_list = ["--remove-args=%s " % arg for arg in args_removed]
        update_kernel_cmd = "grubby --update-kernel=%s " % kernel_path
        update_kernel_cmd += "".join(remove_args_list)
        update_kernel_cmd += '--args="%s"' % " ".join(args_added)
        s, o = session.cmd_status_output(update_kernel_cmd)
        if s != 0:
            msg = "Fail to modify the kernel cmdline, guest output: '%s'" % o
            logging.error(msg)
            raise error.TestError(msg)

        count = 5

        # reboot guest
        error.context("Reboot guest after updating kernel", logging.info)
        time.sleep(int(params.get("sleep_before_reset", 10)))
        session = vm.reboot(session, 'shell', timeout=login_timeout)
        # check if the guest can bootup normally after kernel update
        guest_version = get_guest_kernel_version()
        if guest_version != kernel_version:
            raise error.TestFail("Fail to verify the guest kernel, \n"
                                 "Expceted version %s \n"
                                 "In fact version %s \n" %
                                 (kernel_version, guest_version))

        if verify_virtio == "yes":
            error.context("Verifying the virtio drivers", logging.info)
            if not is_virtio_driver_installed():
                raise error.TestFail("Fail to verify the installation of"
                                     " virtio drivers")
    except Exception:
        if count in [4, 3, 1]:
            # restore grub.cfg
            s, o = session.cmd_status_output(restore_grubcf_cmd, timeout=100)
            if s != 0:
                logging.error("Failed to execute cmd '%s' in guest,"
                              " guest output: '%s'", restore_grubcf_cmd, o)
        elif count == 2 and restore_initrd_cmd:
            # restore initrd file
            s, o = session.cmd_status_output(restore_initrd_cmd, timeout=200)
            if s != 0:
                logging.error("Failed to execute cmd '%s' in guest,"
                              " guest output: '%s'", restore_initrd_cmd, o)

        raise
