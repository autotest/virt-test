import logging
import time
from autotest.client.shared import error
from virttest import utils_test, utils_misc


@error.context_aware
def run_change_media(test, params, env):
    """
    change a removable media:
    1) Boot VM with QMP/human monitor enabled.
    2) Connect to QMP/human monitor server.
    3) Check current block information.
    4) Insert some file to cdrom.
    5) Check current block information again.
    6) Mount cdrom to /mnt in guest to make it locked.
    7) Check current block information to make sure cdrom is locked.
    8) Change cdrom without force.
    9) Change a non-removable media.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    def check_block_locked(block_name):
        blocks_info = monitor.info("block")

        if isinstance(blocks_info, str):
            lock_str = "locked=1"
            for block in blocks_info.splitlines():
                if block_name in block and lock_str in block:
                    return True
        else:
            for block in blocks_info:
                if block['device'] == block_name and block['locked']:
                    return True
        return False

    def change_block(cmd=None):
        try:
            output = monitor.send_args_cmd(cmd)
        except Exception, err:
            output = str(err)
        return output

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    monitor = vm.get_monitors_by_type('qmp')
    if monitor:
        monitor = monitor[0]
    else:
        logging.warn("qemu does not support qmp. Human monitor will be used.")
        monitor = vm.monitor
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    logging.info("Wait until device is ready")
    time.sleep(10)

    cdrom = params.get("cdrom_cd1")
    device_name = vm.get_block({"file": cdrom})
    if device_name is None:
        msg = "Unable to detect qemu block device for cdrom %s" % cdrom
        raise error.TestError(msg)
    orig_img_name = params.get("orig_img_name")
    change_insert_cmd = "change device=%s,target=%s" % (device_name,
                                                        orig_img_name)
    monitor.send_args_cmd(change_insert_cmd)
    logging.info("Wait until device is ready")
    blocks_info = lambda: orig_img_name in str(monitor.info("block"))
    if not utils_misc.wait_for(blocks_info, 10):
        msg = "Fail to insert device %s to guest" % orig_img_name
        raise error.TestFail(msg)

    if check_block_locked(device_name):
        raise error.TestFail("Unused device is locked.")

    error.context("mount cdrom to make status to locked", logging.info)
    cdrom = utils_test.get_readable_cdroms(params, session)[0]
    mount_cmd = params.get("cd_mount_cmd") % cdrom
    (status, output) = session.cmd_status_output(mount_cmd, timeout=360)
    if status:
        msg = "Unable to mount cdrom. command: %s\nOutput: %s" % (mount_cmd,
                                                                  output)
        raise error.TestError(msg)

    if not check_block_locked(device_name):
        raise error.TestFail("device is not locked after mount it in guest.")

    error.context("Change media of cdrom", logging.info)
    new_img_name = params.get("new_img_name")
    change_insert_cmd = "change device=%s,target=%s" % (device_name,
                                                        new_img_name)
    output = change_block(change_insert_cmd)
    if "is locked" not in output:
        msg += "Device is not locked after 'change' the locked device."
        raise error.TestFail("Device is not locked")

    blocks_info = monitor.info("block")
    if orig_img_name not in str(blocks_info):
        raise error.TestFail("Locked device %s is changed!" % orig_img_name)

    error.context("Change no-removable device", logging.info)
    device_name = vm.get_block({"removable": False})
    if device_name is None:
        raise error.TestError("VM doesn't have any non-removable devices.")
    change_insert_cmd = "change device=%s,target=%s" % (device_name,
                                                        new_img_name)
    output = change_block(change_insert_cmd)
    if "is not removable" not in output:
        raise error.TestFail("Could remove non-removable device!")
    umount_cmd = params.get("cd_umount_cmd")
    if umount_cmd:
        session.cmd(umount_cmd, timeout=360)
    session.close()
