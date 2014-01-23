import logging
from virttest import env_process
from autotest.client.shared import error
from qemu.tests import drive_mirror_stress


class DriveMirrorPowerdown(drive_mirror_stress.DriveMirrorStress):

    def __init__(self, test, params, env, tag):
        super(DriveMirrorPowerdown, self).__init__(test, params, env, tag)

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
        bootup guest with target image;
        """
        params = self.parser_test_args()
        vm_name = params['main_vm']
        self.params["image_name"] = params["target_image"]
        self.params["image_format"] = params["target_format"]
        logging.info("Target image: %s" % self.target_image)
        error.context("powerup vm with target image", logging.info)
        env_process.preprocess_vm(self.test, self.params, self.env, vm_name)
        vm = self.env.get_vm(vm_name)
        vm.verify_alive()
        self.vm = vm


def run(test, params, env):
    """
    drive_mirror_powerdown test:
    1). boot guest, do kernel build
    3). mirror boot disk to target image
    4). wait mirroring go into ready status then quit qemu
    5). bootup guest with target image
    6). check guest can response correctly

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
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
