import logging
from virttest import storage, data_dir
from autotest.client.shared import error, utils
import drive_mirror_stress

class BlockMirrorPowerdown(drive_mirror_stress.BlockMirrorStress):

    @error.context_aware
    def powerdown(self):
        """
        power down guest via quit qemu;
        """
        error.context("powerdown vm", logging.info)
        return self.vm.destroy()

    @error.context_aware
    def powerup(self):
        """
        bootup guest with target image, same as reopen new image;
        steps are:
        1). backup base image, move target image as base image
        2). bootup guest with target image;
        """
        params = self.params.object_params(self.tag)
        target_image = params.get("target_image")
        image_file = storage.get_image_filename(params, data_dir.get_data_dir())
        self.params["image_file"] = image_file
        cmd = "mv -f %s %s-bak && " % (image_file, image_file)
        cmd += "ln -sf %s %s " % (target_image, image_file)
        error.context("powerup vm with target image", logging.info)
        utils.system(cmd)
        logging.info("use target as image file")
        self.vm.create()

    def clean(self):
        super(BlockMirrorPowerdown, self).clean()
        cmd = "rm -f %s && " % self.params["image_file"]
        cmd += "mv %s-bak %s" % (self.params["image_file"],
                                 self.params["image_file"])
        utils.system(cmd)

def run_drive_mirror_powerdown(test, params, env):
    """
    drive_mirror_powerdown test:
    1). boot guest, do kernel build
    3). mirror disk to target image
    4). wait go into steady status, then quit qemu
    5). bootup guest with target image
    6). check guest can response correctly

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    powerdown_test = BlockMirrorPowerdown(test, params, env, tag)
    try:
        powerdown_test.action_before_start()
        powerdown_test.start()
        powerdown_test.action_when_steady()
        powerdown_test.powerup()
        powerdown_test.action_after_reopen()
    finally:
        powerdown_test.clean()
