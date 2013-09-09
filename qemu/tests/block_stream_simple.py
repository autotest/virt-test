import logging
from autotest.client.shared import error
from qemu.tests import blk_stream


class BlockStreamSimple(blk_stream.BlockStream):

    def __init__(self, test, params, env, tag):
        super(BlockStreamSimple, self).__init__(test, params, env, tag)

    @error.context_aware
    def query_status(self):
        """
        query running block streaming job info;
        """
        error.context("query job status", logging.info)
        if not self.get_status():
            raise error.TestFail("No active job")


def run_block_stream_simple(test, params, env):
    """
    block_stream_simple test:
    1). launch block streaming job w/o set max speed
    2). reset max job speed before steady status(optional)
    3). cancel active job on the device(optional)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    simple_test = BlockStreamSimple(test, params, env, tag)
    try:
        simple_test.create_snapshots()
        simple_test.start()
        simple_test.action_when_streaming()
        simple_test.action_after_finished()
    finally:
        simple_test.clean()
