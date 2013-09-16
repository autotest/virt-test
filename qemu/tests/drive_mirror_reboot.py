from qemu.tests import drive_mirror


def run_drive_mirror_reboot(test, params, env):
    """
    drive_mirror_reboot test:
    1). boot guest, do system_reset
    2). start mirroring, wait go into steady status
    3). reopen new image then reboot guest
    4). check guest alive

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_images", "image1")
    reboot_test = drive_mirror.DriveMirror(test, params, env, tag)
    try:
        reboot_test.reboot("system_reset", False)
        reboot_test.start()
        reboot_test.action_when_steady()
        reboot_test.action_after_reopen()
    finally:
        reboot_test.clean()
