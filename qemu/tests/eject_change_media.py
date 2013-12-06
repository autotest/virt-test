import logging
import time
from autotest.client.shared import error
from virttest import utils_misc, utils_test


@error.context_aware
def run_eject_change_media(test, params, env):
    """
    Eject change a removable media:
    1) Boot VM with QMP/human monitor enabled.
    2) Connect to QMP/human monitor server.
    3) Eject original cdrom.
    4) Eject original cdrom for second time.
    5) Insert new image to cdrom.
    6) Eject device after add new image by change command.
    7) Insert original cdrom to cdrom.
    8) Eject media of locked cdrom. (Linux only)
    9) Try to eject non-removable device w/o force option.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    def eject_media(vm, device_id, media_file, force=False):
        """
        Eject cdrom media via monitor(qmp or human);

        :param vm: qemu vm object;
        :param device_id: device ID;
        :param media_file: file path of device drive;
        :param force: eject media with force option or not;
        :return: bool type;
        """
        def is_ejected():
            """
            Check is media file is ejected;
            """
            block_info = str(vm.monitor.info("block"))
            return not (media_file and media_file in block_info)

        eject_cmd = ["eject"]
        if vm.monitor.protocol == "qmp":
            eject_cmd.append("device=%s" % device_id)
            if force:
                eject_cmd.append(",force=True")
        elif vm.monitor.protocol == "human":
            if force:
                eject_cmd.append("-f")
            eject_cmd.append(device_id)
        eject_cmd = " ".join(eject_cmd)
        vm.monitor.send_args_cmd(eject_cmd)
        ejected = utils_misc.wait_for(is_ejected, timeout=10)
        if ejected is None:
            logging.debug("Ejecte media for '%s' timeout in 10s" % device_id)
        return bool(ejected)

    def change_media(vm, device_id, media_file):
        """
        Change media in cdrom to media_file;

        :param vm: qemu vm object;
        :param device_id: device ID;
        :param media_file: file path of device drive;
        :return: bool type;
        """
        def is_changed():
            block_info = str(vm.monitor.info("block"))
            return (not media_file or media_file in block_info)

        change_cmd = "change device=%s,target=%s" % (device_id, media_file)
        vm.monitor.send_args_cmd(change_cmd)
        changed = utils_misc.wait_for(is_changed, timeout=10)
        if changed is None:
            logging.debug("Change media of cdrom device timeout in 10s")
        return bool(changed)

    def check_block_locked(vm, device_id):
        """
        Check if block is locked;

        :param vm: qemu vm object;
        :param device_id: device ID;
        :return: bool type;
        """
        block_info = vm.monitor.info("block")
        if isinstance(block_info, str):
            lock_str = "locked=1"
            for block in block_info.splitlines():
                if device_id in block and lock_str in block:
                    return True
        else:
            for block in block_info:
                if block['device'] == device_id and block['locked']:
                    return True
        return False

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    new_img_name = params["new_img_name"]
    target_cdrom = params["target_cdrom"]
    orig_img_name = params[target_cdrom]
    pre_cmd = params.get("pre_cmd")
    if pre_cmd:
        post_cmd = params["post_cmd"]
        session.cmd(pre_cmd)
    p_dict = {"file": orig_img_name}
    device_name = vm.get_block(p_dict)
    if device_name is None:
        msg = "Fail to get device using image %s" % orig_img_name
        raise error.TestFail(msg)

    repeat_times = int(params.get("repeat_times", 0))
    if repeat_times:
        error.context("Repeat eject/change media %s times" % repeat_times,
                      logging.info)
        for i in range(1, repeat_times + 1, 1):
            ejected = eject_media(vm, device_name, orig_img_name)
            if not ejected:
                msg = "Fail to eject media %s," % orig_img_name
                msg += " in loop %s" % i
                raise error.TestFail(msg)
            time.sleep(0.5)
            changed = change_media(vm, device_name, new_img_name)
            if not changed:
                msg = "Fail to changed media to %s" % new_img_name
                msg += " in loop %s" % i
                raise error.TestFail(msg)
            orig_img_name, new_img_name = new_img_name, orig_img_name
            logging.info("Repeat eject/change media %s times" % i)
            time.sleep(0.5)

    error.context("Eject media %s" % new_img_name, logging.info)
    ejected = eject_media(vm, device_name, new_img_name)
    if not ejected:
        raise error.TestFail("Fail to eject device %s" % device_name)

    error.context("Force eject media again", logging.info)
    ejected = eject_media(vm, device_name, None, True)
    if not ejected:
        raise error.TestFail("Fail to force eject device %s" % device_name)

    error.context("Chanage media to %s" % orig_img_name, logging.info)
    changed = change_media(vm, device_name, orig_img_name)
    if not changed:
        raise error.TestFail("Fail to change media to %s" % orig_img_name)

    error.context("Check cdrom door not locked", logging.info)
    if check_block_locked(vm, device_name):
        raise error.TestFail("Unused device is locked.")

    mount_cmd = params.get("mount_cdrom_cmd")
    if mount_cmd:
        error.context("Try to eject locked media", logging.info)
        cdrom = utils_test.get_readable_cdroms(params, session)[0]
        mount_cmd = mount_cmd % cdrom
        umount_cmd = params["umount_cdrom_cmd"] % cdrom
        (status, output) = session.cmd_status_output(mount_cmd, timeout=360)
        if status:
            msg = "Unable to mount cdrom. command: %s\n" % mount_cmd
            msg += "Output: %s" % output
            raise error.TestError(msg)
        if not check_block_locked(vm, device_name):
            raise error.TestFail("device is not locked " +
                                 "after mount it in guest.")
        try:
            eject_media(vm, device_name, orig_img_name)
        except Exception, e:
            if "is locked" not in str(e):
                raise error.TestFail("Got a invaild Exception (%s)" % e)
            pass
        else:
            raise error.TestFail("Expect a Exception like: " +
                                 "'%s' is clocked" % device_name)

    if params.get("eject_nonremovable_device"):
        error.context("Try to eject non-removable device", logging.info)
        p_dict = {"removable": False}
        device_name = vm.get_block(p_dict)
        force_eject = params.get("force_eject", "no") == "yes"
        if device_name is None:
            raise error.TestError("Could not find non-removable device")
        try:
            eject_media(vm, device_name, orig_img_name, force_eject)
        except Exception, e:
            if "'%s' is not removable" % device_name not in str(e):
                raise error.TestFail("Get a invaild Exception (%s)" % e)
            pass
        else:
            err_msg = "Ejected a non-removable device %s " % device_name
            err_msg += "Expect a Exception like:"
            err_msg += "'%s' is not removable" % device_name
            raise error.TestFail(err_msg)

    if session:
        if mount_cmd:
            session.cmd(umount_cmd)
        if pre_cmd:
            session.cmd(post_cmd)
        session.close()
