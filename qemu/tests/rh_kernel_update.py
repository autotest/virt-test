import logging, re, time, os
from autotest.client.shared import error, utils
from virttest import utils_misc

def run_rh_kernel_update(test, params, env):
    """
    Update kernel from brewweb link(For internal usage):
    1) boot the vm
    2) verify the version of guest kernel
    3) use rpm -ivh to install the kernel
    4) check the grub configuration
    5) reboot the guest
    6) check the version of guest kernel

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def get_brew_url(mnt_path):
        # get the url from the brew mnt path
        url = "http://download.devel.redhat.com" + mnt_path[11:]
        logging.debug("Brew URL is %s" % url)
        return url

    def install_rpm_from_brew(session, url, upgrade=False):
        # install a package from brew
        if upgrade:
            # Upgrades or installs kernel to a newer version, then remove
            # old version.
            cmd = "rpm -Uvhf %s" % url
        else:
            cmd = "rpm -ivhf %s" % url
        s, o = session.cmd_status_output(cmd, timeout=600)
        if s != 0 and not "already" in o:
            raise error.TestFail("Fail to install %s:%s" % (url, o))
        else:
            return True
        # FIXME: need to add the check for newer version

    def install_rpm_from_local(session, url, upgrade=False):
        rpm_name = os.path.basename(url)
        if url.startswith("http"):
            download_cmd = "wget %s" % url
            utils.system_output(download_cmd)
            rpm_src = rpm_name
        else:
            rpm_src = utils_misc.get_path(test.bindir, url)
        vm.copy_files_to(rpm_src, "/tmp/%s" % rpm_name)
        install_rpm_from_brew(session, "/tmp/%s" % rpm_name, upgrade)


    def get_kernel_rpm_link():
        method = params.get("method", "link")
        if method == "link":
            return params.get("kernel_version"), params.get("kernel_rpm"),\
                              params.get("firmware_rpm")
        elif method == "brew":
            # fetch the newest packages from brew
            # FIXME: really brain dead method to fetch the kernel version
            #        kernel_vesion = re... + hint from configuration file
            #        is there any smart way to fetch the `uname -r` from
            #        brew build?
            rh_kernel_hint = "[\d+][^\s]+"
            kernel_re = params.get("kernel_re")
            tag = params.get("brew_tag")
            platform = params.get("platform")

            latest_pkg_cmd = "brew latest-pkg %s kernel" % tag
            o = utils.system_output(latest_pkg_cmd, timeout=360)
            build = re.findall("kernel[^\s]+", o)[0]
            logging.debug("Latest package on brew for tag %s is %s" %
                          (tag, build))

            buildinfo = utils.system_output("brew buildinfo %s" % build,
                                            timeout=360)

            # install kernel-firmware
            if "firmware" in buildinfo:
                logging.info("Found kernel-firmware")
                firmware_url = get_brew_url(re.findall(".*firmware.*",
                                                       buildinfo)[0])
            else:
                firmware_url = None

            kernel_url = get_brew_url(re.findall(kernel_re % rh_kernel_hint,
                                              buildinfo, re.I)[0])

            debug_re = kernel_re % ("(%s)" % rh_kernel_hint)
            kernel_version = re.findall(debug_re, kernel_url, re.I)[0]
            kernel_version += "." + params.get("kernel_suffix", "")
            return kernel_version, kernel_url, firmware_url
        else:
            raise error.TestError("Unknown installation method %s" % method)

    def get_guest_kernel_version():
        s, o = session.cmd_status_output("uname -r")
        return o.strip()

    def virtio_driver_installed():
        s, o = session.cmd_status_output("lsmod | grep virtio")
        for driver in virtio_drivers:
            if driver not in o:
                logging.debug("%s have not been installed." % driver)
                return False
            else:
                logging.debug("%s have already been installed." % driver)
        return True

    def check_kernel_version(kernel_version, guest_version):
        # return True: when kernel_version <= guest_version
        if guest_version == kernel_version:
            logging.info("The kernel version is matched %s" % guest_version)
            return True
        else:
            kernel_s = re.split('[.-]', kernel_version)
            guest_s = re.split('[.-]', guest_version)
            kernel_v = [int(i) for i in kernel_s if i.isdigit()]
            guest_v = [int(i) for i in guest_s if i.isdigit()]
            for i in range(min(len(kernel_v),len(guest_v))):
                if kernel_v[i] < guest_v[i]:
                    logging.info("The kernel_version: %s is old than guest_version"
                                 "%s" % (kernel_version, guest_version))
                    return True
                elif kernel_v[i] > guest_v[i]:
                    return False
            if len(kernel_v) < len(guest_v):
                logging.info("The kernel_version: %s is old than guest_version"
                             "%s" % (kernel_version, guest_version))
                return True
        return False


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    kernel_version, kernel_rpm, firmware_rpm = get_kernel_rpm_link()
    install_virtio = params.get("install_virtio", "yes")
    verify_virtio = params.get("verify_virtio", "yes")
    args_removed = params.get("args_removed", "").split()
    args_added = params.get("args_added", "").split()
    restore_initrd_cmd = ""
    virtio_drivers = ["virtio", "virtio_ring", "virtio_pci", "virtio_net",
                      "virtio_blk"]

    logging.info("Kernel version:  %s" % kernel_version)
    logging.info("Kernel rpm    :  %s" % kernel_rpm)
    logging.info("Firmware rpm  :  %s" % firmware_rpm)

    grub_cfg_path = "/boot/grub/grub.conf"
    cp_grubcf_cmd = "/bin/cp %s %s-bk" %(grub_cfg_path, grub_cfg_path)
    restore_grubcf_cmd = "/bin/cp %s-bk %s" %(grub_cfg_path, grub_cfg_path)
    count = 0

    try:
        # backup grub.cfg file
        s, o = session.cmd_status_output(cp_grubcf_cmd)
        if s != 0:
            logging.error(o)
            raise error.TestError("Fail to backup the grub.cfg")
        else:
            count = 1

        # judge if need to install a new kernel
        ifupdatekernel = True
        logging.info("Verifying the version of guest kernel ...")
        guest_version = get_guest_kernel_version()
        if check_kernel_version(kernel_version, guest_version):
            ifupdatekernel = False
            # set kernel_version to current version for later step to use
            kernel_version = guest_version
            if install_virtio == "no":
                logging.info("No need install virtio driver,"
                             "try to update kernel arguments")
            elif virtio_driver_installed():
                install_virtio = "no"
                logging.info("Virtio driver has been installed,"
                             "try to update kernel arguments")
            else:
                logging.info("Lack the driver of virtio, need install it")
        else:
            logging.info("The guest kerenl is %s but expected is %s" %
                         (guest_version, kernel_version))
            if params.get("install_rpm_from_local") == "yes":
                if firmware_rpm is not None:
                    logging.info("Installing guest kernel firmware ...")
                    install_rpm_from_local(session, firmware_rpm, upgrade=True)
                logging.info("Installing guest kernel ...")
                status = install_rpm_from_local(session, kernel_rpm)
            else:
                if firmware_rpm is not None:
                    logging.info("Installing guest kernel firmware ...")
                    install_rpm_from_brew(session, firmware_rpm, upgrade=True)
                logging.info("Installing guest kernel ...")
                status = install_rpm_from_brew(session, kernel_rpm)
            if status == True:
                count = 2
            # back grub.cfg after install a new kernel
            s, o = session.cmd_status_output(cp_grubcf_cmd)
            if s != 0:
                logging.error(o)
                raise error.TestError("Fail to backup the grub.cfg after"
                                      " update kernel")

        kernel_path = "/boot/vmlinuz-%s" % kernel_version

        if install_virtio == "yes":
            logging.info("Installing virtio driver ...")

            initrd_prob_cmd = "grubby --info=%s" % kernel_path
            s, o = session.cmd_status_output(initrd_prob_cmd)
            if s != 0:
                logging.error(o)
                raise error.TestFail("Could not get the kernel information")
            initrd_path = re.findall("initrd=(.*)", o)[0]
            mkinitrd_cmd = "mkinitrd -f %s " % initrd_path
            mkinitrd_cmd += "".join([ "--with=%s " % driver for driver in
                                      virtio_drivers])
            mkinitrd_cmd += " %s" % kernel_version
            cp_initrd_cmd = "/bin/cp %s %s-bk" % (initrd_path, initrd_path)
            restore_initrd_cmd = "/bin/cp %s-bk %s" % (initrd_path,
                                                       initrd_path)

            # backup initrd file
            s, o = session.cmd_status_output(cp_initrd_cmd, timeout=200)
            if s != 0:
                logging.error(o)
            # update initrd file
            s, o = session.cmd_status_output(mkinitrd_cmd, timeout=200)
            if s != 0:
                logging.error(o)
                raise error.TestFail("Error found during virtio "
                                     "driver installation")
            else:
                count = 3

        # make sure the newly installed kernel as default
        if ifupdatekernel:
            logging.info("Make the new installed kernel as default ...")
            make_def_cmd = "grubby --set-default=%s " % kernel_path
            s, o = session.cmd_status_output(make_def_cmd)
            if s != 0:
                logging.error(o)
                raise error.TestError("Fail to set %s as default kernel" %
                                      kernel_path)
            else:
                count = 4
            s, o = session.cmd_status_output(cp_grubcf_cmd)
            if s != 0:
                logging.error(o)
                raise error.TestError("Fail to backup the grub.cfg after set"
                                      "new installed kernel as default")

        # remove or add the required arguments

        logging.info("Update the kernel cmdline ...")
        update_kernel_cmd = "grubby --update-kernel=%s " % kernel_path
        update_kernel_cmd += "".join(["--remove-args=%s " % arg for arg in
                                 args_removed])
        update_kernel_cmd += "--args=\"%s\""\
                              % " ".join([ arg for arg in args_added])
        s, o = session.cmd_status_output(update_kernel_cmd)
        if s != 0:
            logging.error(o)
            raise error.TestError("Fail to modify the kernel cmdline")
        else:
            count = 5
        # reboot guest
        logging.info("Rebooting ...")
        time.sleep(int(params.get("sleep_before_reset", 10)))
        session = vm.reboot(session, 'shell', timeout=login_timeout)
        # check if the guest can bootup normally after kernel update
        logging.info("Verifying the guest kernel version ...")
        guest_version = get_guest_kernel_version()
        if guest_version != kernel_version:
            raise error.TestFail("Fail to verify the guest kernel, \n"
                                 "Expceted version %s \n"
                                 "In fact version %s \n" %
                                 (kernel_version, guest_version))

        if verify_virtio == "yes":
            logging.info("Verifying the virtio drivers ...")
            if not virtio_driver_installed():
                raise error.TestFail("Fail to verify the installation of"
                                     " virtio drivers.")
    except Exception, e:
        if count == 4 or count == 3 or count == 1:
            # restore grub.cfg
            s, o = session.cmd_status_output(restore_grubcf_cmd, timeout=100)
            if s != 0:
                logging.error(o)
            raise error.TestFail(e)
        elif count == 2:
            # restore initrd file
            if restore_initrd_cmd:
                s, o = session.cmd_status_output(restore_initrd_cmd,
                                                 timeout=200)
            if s != 0:
                logging.error(o)
            raise error.TestFail(e)
