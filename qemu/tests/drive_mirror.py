import os
import logging
import time
from autotest.client.shared import error, utils
from virttest import utils_misc, storage, qemu_storage, nfs
from qemu.tests import block_copy


class DriveMirror(block_copy.BlockCopy):

    """
    base class for block mirror tests;
    """

    def __init__(self, test, params, env, tag):
        super(DriveMirror, self).__init__(test, params, env, tag)
        self.target_image = self.get_target_image()

    def parser_test_args(self):
        """
        paraser test args and set default value;
        """
        params = super(DriveMirror, self).parser_test_args()
        params["create_mode"] = params.get("create_mode", "absolute-path")
        params["target_format"] = params.get("target_format",
                                             params["image_format"])
        params["reopen_timeout"] = int(params.get("reopen_timeout", 60))
        params["full_copy"] = params.get("full_copy", "").lower()
        params["check_event"] = params.get("check_event", "no").lower()
        if params["block_mirror_cmd"].startswith("__"):
            params["full_copy"] = (params["full_copy"] == "full")
        return params

    def get_target_image(self):
        params = self.parser_test_args()
        t_params = {}
        t_params["image_name"] = params["target_image"]
        t_params["image_format"] = params["target_format"]
        target_image = storage.get_image_filename(t_params,
                                                  self.data_dir)
        if params.get("target_image_type") == "nfs":
            image = nfs.Nfs(params)
            image.setup()
            # sleep 30s to wait nfs ready, it's requried by some rhel6 host
            time.sleep(30)
        elif params.get("target_image_type") == "iscsi":
            image = qemu_storage.Iscsidev(params, self.data_dir, "")
            target_image = image.setup()
        if (params["create_mode"] == "existing" and
                not os.path.exists(target_image)):
            image = qemu_storage.QemuImg(t_params, self.data_dir, "")
            image.create(t_params)
        return target_image

    @error.context_aware
    def start(self):
        """
        start block device mirroring job;
        """
        params = self.parser_test_args()
        target_image = self.target_image
        device = self.device
        default_speed = params["default_speed"]
        target_format = params["target_format"]
        create_mode = params["create_mode"]
        full_copy = params["full_copy"]

        error.context("Start to mirror block device", logging.info)
        self.vm.block_mirror(device, target_image, default_speed,
                             full_copy, target_format, create_mode)
        time.sleep(0.5)
        started = self.get_status()
        if not started:
            raise error.TestFail("No active mirroring job found")
        self.trash.append(target_image)

    @error.context_aware
    def reopen(self):
        """
        reopen target image, then check if image file of the device is
        target images;
        """
        params = self.parser_test_args()
        target_format = params["target_format"]
        timeout = params["reopen_timeout"]

        def is_opened():
            device = self.vm.get_block({"file": self.target_image})
            ret = (device == self.device)
            if self.vm.monitor.protocol == "qmp":
                ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_COMPLETED"))
            return ret

        error.context("reopen new target image", logging.info)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
        self.vm.block_reopen(self.device, self.target_image, target_format)
        opened = utils_misc.wait_for(is_opened, first=3.0, timeout=timeout)
        if not opened:
            msg = "Target image not used,wait timeout in %ss" % timeout
            raise error.TestFail(msg)

    def is_steady(self):
        """
        check block device mirroring job is steady status or not;
        """
        params = self.parser_test_args()
        info = self.get_status()
        ret = (info["len"] == info["offset"])
        if self.vm.monitor.protocol == "qmp":
            if params.get("check_event", "no") == "yes":
                ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_READY"))
                return ret
        time.sleep(3.0)
        return ret

    def wait_for_steady(self):
        """
        check block device mirroring status, utils timeout; if still not go
        into steady status, raise TestFail exception;
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_READY")
        steady = utils_misc.wait_for(self.is_steady, step=3.0,
                                     timeout=timeout)
        if not steady:
            raise error.TestFail("Wait mirroring job ready "
                                 "timeout in %ss" % timeout)

    def action_before_start(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_start")

    def action_before_steady(self):
        """
        run steps before job in steady status;
        """
        return self.do_steps("before_steady")

    def action_when_steady(self):
        """
        run steps when job in steady status;
        """
        self.wait_for_steady()
        return self.do_steps("when_steady")

    def action_after_reopen(self):
        """
        run steps after reopened new target image;
        """
        return self.do_steps("after_reopen")

    def clean(self):
        params = self.parser_test_args()
        if params.get("target_image_type") == "iscsi":
            image = qemu_storage.Iscsidev(params, self.data_dir, "")
            # cleanup iscsi disk to ensure it works for other test
            utils.run("dd if=/dev/zero of=%s bs=1M count=512"
                      % self.target_image)
            image.cleanup()
        elif params.get("target_image_type") == "nfs":
            image = nfs.Nfs(params)
            image.cleanup()
        super(DriveMirror, self).clean()


def run_drive_mirror(test, params, env):
    pass
