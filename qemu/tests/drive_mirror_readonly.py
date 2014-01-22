import logging
from autotest.client.shared import error
from autotest.client.shared import utils
from qemu.tests import drive_mirror


@error.context_aware
def run_drive_mirror_readonly(test, params, env):
    """
    Test block mirroring functionality

    1). Set readonly bit for target image;
    2). boot vm, then mirror $source_image to target image;
    3). check no qemu monitor raise Exception and no active job;
    """
    tag = params.get("source_images", "image1")
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    error.context("Set readonly bit of target image", logging.info)
    utils.system("chattr +i %s" % mirror_test.target_image)
    try:
        try:
            mirror_test.start()
        except Exception, e:
            if "Permission denied" not in str(e):
                raise
            pass
        else:
            raise error.TestFail("Except qemu monitor raise Exception here")
        job = mirror_test.get_status()
        if job and job["type"] == "mirror":
            raise error.TestFail("Unexcept active mirror job found.")
    finally:
        error.context("Clean readonly bit of target image", logging.info)
        utils.system("chattr -i %s" % mirror_test.target_image)
        mirror_test.vm.destroy()
        mirror_test.clean()
