import logging, re
from autotest.client.shared import error
from autotest.client.virt import kvm_monitor, utils_misc, storage


@error.context_aware
def run_block_resize(test, params, env):
    """
    KVM block resize test:

    1) Start guest with data image and check the data image size.
    2) Enlarge(or Decrease) the data image and check it in guest.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    def get_block_size(session, block_cmd, block_pattern):
        """
        Get block size inside guest.
        """
        output = session.cmd_output(block_cmd)
        block_size = re.findall(block_pattern, output)
        if block_size:
             if not re.search("[a-zA-Z]", block_size[0]):
                 return int(block_size[0])
             else:
                 return float(utils_misc.standard_value(block_size[0],
                                                        standard_unit="B"))
        else:
             raise error.TestError("Can not find the block size for the"
                                   " deivce. The output of command"
                                   " is: %s" % output)


    error.context("Check image size in guest", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session =  vm.wait_for_login(timeout=timeout)

    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    data_image_size = data_image_params.get("image_size")
    data_image_size = float(utils_misc.standard_value(data_image_size,
                                                standard_unit="B"))
    data_image_filename = storage.get_image_filename(data_image_params,
                                                     test.bindir)
    data_image_dev = vm.get_block({'file': data_image_filename})

    block_size_cmd = params.get("block_size_cmd")
    block_size_pattern = params.get("block_size_pattern")
    need_reboot = params.get("need_reboot", "no") == "yes"
    accept_ratio = float(params.get("accept_ratio", 0))

    block_size = get_block_size(session, block_size_cmd, block_size_pattern)
    if (block_size > data_image_size
        or block_size < data_image_size * (1 - accept_ratio)):
        raise error.TestError("Please check your system and image size check"
                              " command. The command output is not compatible"
                              " with the image size.")

    if params.get("guest_prepare_cmd"):
        session.cmd(params.get("guest_prepare_cmd"))

    disk_update_cmd = params.get("disk_update_cmd")
    if disk_update_cmd:
        disk_update_cmd = disk_update_cmd.split("::")

    block_size = data_image_size
    for index, ratio in enumerate(params.get("disk_change_ratio",
                                             "").strip().split()):
        old_block_size = block_size
        block_size = int(int(data_image_size) * float(ratio))
        if disk_update_cmd:
            if "DISK_CHANGE_SIZE" in disk_update_cmd[index]:
                disk_unit = params.get("disk_unit", "M")
                change_size = abs(block_size - old_block_size)
                change_size = utils_misc.standard_value("%sB" % change_size,
                                                        disk_unit)
                disk_update_cmd[index] = re.sub("DISK_CHANGE_SIZE",
                                                change_size.split(".")[0],
                                                disk_update_cmd[index])

        error.context("Change the disk size to %s" % block_size, logging.info)
        if block_size < old_block_size and disk_update_cmd:
            session.cmd(disk_update_cmd[index])
        tmp = vm.monitor.block_resize(data_image_dev, block_size)
        if need_reboot:
            session = vm.reboot(session=session)
        if block_size > old_block_size and disk_update_cmd:
            session.cmd(disk_update_cmd[index])

        current_size = get_block_size(session, block_size_cmd,
                                      block_size_pattern)
        if (current_size > block_size
            or current_size < block_size * (1 - accept_ratio)):
            raise error.TestFail("Guest reported a wrong disk size:\n"
                                 "    reported: %s\n"
                                 "    expect: %s\n" % (current_size,
                                                       block_size))
