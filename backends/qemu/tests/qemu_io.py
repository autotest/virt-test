import os
import re
import logging
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import aexpect, utils_misc, data_dir


class QemuIOConfig(object):

    """
    Performs setup for the test qemu_io. This is a borg class, similar to a
    singleton. The idea is to keep state in memory for when we call cleanup()
    on postprocessing.
    """
    __shared_state = {}

    def __init__(self, test, params):
        self.__dict__ = self.__shared_state
        root_dir = test.bindir
        self.tmpdir = test.tmpdir
        self.qemu_img_binary = params.get('qemu_img_binary')
        if not os.path.isfile(self.qemu_img_binary):
            self.qemu_img_binary = utils_misc.get_path(os.path.join(root_dir,
                                                       params.get("vm_type")),
                                                       self.qemu_img_binary)
        self.raw_files = ["stg1.raw", "stg2.raw"]
        self.raw_files = map(lambda f: os.path.join(self.tmpdir, f),
                             self.raw_files)
        # Here we're trying to choose fairly explanatory names so it's less
        # likely that we run in conflict with other devices in the system
        self.vgtest_name = params.get("vgtest_name", "vg_kvm_test_qemu_io")
        self.lvtest_name = params.get("lvtest_name", "lv_kvm_test_qemu_io")
        self.lvtest_device = "/dev/%s/%s" % (
            self.vgtest_name, self.lvtest_name)
        try:
            getattr(self, 'loopback')
        except AttributeError:
            self.loopback = []

    @error.context_aware
    def setup(self):
        error.context("performing setup", logging.debug)
        utils_misc.display_attributes(self)
        # Double check if there aren't any leftovers
        self.cleanup()
        try:
            for f in self.raw_files:
                utils.run("%s create -f raw %s 10G" %
                          (self.qemu_img_binary, f))
                # Associate a loopback device with the raw file.
                # Subject to race conditions, that's why try here to associate
                # it with the raw file as quickly as possible
                l_result = utils.run("losetup -f")
                utils.run("losetup -f %s" % f)
                loopback = l_result.stdout.strip()
                self.loopback.append(loopback)
                # Add the loopback device configured to the list of pvs
                # recognized by LVM
                utils.run("pvcreate %s" % loopback)
            loopbacks = " ".join(self.loopback)
            utils.run("vgcreate %s %s" % (self.vgtest_name, loopbacks))
            # Create an lv inside the vg with starting size of 200M
            utils.run("lvcreate -L 19G -n %s %s" %
                      (self.lvtest_name, self.vgtest_name))
        except Exception:
            try:
                self.cleanup()
            except Exception, e:
                logging.warn(e)
            raise

    @error.context_aware
    def cleanup(self):
        error.context("performing qemu_io cleanup", logging.debug)
        if os.path.isfile(self.lvtest_device):
            utils.run("fuser -k %s" % self.lvtest_device)
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
        p_result = utils.run("pvdisplay")
        l_result = utils.run('losetup -a')
        for l in self.loopback:
            if l in p_result.stdout:
                utils.run("pvremove -f %s" % l)
            if l in l_result.stdout:
                try:
                    utils.run("losetup -d %s" % l)
                except error.CmdError, e:
                    logging.error("Failed to liberate loopback %s, "
                                  "error msg: '%s'", l, e)

        for f in self.raw_files:
            if os.path.isfile(f):
                os.remove(f)


def run(test, params, env):
    """
    Run qemu_iotests.sh script:
    1) Do some qemu_io operations(write & read etc.)
    2) Check whether qcow image file is corrupted

    :param test:   QEMU test object
    :param params: Dictionary with the test parameters
    :param env:    Dictionary with test environment.
    """

    test_type = params.get("test_type")
    qemu_io_config = None
    if test_type == "lvm":
        qemu_io_config = QemuIOConfig(test, params)
        qemu_io_config.setup()

    test_script = os.path.join(data_dir.get_root_dir(),
                               'shared/scripts/qemu_iotests.sh')
    logging.info("Running script now: %s" % test_script)
    test_image = params.get("test_image", "/tmp/test.qcow2")
    s, test_result = aexpect.run_fg("sh %s %s" % (test_script,
                                                  test_image),
                                    logging.debug, timeout=1800)

    err_string = {
        "err_nums": "\d errors were found on the image.",
        "an_err": "An error occurred during the check",
        "unsupt_err": "This image format does not support checks",
        "mem_err": "Not enough memory",
        "open_err": "Could not open",
        "fmt_err": "Unknown file format",
        "commit_err": "Error while committing image",
        "bootable_err": "no bootable device",
    }

    try:
        for err_type in err_string.keys():
            msg = re.findall(err_string.get(err_type), test_result)
            if msg:
                raise error.TestFail(msg)
    finally:
        try:
            if qemu_io_config:
                qemu_io_config.cleanup()
        except Exception, e:
            logging.warn(e)
