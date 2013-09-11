import re
import logging
import string
from autotest.client.shared import error
from virttest import utils_misc, aexpect, storage, utils_test, data_dir


@error.context_aware
def run_pci_hotplug(test, params, env):
    """
    Test hotplug of PCI devices.

    (Elements between [] are configurable test parameters)
    1) PCI add one/multi device (NIC / block) with(or without) repeat
    2) Compare output of monitor command 'info pci'.
    3) Compare output of guest command [reference_cmd].
    4) Verify whether pci_model is shown in [pci_find_cmd].
    5) Check whether the newly added PCI device works fine.
    6) PCI delete the device, verify whether could remove the PCI device.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    # Select an image file
    def find_image(pci_num):
        image_params = params.object_params("%s" % img_list[pci_num + 1])
        o = storage.get_image_filename(image_params, data_dir.get_data_dir())
        return o

    def pci_add_nic(pci_num):
        pci_add_cmd = "pci_add pci_addr=auto nic model=%s" % pci_model
        return pci_add(pci_add_cmd)

    def pci_add_block(pci_num):
        image_filename = find_image(pci_num)
        pci_add_cmd = ("pci_add pci_addr=auto storage file=%s,if=%s" %
                       (image_filename, pci_model))
        return pci_add(pci_add_cmd)

    def pci_add(pci_add_cmd):
        error.context("Adding pci device with command 'pci_add'")
        add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info.append(['', '', add_output, pci_model])

        if not "OK domain" in add_output:
            raise error.TestFail("Add PCI device failed. "
                                 "Monitor command is: %s, Output: %r" %
                                 (pci_add_cmd, add_output))
        return vm.monitor.info("pci")

    def is_supported_device(dev):
        # Probe qemu to verify what is the supported syntax for PCI hotplug
        cmd_output = vm.monitor.human_monitor_cmd("?")
        if len(re.findall("\ndevice_add", cmd_output)) > 0:
            cmd_type = "device_add"
        elif len(re.findall("\npci_add", cmd_output)) > 0:
            cmd_type = "pci_add"
        else:
            raise error.TestError("Unknow version of qemu")

        # Probe qemu for a list of supported devices
        probe_output = vm.monitor.human_monitor_cmd("%s ?" % cmd_type)
        devices_supported = [j.strip('"') for j in
                             re.findall('\"[a-z|0-9|\-|\_|\,|\.]*\"',
                                        probe_output, re.MULTILINE)]
        logging.debug("QEMU reported the following supported devices for "
                      "PCI hotplug: %s", devices_supported)
        return (dev in devices_supported)

    def verify_supported_device(dev):
        if not is_supported_device(dev):
            raise error.TestError("%s doesn't support device: %s" %
                                  (cmd_type, dev))

    def device_add_nic(pci_num, queues=1):
        device_id = pci_type + "-" + utils_misc.generate_random_id()
        pci_info.append([device_id, device_id])

        pci_model = params.get("pci_model")
        if pci_model == "virtio":
            pci_model = "virtio-net-pci"
        verify_supported_device(pci_model)
        pci_add_cmd = "device_add id=%s,driver=%s" % (pci_info[pci_num][1],
                                                      pci_model)
        if queues > 1 and "virtio" in pci_model:
            pci_add_cmd += ",mq=on"
        return device_add(pci_num, pci_add_cmd)

    def device_add_block(pci_num):
        device_id = pci_type + "-" + utils_misc.generate_random_id()
        pci_info.append([device_id, device_id])

        image_format = params.get("image_format_%s" % img_list[pci_num + 1])
        if not image_format:
            image_format = params.get("image_format", "qcow2")
        image_filename = find_image(pci_num)

        pci_model = params.get("pci_model")
        controller_model = None
        if pci_model == "virtio":
            pci_model = "virtio-blk-pci"

        if pci_model == "scsi":
            pci_model = "scsi-disk"
            controller_model = "lsi53c895a"
            verify_supported_device(controller_model)
            controller_id = "controller-" + device_id
            controller_add_cmd = ("device_add %s,id=%s" %
                                  (controller_model, controller_id))
            error.context("Adding SCSI controller.")
            vm.monitor.send_args_cmd(controller_add_cmd)

        verify_supported_device(pci_model)
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
        return device_add(pci_num, pci_add_cmd)

    def device_add(pci_num, pci_add_cmd):
        error.context("Adding pci device with command 'device_add'")
        if vm.monitor.protocol == 'qmp':
            add_output = vm.monitor.send_args_cmd(pci_add_cmd)
        else:
            add_output = vm.monitor.send_args_cmd(pci_add_cmd, convert=False)
        pci_info[pci_num].append(add_output)
        pci_info[pci_num].append(pci_model)

        after_add = vm.monitor.info("pci")
        if pci_info[pci_num][1] not in after_add:
            logging.error("Could not find matched id in monitor:"
                          " %s" % pci_info[pci_num][1])
            raise error.TestFail("Add device failed. Monitor command is: %s"
                                 ". Output: %r" % (pci_add_cmd, add_output))
        return after_add

    # Hot add a pci device
    def add_device(pci_num, queues=1):
        info_pci_ref = vm.monitor.info("pci")
        reference = session.cmd_output(reference_cmd)

        try:
            # get function for adding device.
            add_fuction = local_functions["%s_%s" % (cmd_type, pci_type)]
        except Exception:
            raise error.TestError("No function for adding '%s' dev with '%s'" %
                                  (pci_type, cmd_type))
        after_add = None
        if add_fuction:
            # Do add pci device.
            after_add = add_fuction(pci_num, queues)

        try:
            # Define a helper function to compare the output
            def _new_shown():
                o = session.cmd_output(reference_cmd)
                return o != reference

            # Define a helper function to catch PCI device string
            def _find_pci():
                output = session.cmd_output(params.get("find_pci_cmd"))
                output = map(string.strip, output.splitlines())
                ref = map(string.strip, reference.splitlines())
                output = [_ for _ in output if _ not in ref]
                output = "\n".join(output)
                if re.search(params.get("match_string"), output, re.I):
                    return True
                return False

            error.context("Start checking new added device")
            # Compare the output of 'info pci'
            if after_add == info_pci_ref:
                raise error.TestFail("No new PCI device shown after executing "
                                     "monitor command: 'info pci'")

            secs = int(params.get("wait_secs_for_hook_up"))
            if not utils_misc.wait_for(_new_shown, test_timeout, secs, 3):
                raise error.TestFail("No new device shown in output of command "
                                     "executed inside the guest: %s" %
                                     reference_cmd)

            if not utils_misc.wait_for(_find_pci, test_timeout, 3, 3):
                raise error.TestFail("PCI %s %s device not found in guest. "
                                     "Command was: %s" %
                                     (pci_model, pci_type,
                                      params.get("find_pci_cmd")))

            # Test the newly added device
            try:
                session.cmd(params.get("pci_test_cmd") % (pci_num + 1))
            except aexpect.ShellError, e:
                raise error.TestFail("Check for %s device failed after PCI "
                                     "hotplug. Output: %r" % (pci_type, e.output))

        except Exception:
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
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)

    test_timeout = int(params.get("hotplug_timeout", 360))
    reference_cmd = params["reference_cmd"]
    # Test if it is nic or block
    pci_type = params["pci_type"]
    pci_model = params["pci_model"]

    # Modprobe the module if specified in config file
    module = params.get("modprobe_module")
    if module:
        session.cmd("modprobe %s" % module)

    # check monitor type
    qemu_binary = params.get("qemu_binary", "/usr/libexec/qemu-kvm")
    qemu_binary = utils_misc.get_path(test.bindir, qemu_binary)
    # Probe qemu to verify what is the supported syntax for PCI hotplug
    if vm.monitor.protocol == 'qmp':
        cmd_output = vm.monitor.info("commands")
    else:
        cmd_output = vm.monitor.human_monitor_cmd("help", debug=False)

    cmd_type = utils_test.find_substring(str(cmd_output), "device_add",
                                         "pci_add")
    if not cmd_output:
        raise error.TestError("Could find a suitable method for hotplugging"
                              " device in this version of qemu")

    # Determine syntax of drive hotplug
    # __com.redhat_drive_add == qemu-kvm-0.12 on RHEL 6
    # drive_add == qemu-kvm-0.13 onwards
    drive_cmd_type = utils_test.find_substring(str(cmd_output),
                                               "__com.redhat_drive_add", "drive_add")
    if not drive_cmd_type:
        raise error.TestError("Could find a suitable method for hotplugging"
                              " drive in this version of qemu")

    local_functions = locals()

    pci_num_range = int(params.get("pci_num"))
    queues = int(params.get("queues"))
    rp_times = int(params.get("repeat_times"))
    img_list = params.get("images").split()
    context_msg = "Running sub test '%s' %s"
    for j in range(rp_times):
        # pci_info is a list of list.
        # each element 'i' has 4 members:
        # pci_info[i][0] == device drive id, only used for device_add
        # pci_info[i][1] == device id, only used for device_add
        # pci_info[i][2] == output of device add command
        # pci_info[i][3] == device module name.
        pci_info = []
        for pci_num in xrange(pci_num_range):
            sub_type = params.get("sub_type_before_plug")
            if sub_type:
                error.context(context_msg % (sub_type, "before hotplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error.context("Start hot-adding pci device, repeat %d" % j)
            add_device(pci_num, queues)

            sub_type = params.get("sub_type_after_plug")
            if sub_type:
                error.context(context_msg % (sub_type, "after hotplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)
        for pci_num in xrange(pci_num_range):
            sub_type = params.get("sub_type_before_unplug")
            if sub_type:
                error.context(context_msg % (sub_type, "before hotunplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

            error.context("start hot-deleting pci device, repeat %d" % j)
            pci_del(-(pci_num + 1))

            sub_type = params.get("sub_type_after_unplug")
            if sub_type:
                error.context(context_msg % (sub_type, "after hotunplug"),
                              logging.info)
                utils_test.run_virt_sub_test(test, params, env, sub_type)

    if params.get("reboot_vm", "no") == "yes":
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        vm.reboot()
