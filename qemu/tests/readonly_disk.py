import logging
import re
from autotest.client.shared import error
from virttest import aexpect, env_process


@error.context_aware
def run_readonly_disk(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest with virtio data disk
    2) Format the disk and copy file to it
    3) Stop the guest and boot up it again with the data disk set to readonly
    4) Try to copy file to the data disk
    5) Try to copy file from the data disk

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error.context("Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    create_partition_cmd = params.get("create_partition_cmd")
    format_cmd = params.get("format_cmd")
    copy_cmd = params.get("copy_cmd")
    src_file = params.get("src_file")
    disk_letter = params.get("disk_letter")

    # update the cdrom letter for winutils
    cdrom_chk_cmd = "echo list volume > cmd && echo exit >>"
    cdrom_chk_cmd += " cmd && diskpart /s cmd"

    vols = re.findall("\s+([A-Z])\s+.*CDFS.*\n",
                      session.cmd_output(cdrom_chk_cmd))
    if vols:
        src_file = re.sub("WIN_UTIL", vols[0], src_file)
    else:
        raise error.TestError("Can not find winutils in guest.")

    filen = 0
    error.context("Format the disk and copy file to it", logging.info)
    session.cmd(create_partition_cmd)
    session.cmd(format_cmd)
    dst_file = disk_letter + ":\\" + str(filen)
    session.cmd(copy_cmd % (src_file, dst_file))
    filen += 1

    msg = "Stop the guest and boot up it again with the data disk"
    msg += " set to readonly"
    error.context(msg, logging.info)
    session.close()
    vm.destroy()
    data_img = params.get("images").split()[-1]
    params["image_readonly_%s" % data_img] = "yes"
    params["force_create_image_%s" % data_img] = "no"
    env_process.preprocess(test, params, env)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    try:
        error.context("Try to write to the readonly disk", logging.info)
        dst_file_readonly = disk_letter + ":\\" + str(filen)
        session.cmd(copy_cmd % (src_file, dst_file_readonly))
        raise error.TestFail("Write in readonly disk should failed.")
    except aexpect.ShellCmdError:
        error.context("Try to read from the readonly disk", logging.info)
        session.cmd(copy_cmd % (dst_file, "C:\\"))

    session.close()
