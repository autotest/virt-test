import logging
from autotest.client.shared import error
from qemu.tests import drive_mirror

class BlockMirrorSimple(drive_mirror.BlockMirror):

    def __init__(self, test, params, env, tag):
        super(BlockMirrorSimple, self).__init__(test, params, env, tag)

    @error.context_aware
    def query_status(self):
        """
        query runing block mirroring job info;
        """
        error.context("query job status", logging.info)
        if not self.get_status():
            raise error.TestFail("No active job")


def run_drive_mirror_simple(test, params, env):
    """
    drive_mirror_simple test:
    1). launch block mirroring job w/o max speed
    2). query job status on the device before steady status(optinal)
    3). reset max job speed before steady status(optional)
    4). cancel active job on the device before steady status(optional)

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    simple_test = BlockMirrorSimple(test, params, env, tag)
    try:
        simple_test.start()
        simple_test.action_before_steady()
    finally:
        simple_test.clean()
