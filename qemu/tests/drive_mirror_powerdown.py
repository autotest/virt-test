import logging
from virttest import storage, data_dir
from autotest.client.shared import error, utils
from qemu.tests import drive_mirror_stress

class DriveMirrorPowerdown(drive_mirror_stress.DriveMirrorStress):

    def __init__(self, test, params, env, tag):
        super(DriveMirrorPowerdown, self).__init__(test, params, env, tag)
        params = self.params.object_params(self.tag)
        image_file = storage.get_image_filename(params,
                data_dir.get_data_dir())
        self.params["image_file"] = image_file

    @error.context_aware
    def powerdown(self):
        """
        power down guest via quit qemu;
        """
        params = self.parser_test_args()
        error.context("powerdown vm", logging.info)
        self.vm.destroy()
        error.context("backup base image", logging.info)
        image_file = params.get("image_file")
        cmd = "mv %s %s-bak" % (image_file, image_file)
        utils.system(cmd)
        return

    @error.context_aware
    def powerup(self):
        """
        bootup guest with target image, same as reopen new image;
        steps are:
        1). backup base image, move target image as base image
        2). bootup guest with target image;
        """
        params = self.parser_test_args()
        image_file = params.get("image_file")
        target_image = params.get("target_image")
        cmd = "mv -f %s %s" % (target_image, image_file)
        error.context("copy target image")
        utils.system(cmd)
        error.context("powerup vm with target image", logging.info)
        self.vm.create()

    def clean(self):
        params = self.parser_test_args()
        image_file = params.get("image_file")
        super(DriveMirrorPowerdown, self).clean()
        cmd = "mv -f %s-bak %s" % (image_file, image_file)
        utils.system(cmd)

def run_drive_mirror_powerdown(test, params, env):
    """
    drive_mirror_powerdown test:
    1). boot guest, do kernel build
    3). mirror disk to target image
    4). wait go into steady status, then quit qemu
    5). bootup guest with target image
    6). check guest can response correctly

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    powerdown_test = DriveMirrorPowerdown(test, params, env, tag)
    try:
        powerdown_test.action_before_start()
        powerdown_test.start()
        powerdown_test.action_when_steady()
        powerdown_test.powerup()
        powerdown_test.action_after_reopen()
    finally:
        powerdown_test.clean()
