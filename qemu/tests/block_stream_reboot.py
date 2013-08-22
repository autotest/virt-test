from autotest.client.shared import error, utils
from qemu.tests import blk_stream

class BlockStreamReboot(blk_stream.BlockStream):

    process = []

    def __init__(self, test, params, env, tag):
        super(BlockStreamReboot, self).__init__(test, params, env, tag)


    @error.context_aware
    def reboot(self):
        """
        Reset guest with system_reset;
        """
        params = self.parser_test_args()
        method = params.get("reboot_method", "system_reset")
        return super(BlockStreamReboot, self).reboot(method=method)


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
    1). boot guest, then reboot guest with system_reset;
    2). create snapshots and start stream job immediately;
    3). waiting stream done and check guest is alive;

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
