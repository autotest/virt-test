import re, logging, time, random
from autotest.client.shared import error
from virttest import utils_misc, virt_vm, aexpect, storage, data_dir
from virttest import utils_test

@error.context_aware
def run_pci_hotplug_check(test, params, env):
    """
    Test hotplug of PCI devices and check the status in guest.
    1 Boot up a guest
    2 Hotplug virtio disk to the guest. Record the id and partition name of
      the disk in a list.
    3 Random choice a disk in the list. Unplug the disk and check the partition
      status.
    4 Hotpulg the disk back to guest with the same monitor cmdline and same id
      which is record in step 2.
    5 Check the partition status in guest. And confirm the disk with dd cmd
    6 Repeat step 3 to 5 for N times

    @param test:   QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env:    Dictionary with test environment.
    """
    def find_new_device(check_cmd, device_string, chk_timeout=5.0):
        end_time = time.time() + chk_timeout
        while time.time() < end_time:
            new_line = session.cmd_output(check_cmd)
            for line in re.split("\n+", new_line.strip()):
                dev_name = re.split("\s+", line.strip())[-1]
                if dev_name not in device_string:
                    return dev_name
            time.sleep(0.1)
        return None

    def find_del_device(check_cmd, device_string, chk_timeout=5.0):
        end_time = time.time() + chk_timeout
        while time.time() < end_time:
            new_line = session.cmd_output(check_cmd)
            for line in re.split("\n+", device_string.strip()):
                dev_name = re.split("\s+", line.strip())[-1]
                if dev_name not in new_line:
                    return dev_name
            time.sleep(0.1)
        return None


    # Select an image file
    def find_image(pci_num):
        image_params = params.object_params("%s" % img_list[pci_num + 1])
        o = storage.get_image_filename(image_params,data_dir.get_data_dir())
        return o

    def pci_add_block(pci_num, pci_id=None):
        image_filename = find_image(pci_num)
        pci_add_cmd = ("pci_add pci_addr=auto storage file=%s,if=%s" %
                       (image_filename, pci_model))
        return pci_add(pci_add_cmd, pci_id=pci_id)

    def pci_add(pci_add_cmd, pci_id=None):
        error.context("Adding pci device with command 'pci_add'")
        guest_devices = session.cmd_output(chk_cmd)
        add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        guest_device = find_new_device(chk_cmd, guest_devices)
        if pci_id is None:
            pci_info.append(['', '' , add_output, pci_model, guest_device])

        if not "OK domain" in add_output:
            raise error.TestFail("Add PCI device failed. "
                                 "Monitor command is: %s, Output: %r" %
                                 (pci_add_cmd, add_output))
        return  vm.monitor.info("pci")

    def check_support_device(dev):
        if vm.monitor.protocol == 'qmp':
            devices_supported = vm.monitor.human_monitor_cmd("%s ?" % cmd_type)
        else:
            devices_supported = vm.monitor.send_args_cmd("%s ?" % cmd_type)
        # Check if the device is support in qemu
        is_support = utils_test.find_substring(devices_supported, dev)
        if not is_support:
            raise error.TestError("%s doesn't support device: %s" %
                                  (cmd_type, dev))

    def device_add_block(pci_num, pci_id=None):
        if pci_id is not None:
            device_id = pci_type + "-" + pci_id
        else:
            device_id = pci_type + "-" + utils_misc.generate_random_id()
            pci_info.append([device_id, device_id])

        image_format = params.get("image_format_%s" % img_list[pci_num+1])
        if not image_format:
            image_format = params.get("image_format", "qcow2")
        image_filename = find_image(pci_num)

        pci_model = params.get("pci_model")
        controller_model = None
        if pci_model == "virtio":
            pci_model = "virtio-blk-pci"
        elif pci_model == "ide":
            pci_model = "ide-drive"

        if pci_model == "scsi":
            pci_model = "scsi-disk"
            controller_model = "lsi53c895a"
            check_support_device(controller_model)
            controller_id = "controller-" + device_id
            controller_add_cmd = ("device_add %s,id=%s" %
                                  (controller_model, controller_id))
            error.context("Adding SCSI controller.")
            vm.monitor.send_args_cmd(controller_add_cmd)

        check_support_device(pci_model)
        if drive_cmd_type == "drive_add":
            driver_add_cmd = ("%s auto file=%s,if=none,format=%s,id=%s" %
                              (drive_cmd_type, image_filename, image_format,
                               pci_info[pci_num][0]))
        elif drive_cmd_type == "__com.redhat_drive_add":
            driver_add_cmd = ("%s file=%s,format=%s,id=%s" %
                             (drive_cmd_type, image_filename, image_format,
                              pci_info[pci_num][0]))
        # add driver.
        error.context("Adding driver.")
        vm.monitor.send_args_cmd(driver_add_cmd, convert=False)

        pci_add_cmd = ("device_add id=%s,driver=%s,drive=%s" %
                       (pci_info[pci_num][1], pci_model, pci_info[pci_num][0]))
        return device_add(pci_num, pci_add_cmd, pci_id=pci_id)

    def device_add(pci_num, pci_add_cmd, pci_id=None):
        error.context("Adding pci device with command 'device_add'")
        guest_devices = session.cmd_output(chk_cmd)
        if vm.monitor.protocol == 'qmp':
            add_output = vm.monitor.send_args_cmd(pci_add_cmd)
        else:
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        guest_device = find_new_device(chk_cmd, guest_devices)
        if pci_id is None:
            pci_info[pci_num].append(add_output)
            pci_info[pci_num].append(pci_model)
            pci_info[pci_num].append(guest_device)

        after_add = vm.monitor.info("pci")
        if pci_info[pci_num][1] not in after_add:
            logging.debug("Print info pci after add the block: %s" % after_add)
            raise error.TestFail("Add device failed. Monitor command is: %s"
                                 ". Output: %r" % (pci_add_cmd, add_output))
        return after_add

    # Hot add a pci device
    def add_device(pci_num, pci_id=None):
        info_pci_ref = vm.monitor.info("pci")
        reference = session.cmd_output(params.get("reference_cmd"))

        try:
            # get function for adding device.
            add_fuction = local_functions["%s_%s" % (cmd_type, pci_type)]
        except:
            raise error.TestError("No function for adding '%s' dev with '%s'" %
                                  (pci_type, cmd_type))
        after_add = None
        if add_fuction:
            # Do add pci device.
            after_add = add_fuction(pci_num, pci_id=pci_id)

        try:
            # Define a helper function to compare the output
            def _new_shown():
                o = session.cmd_output(params.get("reference_cmd"))
                return o != reference

            # Define a helper function to catch PCI device string
            def _find_pci():
                o = session.cmd_output(params.get("find_pci_cmd"))
                return params.get("match_string") in o

            error.context("Start checking new added device")
            # Compare the output of 'info pci'
            if after_add == info_pci_ref:
                raise error.TestFail("No new PCI device shown after executing "
                                     "monitor command: 'info pci'")

            secs = int(params.get("wait_secs_for_hook_up"))
            if not utils_misc.wait_for(_new_shown, test_timeout, secs, 3):
                raise error.TestFail("No new device shown in output of command "
                                     "executed inside the guest: %s" %
                                     params.get("reference_cmd"))

            if not utils_misc.wait_for(_find_pci, test_timeout, 3, 3):
                raise error.TestFail("PCI %s %s device not found in guest. "
                                     "Command was: %s" %
                                     (pci_model, pci_type,
                                      params.get("find_pci_cmd")))

            # Test the newly added device
        except:
            pci_del(pci_num, ignore_failure=True)
            raise

    # Hot delete a pci device
    def pci_del(pci_num, ignore_failure=False):
        def _device_removed():
            after_del = vm.monitor.info("pci")
            return after_del != before_del

        before_del = vm.monitor.info("pci")
        if cmd_type == "pci_add":
            slot_id = int(pci_info[pci_num][2].split(",")[2].split()[1])
            cmd = "pci_del pci_addr=%s" % hex(slot_id)
            vm.monitor.send_args_cmd(cmd, convert=False)
        elif cmd_type == "device_add":
            cmd = "device_del id=%s" % pci_info[pci_num][1]
            vm.monitor.send_args_cmd(cmd)

        if (not utils_misc.wait_for(_device_removed, test_timeout, 0, 1)
            and not ignore_failure):
            raise error.TestFail("Failed to hot remove PCI device: %s. "
                                 "Monitor command: %s" %
                                 (pci_info[pci_num][3], cmd))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    guest_devices = None
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("test_timeout", 360))
    pci_type = params.get("pci_type")
    pci_model = params.get("pci_model")

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        session.cmd("modprobe %s" % module)

    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == 'qmp':
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.send_args_cmd("help")

    cmd_type = utils_test.find_substring(str(cmd_output), "device_add",
                                         "pci_add")
    if not cmd_output:
        raise error.TestError("Unknow version of qemu")

    # Determine syntax of drive hotplug
    # __com.redhat_drive_add == qemu-kvm-0.12 on RHEL 6
    # drive_add == qemu-kvm-0.13 onwards
    drive_cmd_type = utils_test.find_substring(str(cmd_output),
                                    "__com.redhat_drive_add", "drive_add")
    if not drive_cmd_type:
        raise error.TestError("Unknow version of qemu")

    local_functions = locals()

    pci_num_range = int(params.get("pci_num"))
    rp_times = int(params.get("repeat_times"))
    img_list = params.get("images").split()
    chk_cmd = params.get("guest_check_cmd")
    mark_cmd = params.get("mark_cmd")
    offset = params.get("offset")
    confirm_cmd = params.get("confirm_cmd")

    pci_info = []
    # Add block device into guest
    for pci_num in xrange(pci_num_range):
        error.context("Prepare removable pci device")
        add_device(pci_num)
        if pci_info[pci_num][4] is not None:
            partition = pci_info[pci_num][4]
            cmd = mark_cmd % (partition, partition, offset)
            session.cmd(cmd)
        else:
            raise error.TestError("Device not init in guest")

    for j in range(rp_times):
        # pci_info is a list of list.
        # each element 'i' has 4 members:
        # pci_info[i][0] == device drive id, only used for device_add
        # pci_info[i][1] == device id, only used for device_add
        # pci_info[i][2] == output of device add command
        # pci_info[i][3] == device module name.
        # pci_info[i][4] == partition id in guest
        pci_num = random.randint(0, len(pci_info) - 1)
        error.context("start hot-deleting pci device, repeat %d" % j)
        guest_devices = session.cmd_output(chk_cmd)
        pci_del(pci_num)
        device_del = find_del_device(chk_cmd, guest_devices)
        if device_del != pci_info[pci_num][4]:
            raise error.TestFail("Device is not deleted in guest.")
        error.context("Start hot-adding pci device, repeat %d" % j)
        guest_devices = session.cmd_output(chk_cmd)
        add_device(pci_num, pci_id=pci_info[pci_num][0])
        device_del = find_new_device(chk_cmd, guest_devices)
        if device_del != pci_info[pci_num][4]:
            raise error.TestFail("Device partition changed from %s to %s" %
                                 (pci_info[pci_num][4], device_del))
        cmd = confirm_cmd % (pci_info[pci_num][4], offset)
        confirm_info = session.cmd_output(cmd)
        if device_del not in confirm_info:
            raise error.TestFail("Can not find partition tag in Guest: %s" %
                                  confirm_info)
