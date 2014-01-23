import re
import logging
from autotest.client.shared import error, utils
from virttest import env_process, utils_misc
from qemu.tests import blk_stream


class BlockStreamTest(blk_stream.BlockStream):

    def get_image_size(self, image_file):
        qemu_img = utils_misc.get_qemu_img_binary(self.params)
        cmd = "%s info %s" % (qemu_img, image_file)
        info = utils.system_output(cmd)
        size = re.findall("(\d+) bytes", info)
        if size:
            return int(size[0])
        return 0


@error.context_aware
def run(test, params, env):
    """
    Test block streaming functionality.

    1) create live snapshot image sn1
    3) Request for block-stream
    4) Wait till the block job finishs
    5) Check for backing file in sn1
    6) Check for the size of the sn1 should not exceeds image.img
    """
    tag = params.get("source_images", "image1")
    stream_test = BlockStreamTest(test, params, env, tag)
    try:
        image_file = stream_test.get_image_file()
        image_size = stream_test.get_image_size(image_file)
        stream_test.create_snapshots()
        backingfile = stream_test.get_backingfile()
        if not backingfile:
            raise error.TestFail("Backing file is not available in the "
                                 "backdrive image")
        logging.info("Image file: %s" % stream_test.get_image_file())
        logging.info("Backing file: %s" % backingfile)
        stream_test.start()
        stream_test.wait_for_finished()
        backingfile = stream_test.get_backingfile()
        if backingfile:
            raise error.TestFail("Backing file is still available in the "
                                 "backdrive image")
        target_file = stream_test.get_image_file()
        target_size = stream_test.get_image_size(target_file)
        error.context("Compare image size", logging.info)
        if image_size < target_size:
            raise error.TestFail("Compare %s image, size of %s increased"
                                 "(%s -> %s)" % (image_file, target_file,
                                                 image_size, target_size))
        stream_test.verify_alive()
        stream_test.vm.destroy()
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        stream_test.vm = vm
        stream_test.verify_alive()
    finally:
        stream_test.clean()
