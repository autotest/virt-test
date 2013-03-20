import logging, time
from autotest.client.shared import error
from autotest.client.virt import utils_misc
from autotest.client.tests.kvm.tests import block_copy

class BlockMirror(block_copy.BlockCopy):
    """
    base class for block mirror tests;
    """

    def __init__(self, test, params, env, tag):
        super(BlockMirror, self).__init__(test, params, env, tag)

    def parser_test_args(self):
        """
        paraser test args and set default value;
        """
        params = super(BlockMirror, self).parser_test_args()
        params["create_mode"] = params.get("create_mode", "absolute-path")
        params["target_format"] = params.get("target_format", "qcow2")
        params["reopen_timeout"] = int(params.get("reopen_timeout", 60))
        params["full_copy"] = params.get("full_copy", "").lower()
        cmd = params.get("block_mirror_cmd", "__com.redhat.drive-mirror")
        if cmd.startswith("__com.redhat"):
            params["full_copy"] = (params["full_copy"] == "full")
        return params

    @error.context_aware
    def start(self):
        """
        start block device mirroring job;
        """
        params = self.parser_test_args()
        target_image = params.get("target_image")
        default_speed = params.get("default_speed")
        full_copy = params.get("full_copy")
        create_mode = params.get("create_mode")
        target_format = params.get("target_format")

        error.context("start to mirror block device", logging.info)
        self.vm.block_mirror(self.device, target_image, default_speed,
                             full_copy, target_format, create_mode)
        time.sleep(0.5)
        started = self.get_status()
        if not started:
            raise error.TestFail("no active job found")

        self.trash.append(target_image)

    @error.context_aware
    def reopen(self):
        """
        reopen target image, then check if image file of the device is
        target images;
        """

        params = self.parser_test_args()
        target_image = params.get("target_image")
        target_format = params.get("target_format")
        reopen_timeout = params.get("reopen_timeout")

        def is_opened():
            if self.vm.monitor.protocol == "qmp":
                return self.vm.monitor.get_event("BLOCK_JOB_COMPLETED")
            device = self.vm.get_block({"file": target_image})
            return  device == self.device

        error.context("reopen new target image", logging.info)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_events()
        self.vm.block_reopen(self.device, target_image, target_format)
        opened = utils_misc.wait_for(is_opened, timeout=reopen_timeout,
                text="wait block job cancelled in %ss" % reopen_timeout)
        if not opened:
            raise error.TestFail("target image not opening")

    def is_steady(self):
        """
        check block device mirroring job is steady status or not;
        """
        event_ready = offset_ready = False
        if self.vm.monitor.protocol == "qmp":
            event_ready = self.vm.monitor.get_event("BLOCK_JOB_READY")
        info = self.get_status()
        offset_ready = bool(info) and (info["len"] == info["offset"])
        return event_ready or offset_ready

    def wait_for_steady(self):
        """
        check block device mirroring status, utils timeout; if still not go
        into steady status, raise TestFail exception;
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        steady =utils_misc.wait_for(self.is_steady, timeout=timeout)
        if not steady:
            raise error.TestFail("wait job goin ready status"
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
