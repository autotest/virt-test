import logging
import time
from virttest import utils_misc, data_dir
from autotest.client.shared import error
from qemu.tests import block_copy


class BlockStream(block_copy.BlockCopy):

    """
    base class for block stream tests;
    """

    def __init__(self, test, params, env, tag):
        super(BlockStream, self).__init__(test, params, env, tag)

    def parser_test_args(self):
        params = super(BlockStream, self).parser_test_args()
        params["wait_finished"] = params.get("wait_finished", "yes").lower()
        return params

    @error.context_aware
    def start(self):
        """
        start block device streaming job;
        """
        params = self.parser_test_args()
        base_image = params.get("base_image")
        default_speed = params.get("default_speed")

        error.context("start to stream block device", logging.info)
        self.vm.block_stream(self.device, default_speed, base_image)
        time.sleep(0.5)
        status = self.get_status()
        if not status:
            raise error.TestFail("no active job found")
        msg = "block stream job running, "
        if default_speed:
            msg += "with limited speed %s B/s" % default_speed
        else:
            msg += "without limited speed"
        logging.info(msg)

    @error.context_aware
    def create_snapshots(self):
        """
        create live snapshot_chain, snapshots chain define in $snapshot_chain
        """
        params = self.parser_test_args()
        snapshots = params.get("snapshot_chain").split()
        format = params.get("snapshot_format", "qcow2")
        error.context("create live snapshots", logging.info)
        for sn in snapshots:
            sn = utils_misc.get_path(data_dir.get_data_dir(), sn)
            image_file = self.get_image_file()
            device = self.vm.live_snapshot(image_file, sn, format)
            if device != self.device:
                image_file = self.get_image_file()
                logging.info("expect file: %s\n opening file: %s" % (sn,
                                                                     image_file))
                raise error.TestFail("create live snapshot %s fail" % sn)
            self.trash.append(sn)

    def job_finished(self):
        """
        check if streaming job finished;
        """
        job_info = self.get_status()
        if job_info:
            return False
        if self.vm.monitor.protocol == "qmp":
            return bool(self.vm.monitor.get_event("BLOCK_JOB_COMPLETED"))
        return True

    def wait_for_finished(self):
        """
        waiting until block stream job finished
        """
        params = self.parser_test_args()
        timeout = params.get("wait_timeout")
        finished = utils_misc.wait_for(self.job_finished, step=1.0,
                                       timeout=timeout,
                                       text="wait job finshed in %ss" % timeout)
        if not finished:
            raise error.TestFail("Wait job finished timeout in %s" % timeout)
        logging.info("Block stream job done.")

    def action_before_start(self):
        """
        run steps before streaming start;
        """
        return self.do_steps("before_start")

    def action_when_streaming(self):
        """
        run steps when job in steaming;
        """
        return self.do_steps("when_streaming")

    def action_after_finished(self):
        """
        run steps after streaming done;
        """
        params = self.parser_test_args()
        # if block job cancelled, no need to wait it;
        if params["wait_finished"].lower() == "yes":
            self.wait_for_finished()
        return self.do_steps("after_finished")
