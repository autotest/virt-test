import logging
import time
from autotest.client.shared import error
from virttest import qemu_storage, data_dir
from qemu.tests import drive_mirror


@error.context_aware
def run_drive_mirror_continuous_backup(test, params, env):
    """
    1) Synchronize disk and then do continuous backup

    "qemu-img compare" is used to verify disk is mirrored successfully.
    """
    tag = params.get("source_images", "image1")
    qemu_img = qemu_storage.QemuImg(params, data_dir.get_data_dir(), tag)
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    tmp_dir = params.get("tmp_dir", "c:\\")
    clean_cmd = params.get("clean_cmd", "del /f /s /q tmp*.file")
    dd_cmd = "dd if=/dev/zero bs=1024 count=1024 of=tmp%s.file"
    dd_cmd = params.get("dd_cmd", dd_cmd)
    try:
        source_image = mirror_test.get_image_file()
        target_image = mirror_test.get_target_image()
        mirror_test.start()
        mirror_test.wait_for_steady()
        error.context("Testing continuous backup")
        session = mirror_test.get_session()
        session.cmd("cd %s" % tmp_dir)
        for fn in range(0, 128):
            session.cmd(dd_cmd % fn)
        time.sleep(10)
        mirror_test.vm.pause()
        time.sleep(5)
        error.context("Compare original and backup images", logging.info)
        mirror_test.vm.resume()
        session = mirror_test.get_session()
        session.cmd(clean_cmd)
        session.cmd("cd %s" % tmp_dir)
        qemu_img.compare_images(source_image, target_image)
        mirror_test.vm.destroy()
    finally:
        mirror_test.clean()
