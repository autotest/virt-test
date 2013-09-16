import logging
import time
import re
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import virt_vm, utils_misc, qemu_storage, data_dir


class EnospcConfig(object):

    """
    Performs setup for the test enospc. This is a borg class, similar to a
    singleton. The idea is to keep state in memory for when we call cleanup()
    on postprocessing.
    """
    __shared_state = {}

    def __init__(self, test, params):
        self.__dict__ = self.__shared_state
        root_dir = test.bindir
        self.tmpdir = test.tmpdir
        self.qemu_img_binary = params['qemu_img_binary']
        if not os.path.isfile(self.qemu_img_binary):
            self.qemu_img_binary = utils_misc.get_qemu_img_binary(params)
        self.raw_file_path = os.path.join(self.tmpdir, 'enospc.raw')
        # Here we're trying to choose fairly explanatory names so it's less
        # likely that we run in conflict with other devices in the system
        self.vgtest_name = params["vgtest_name"]
        self.lvtest_name = params["lvtest_name"]
        self.lvtest_device = "/dev/%s/%s" % (
            self.vgtest_name, self.lvtest_name)
        image_dir = os.path.join(data_dir.get_data_dir(),
                                 os.path.dirname(params["image_name"]))
        self.qcow_file_path = os.path.join(image_dir, 'enospc.qcow2')
        try:
            getattr(self, 'loopback')
        except AttributeError:
            self.loopback = ''

    @error.context_aware
    def setup(self):
        logging.debug("Starting enospc setup")
        error.context("performing enospc setup")
        utils_misc.display_attributes(self)
        # Double check if there aren't any leftovers
        self.cleanup()
        try:
            utils.run("%s create -f raw %s 10G" %
                      (self.qemu_img_binary, self.raw_file_path))
            # Associate a loopback device with the raw file.
            # Subject to race conditions, that's why try here to associate
            # it with the raw file as quickly as possible
            l_result = utils.run("losetup -f")
            utils.run("losetup -f %s" % self.raw_file_path)
            self.loopback = l_result.stdout.strip()
            # Add the loopback device configured to the list of pvs
            # recognized by LVM
            utils.run("pvcreate %s" % self.loopback)
            utils.run("vgcreate %s %s" % (self.vgtest_name, self.loopback))
            # Create an lv inside the vg with starting size of 200M
            utils.run("lvcreate -L 200M -n %s %s" %
                      (self.lvtest_name, self.vgtest_name))
            # Create a 10GB qcow2 image in the logical volume
            utils.run("%s create -f qcow2 %s 10G" %
                      (self.qemu_img_binary, self.lvtest_device))
            # Let's symlink the logical volume with the image name that autotest
            # expects this device to have
            os.symlink(self.lvtest_device, self.qcow_file_path)
        except Exception:
            try:
                self.cleanup()
            except Exception, e:
                logging.warn(e)
            raise

    @error.context_aware
    def cleanup(self):
        error.context("performing enospc cleanup")
        if os.path.islink(self.lvtest_device):
            utils.run("fuser -k %s" % self.lvtest_device, ignore_status=True)
            time.sleep(2)
        l_result = utils.run("lvdisplay")
        # Let's remove all volumes inside the volume group created
        if self.lvtest_name in l_result.stdout:
            utils.run("lvremove -f %s" % self.lvtest_device)
        # Now, removing the volume group itself
        v_result = utils.run("vgdisplay")
        if self.vgtest_name in v_result.stdout:
            utils.run("vgremove -f %s" % self.vgtest_name)
        # Now, if we can, let's remove the physical volume from lvm list
        if self.loopback:
            p_result = utils.run("pvdisplay")
            if self.loopback in p_result.stdout:
                utils.run("pvremove -f %s" % self.loopback)
        l_result = utils.run('losetup -a')
        if self.loopback and (self.loopback in l_result.stdout):
            try:
                utils.run("losetup -d %s" % self.loopback)
            except error.CmdError:
                logging.error("Failed to liberate loopback %s", self.loopback)
        if os.path.islink(self.qcow_file_path):
            os.remove(self.qcow_file_path)
        if os.path.isfile(self.raw_file_path):
            os.remove(self.raw_file_path)


@error.context_aware
def run_enospc(test, params, env):
    """
    ENOSPC test

    1) Create a virtual disk on lvm
    2) Boot up guest with two disks
    3) Continually write data to second disk
    4) Check images and extend second disk when no space
    5) Continue paused guest
    6) Repeat step 3~5 several times

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    error.context("Create a virtual disk on lvm")
    enospc_config = EnospcConfig(test, params)
    enospc_config.setup()

    error.context("Boot up guest with two disks")
    vm = env.get_vm(params["main_vm"])
    vm.create()
    login_timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)

    vgtest_name = params["vgtest_name"]
    lvtest_name = params["lvtest_name"]
    logical_volume = "/dev/%s/%s" % (vgtest_name, lvtest_name)

    drive_format = params["drive_format"]
    if drive_format == "virtio":
        devname = "/dev/vdb"
    elif drive_format == "ide":
        output = session_serial.cmd_output("dir /dev")
        devname = "/dev/" + re.findall("([sh]db)\s", output)[0]
    elif drive_format == "scsi":
        devname = "/dev/sdb"
    cmd = params["background_cmd"]
    cmd %= devname

    error.context("Continually write data to second disk")
    logging.info("Sending background cmd '%s'", cmd)
    session_serial.sendline(cmd)

    iterations = int(params.get("repeat_time", 40))
    i = 0
    pause_n = 0
    while i < iterations:
        if vm.monitor.verify_status("paused"):
            pause_n += 1
            error.context("Checking all images in use by %s" % vm.name,
                          logging.info)
            for image_name in vm.params.objects("images"):
                image_params = vm.params.object_params(image_name)
                try:
                    image = qemu_storage.QemuImg(image_params,
                                                 data_dir.get_data_dir(), image_name)
                    image.check_image(image_params, data_dir.get_data_dir())
                except (virt_vm.VMError, error.TestWarn), e:
                    logging.error(e)
            error.context("Guest paused, extending Logical Volume size",
                          logging.info)
            try:
                utils.run("lvextend -L +200M %s" % logical_volume)
            except error.CmdError, e:
                logging.debug(e.result_obj.stdout)
            error.context("Continue paused guest", logging.info)
            vm.resume()
        elif not vm.monitor.verify_status("running"):
            status = str(vm.monitor.info("status"))
            raise error.TestError("Unexpected guest status: %s" % status)
        time.sleep(10)
        i += 1

    logging.info("Final %s", str(vm.monitor.info("status")))
    # Shutdown guest before remove the image on LVM.
    vm.destroy(gracefully=vm.monitor.verify_status("running"))
    try:
        enospc_config.cleanup()
    except Exception, e:
        logging.warn(e)

    if pause_n == 0:
        raise error.TestFail("Guest didn't pause during loop")
    else:
        logging.info("Guest paused %s times from %s iterations",
                     pause_n, iterations)
