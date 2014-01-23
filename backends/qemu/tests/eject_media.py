import logging
import time
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    change a removable media:
    1) Boot VM with QMP/human monitor enabled.
    2) Connect to QMP/human monitor server.
    3) Eject original cdrom.
    4) Eject original cdrom for second time.
    5) Insert new image to cdrom.
    6) Eject device after add new image by change command.
    7) Insert original cdrom to cdrom.
    8) Try to eject non-removable device w/o force option.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    if not utils_misc.qemu_has_option("qmp"):
        logging.warn("qemu does not support qmp. Human monitor will be used.")
    qmp_used = False
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    logging.info("Wait until device is ready")
    time.sleep(10)
    blocks_info = vm.monitor.info("block")
    if isinstance(blocks_info, dict):
        qmp_used = True

    orig_img_name = params.get("cdrom_cd1")
    p_dict = {"file": orig_img_name}
    device_name = vm.get_block(p_dict)
    if device_name is None:
        msg = "Fail to get device using image %s" % orig_img_name
        raise error.TestFail(msg)
    error.context("Eject original device.")
    eject_cmd = "eject device=%s" % device_name
    vm.monitor.send_args_cmd(eject_cmd)
    logging.info("Wait until device is ejected")
    time.sleep(10)
    blocks_info = vm.monitor.info("block")
    if orig_img_name in str(blocks_info):
        raise error.TestFail("Fail to eject cdrom %s. " % orig_img_name)

    error.context("Eject original device for second time")
    vm.monitor.send_args_cmd(eject_cmd)

    new_img_name = params.get("new_img_name")
    error.context("Insert new image to device.")
    change_cmd = "change device=%s,target=%s" % (device_name, new_img_name)
    vm.monitor.send_args_cmd(change_cmd)
    logging.info("Wait until device changed")
    time.sleep(10)
    blocks_info = vm.monitor.info("block")
    if new_img_name not in str(blocks_info):
        raise error.TestFail("Fail to chang cdrom to %s." % new_img_name)
    if qmp_used:
        eject_cmd = "eject device=%s, force=True" % device_name
    else:
        eject_cmd = "eject device=%s" % device_name
    error.context("Eject device after add new image by change command")
    vm.monitor.send_args_cmd(eject_cmd)
    logging.info("Wait until new image is ejected")
    time.sleep(10)

    blocks_info = vm.monitor.info("block")
    if new_img_name in str(blocks_info):
        raise error.TestFail("Fail to eject cdrom %s." % orig_img_name)

    error.context("Insert %s to device %s" % (orig_img_name, device_name))
    change_cmd = "change device=%s,target=%s" % (device_name, orig_img_name)
    vm.monitor.send_args_cmd(change_cmd)
    logging.info("Wait until device changed")
    time.sleep(10)
    blocks_info = vm.monitor.info("block")
    if orig_img_name not in str(blocks_info):
        raise error.TestFail("Fail to change cdrom to %s." % orig_img_name)

    error.context("Try to eject non-removable device")
    p_dict = {"removable": False}
    device_name = vm.get_block(p_dict)
    if device_name is None:
        raise error.TestFail("Could not find non-removable device")
    if params.get("force_eject", "no") == "yes":
        if not qmp_used:
            eject_cmd = "eject -f %s " % device_name
    else:
        eject_cmd = "eject device=%s," % device_name
    try:
        vm.monitor.send_args_cmd(eject_cmd)
    except Exception, e:
        logging.debug("Catch exception message: %s" % e)
    logging.info("Wait until device is ejected")
    time.sleep(10)
    blocks_info = vm.monitor.info("block")
    if device_name not in str(blocks_info):
        raise error.TestFail("Could remove non-removable device!")

    session.close()
