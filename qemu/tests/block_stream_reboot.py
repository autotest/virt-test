import logging
from autotest.client.shared import error, utils
from qemu.tests import blk_stream

class BlockStreamReboot(blk_stream.BlockStream):

    process = []

    def __init__(self, test, params, env, tag):
        super(BlockStreamReboot, self).__init__(test, params, env, tag)


    @error.context_aware
    def start_reset(self):
        """
        Reset guest with system_reset in loop;
        """
        error.context("reset guest in loop", logging.info)
        count = 0
        while True:
            self.reboot(method="system_reset", boot_check=False)
            count +=1
            status = self.get_status()
            # if block stream job really started, stop reset loop
            if status.get("offset", 0) > 0:
                break
        logging.info("has reset %s times, when start stream job" % count)


    def action_before_start(self):
        """
        start pre-action in new threads;
        """
        params = self.parser_test_args()
        for param in params.get("before_start").split():
            if hasattr(self, param):
                fun = getattr(self, param)
                bg = utils.InterruptedThread(fun)
                bg.start()
                if bg.isAlive():
                    self.process.append(bg)


    def clean(self):
        """
        clean up sub-process and trash files
        """
        for bg in self.process:
            bg.join()
        super(BlockStreamReboot, self).clean()


def run_block_stream_reboot(test, params, env):
    """
    block_stream_reboot test:
    1). boot up vm and create snapshots;
    2). reboot guest, then start block steam job;
    3). destroy live vm and create it, then start block stream job(optonal);
    4). after stream done, then reboot guest and check it's alived

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    reboot_test = BlockStreamReboot(test, params, env, tag)
    try:
        reboot_test.action_before_start()
        reboot_test.create_snapshots()
        reboot_test.start()
        reboot_test.action_after_finished()
    finally:
        reboot_test.clean()
