import logging
import time
from autotest.client.shared import error
from virttest import qemu_storage, data_dir, env_process
from qemu.tests import drive_mirror


@error.context_aware
def run_drive_mirror_complete(test, params, env):
    """
    Test block mirroring functionality

    1). boot vm, then mirror $source_image to $target_image
    2). wait for mirroring job go into ready status
    3). compare $source image and $target_image file
    4). reopen $target_image file if $open_target_image is 'yes'
    5). boot vm from $target_image , and check guest alive

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
        time.sleep(5)
        if params.get("open_target_image", "no") == "yes":
            mirror_test.reopen()
            device_id = mirror_test.vm.get_block({"file": target_image})
            if device_id != mirror_test.device:
                raise error.TestError("Mirrored image not being used by guest")
        error.context("Compare fully mirrored images", logging.info)
        qemu_img.compare_images(source_image, target_image)
        mirror_test.vm.resume()
        mirror_test.vm.destroy()
        if params.get("boot_target_image", "no") == "yes":
            params = params.object_params(tag)
            if params.get("target_image_type") == "iscsi":
                params["image_name"] = mirror_test.target_image
                params["image_raw_device"] = "yes"
            else:
                params["image_name"] = params["target_image"]
                params["image_format"] = params["target_format"]
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            vm = env.get_vm(params["main_vm"])
            timeout = int(params.get("login_timeout", 600))
            session = vm.wait_for_login(timeout=timeout)
            session.cmd(params.get("alive_check_cmd", "dir"), timeout=120)
            session.close()
            vm.destroy()
    finally:
        mirror_test.clean()
