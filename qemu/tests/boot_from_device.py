import logging
import re
import os
from autotest.client import utils
from virttest import utils_misc, data_dir
from autotest.client.shared import error, iscsi


@error.context_aware
def run_boot_from_device(test, params, env):
    """
    QEMU boot from device:

    1) Start guest from device(hd/usb/scsi-hd)
    2) Check the boot result
    3) Log into the guest if it's up
    4) Shutdown the guest if it's up

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def create_cdroms():
        """
        Create 'test' cdrom with one file on it
        """

        logging.info("creating test cdrom")
        cdrom_test = params.get("cdrom_test")
        cdrom_test = utils_misc.get_path(data_dir.get_data_dir(), cdrom_test)
        utils.run("dd if=/dev/urandom of=test bs=10M count=1")
        utils.run("mkisofs -o %s test" % cdrom_test)
        utils.run("rm -f test")

    def cleanup_cdroms():
        """
        Removes created cdrom
        """

        logging.info("cleaning up temp cdrom images")
        cdrom_test = utils_misc.get_path(
            data_dir.get_data_dir(), params.get("cdrom_test"))
        os.remove(cdrom_test)

    def preprocess_remote_storage():
        """
        Prepare remote ISCSI storage for block image, and login session for
        iscsi device.
        """

        iscsidevice = iscsi.Iscsi(params)
        iscsidevice.login()
        device_name = iscsidevice.get_device_name()
        if not device_name:
            iscsidevice.logout()
            raise error.TestError("Fail to get iscsi device name")

    def postprocess_remote_storage():
        """
        Logout from target.
        """

        iscsidevice = iscsi.Iscsi(params)
        iscsidevice.logout()

    def cleanup(dev_name):
        if dev_name == "scsi-cd":
            cleanup_cdroms()
        elif dev_name == "iscsi-dev":
            postprocess_remote_storage()

    def check_boot_result(boot_fail_info, device_name):
        """
        Check boot result, and logout from iscsi device if boot from iscsi.
        """

        logging.info("Wait for display and check boot info.")
        infos = boot_fail_info.split(';')
        f = lambda: re.search(infos[0], vm.serial_console.get_output())
        utils_misc.wait_for(f, timeout, 1)

        logging.info("Try to boot from '%s'" % device_name)
        try:
            if dev_name == "hard-drive" or (dev_name == "scsi-hd" and not
                                            params.get("image_name_stg")):
                error.context("Log into the guest to verify it's up",
                              logging.info)
                session = vm.wait_for_login(timeout=timeout)
                session.close()
                vm.destroy()
                return

            output = vm.serial_console.get_output()

            for i in infos:
                if not re.search(i, output):
                    raise error.TestFail("Could not boot from"
                                         " '%s'" % device_name)
        finally:
            cleanup(device_name)

    dev_name = params.get("dev_name")
    if dev_name == "scsi-cd":
        create_cdroms()
        vm = env.get_vm(params["main_vm"])
        vm.create()
    elif dev_name == "iscsi-dev":
        preprocess_remote_storage()
        vm = env.get_vm(params["main_vm"])
        vm.create()
    else:
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    boot_menu_key = params.get("boot_menu_key", 'f12')
    boot_menu_hint = params.get("boot_menu_hint")
    boot_fail_info = params.get("boot_fail_info")
    boot_device = params.get("boot_device")

    if boot_device:
        f = lambda: re.search(boot_menu_hint, vm.serial_console.get_output())
        if not utils_misc.wait_for(f, timeout, 1):
            cleanup(dev_name)
            raise error.TestFail("Could not get boot menu message. "
                                 "Excepted Result: '%s'" % boot_menu_hint)

        # Send boot menu key in monitor.
        vm.send_key(boot_menu_key)

        output = vm.serial_console.get_output()
        boot_list = re.findall("^\d+\. (.*)\s", output, re.M)

        if not boot_list:
            cleanup(dev_name)
            raise error.TestFail("Could not get boot entries list.")

        logging.info("Got boot menu entries: '%s'", boot_list)
        for i, v in enumerate(boot_list, start=1):
            if re.search(boot_device, v, re.I):
                logging.info("Start guest from boot entry '%s'" % boot_device)
                vm.send_key(str(i))
                break
        else:
            raise error.TestFail("Could not get any boot entry match "
                                 "pattern '%s'" % boot_device)

    check_boot_result(boot_fail_info, dev_name)
