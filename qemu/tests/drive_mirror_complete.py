import logging
import time
from autotest.client.shared import error
from virttest import qemu_storage, data_dir
from qemu.tests import drive_mirror


@error.context_aware
def run_drive_mirror_complete(test, params, env):
    """
    Test block mirroring functionality

    1) Mirror the guest and switch to the mirrored one

    "qemu-img compare" is used to verify disk is mirrored successfully.
    """
    tag = params.get("source_images", "image1")
    qemu_img = qemu_storage.QemuImg(params, data_dir.get_data_dir(), tag)
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    try:
        source_image = mirror_test.get_image_file()
        target_image = mirror_test.get_target_image()
        mirror_test.start()
        mirror_test.wait_for_steady()
        mirror_test.vm.pause()
        mirror_test.reopen()
        device_id = mirror_test.vm.get_block({"file": target_image})
        if device_id != mirror_test.device:
            raise error.TestError("Mirrored image not being used by guest")
        time.sleep(5)
        error.context("Compare fully mirrored images", logging.info)
        qemu_img.compare_images(source_image, target_image)
        mirror_test.vm.destroy()
    finally:
        mirror_test.clean()
