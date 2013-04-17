import time, random, logging
from autotest.client.shared import error, utils
from qemu.tests import drive_mirror

class BlockMirrorReboot(drive_mirror.BlockMirror):

    STOP = False

    def __init__(self, test, params, env, tag):
        super(BlockMirrorReboot, self).__init__(test, params, env, tag)

    @error.context_aware
    def start_reset(self):
        """
        Reset guest with system_reset in loop;
        """
        reboot_method = self.params.get("reboot_method", "system_reset")
        error.context("reset/restart guest in loop", logging.info)
        while not self.STOP:
            self.reboot(method=reboot_method)
            random_sleep =random.randint(3, 30)
            # Reboot continuously will make block device under heavy IO
            # status which will cause mirroring job no time slot become
            # ready, so sleep here to avoid this kind of case;
            logging.info("sleep %s s to wait guest bootup really",
                         random_sleep)
            time.sleep(random_sleep)
        return None

    @error.context_aware
    def stop_reset(self):
        """
        stop reset guest loop;
        """
        error.context("stop reset/restart guest loop", logging.info)
        self.STOP = True


def run_drive_mirror_reboot(test, params, env):
    """
    drive_mirror_reboot test:
    1). boot guest, do system_reset in loop
    2). start mirroring, wait go into steady status
    3). reopen new image and stop system_reset, then reboot guest
    4). check guest alive

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    reboot_test = BlockMirrorReboot(test, params, env, tag)
    try:
        bg = utils.InterruptedThread(reboot_test.start_reset)
        bg.start()
        reboot_test.start()
        reboot_test.action_when_steady()
        bg.join()
        reboot_test.action_after_reopen()
    finally:
        reboot_test.clean()
