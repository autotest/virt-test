import logging
from autotest.client.shared import error
from virttest import utils_misc
from qemu.tests import blk_stream


class BlockStreamCheckBackingfile(blk_stream.BlockStream):

    def __init__(self, test, params, env, tag):
        super(BlockStreamCheckBackingfile, self).__init__(test,
                                                          params, env, tag)

    @error.context_aware
    def check_backingfile(self):
        """
        check no backingfile found after stream job done via qemu-img info;
        """
        fail = False
        error.context("Check image file backing-file", logging.info)
        backingfile = self.get_backingfile("qemu-img")
        if backingfile:
            img_file = self.get_image_file()
            logging.debug("Got backing-file: %s" % backingfile +
                          "by 'qemu-img info %s'" % img_file)
            fail |= bool(backingfile)
        backingfile = self.get_backingfile("monitor")
        if backingfile:
            logging.debug("Got backing-file: %s" % backingfile +
                          "by 'info/query block' " +
                          "in %s monitor" % self.vm.monitor.protocol)
            fail |= bool(backingfile)
        if fail:
            msg = ("Unexpected backing file found, there should be "
                   "no backing file")
            raise error.TestFail(msg)

    @error.context_aware
    def check_imagefile(self):
        """
        verify current image file is expected image file
        """
        params = self.parser_test_args()
        exp_img_file = params["expected_image_file"]
        exp_img_file = utils_misc.get_path(self.data_dir, exp_img_file)
        error.context("Check image file is '%s'" % exp_img_file, logging.info)
        img_file = self.get_image_file()
        if exp_img_file != img_file:
            msg = "Excepted image file: %s," % exp_img_file
            msg += "Actual image file: %s" % img_file
            raise error.TestFail(msg)


def run_block_stream_check_backingfile(test, params, env):
    """
    block_stream.check_backingfile test:
    1). boot up vm and create snapshots;
    2). start block steam job, then wait block job done;
    3). check backing-file in monitor and qemu-img command;
    4). verify image file is excepted image file;
    5). vierfy guest is alive;

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    backingfile_test = BlockStreamCheckBackingfile(test, params, env, tag)
    try:
        backingfile_test.create_snapshots()
        backingfile_test.start()
        backingfile_test.action_after_finished()
    finally:
        backingfile_test.clean()
