import os
import logging
from autotest.client.shared import error
from virttest import aexpect, virt_vm, virsh, remote
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test virsh {at|de}tach-disk command.

    The command can attach new disk/detach disk.
    1.Prepare test environment,destroy or suspend a VM.
    2.Perform virsh attach/detach-disk operation.
    3.Recover test environment.
    4.Confirm the test result.
    """

    def create_device_file(device_source="/tmp/attach.img"):
        """
        Create a device source file.

        :param device_source: Device source file.
        """
        try:
            f = open(device_source, 'wb')
            f.seek((512 * 1024 * 1024) - 1)
            f.write(str(0))
            f.close()
        except IOError:
            logging.error("Image file %s created failed." % device_source)

    def check_vm_partition(vm, device, os_type, target_name):
        """
        Check VM disk's partition.

        :param vm. VM guest.
        :param os_type. VM's operation system type.
        :param target_name. Device target type.
        :return: True if check successfully.
        """
        logging.info("Checking VM partittion...")
        if vm.is_dead():
            vm.start()
        try:
            if os_type == "linux":
                session = vm.wait_for_login()
                if device == "disk":
                    s, o = session.cmd_status_output(
                        "grep %s /proc/partitions" % target_name)
                    logging.info("Virtio devices in VM:\n%s", o)
                elif device == "cdrom":
                    s, o = session.cmd_status_output(
                        "ls /dev/cdrom")
                    logging.info("CDROM in VM:\n%s", o)
                session.close()
                if s != 0:
                    return False
            return True
        except (remote.LoginError, virt_vm.VMError, aexpect.ShellError), e:
            logging.error(str(e))
            return False

    def acpiphp_module_modprobe(vm, os_type):
        """
        Add acpiphp module if VM's os type is rhle5.*

        :param vm. VM guest.
        :param os_type. VM's operation system type.
        :return: True if operate successfully.
        """
        if vm.is_dead():
            vm.start()
        try:
            if os_type == "linux":
                session = vm.wait_for_login()
                s_rpm, o_rpm = session.cmd_status_output(
                    "rpm --version")
                # If status is different from 0, this
                # guest OS doesn't support the rpm package
                # manager
                if s_rpm:
                    session.close()
                    return True
                s_vd, o_vd = session.cmd_status_output(
                    "rpm -qa | grep redhat-release")
                if s_vd != 0 and o_vd != "":
                    session.close()
                    return False
                if o_vd.find("5Server") != -1:
                    s_mod, o_mod = session.cmd_status_output(
                        "modprobe acpiphp")
                    del o_mod
                    if s_mod != 0:
                        session.close()
                        return False
                session.close()
            return True
        except (remote.LoginError, virt_vm.VMError, aexpect.ShellError), e:
            logging.error(str(e))
            return False

    vm_ref = params.get("at_dt_disk_vm_ref", "name")
    at_options = params.get("at_dt_disk_at_options", "")
    dt_options = params.get("at_dt_disk_dt_options", "")
    pre_vm_state = params.get("at_dt_disk_pre_vm_state", "running")
    status_error = params.get("status_error", 'no')
    no_attach = params.get("at_dt_disk_no_attach", 'no')
    os_type = params.get("os_type", "linux")

    # Get test command.
    test_cmd = params.get("at_dt_disk_test_cmd", "attach-disk")

    # Disk specific attributes.
    device = params.get("at_dt_disk_device", "disk")
    device_source_name = params.get("at_dt_disk_device_source", "attach.img")
    device_target = params.get("at_dt_disk_device_target", "vdd")
    bus_type = params.get("at_dt_disk_bus_type", "virtio")
    source_path = "yes" == params.get("at_dt_disk_device_source_path", "yes")
    test_twice = "yes" == params.get("at_dt_disk_test_twice", "no")

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    if vm.is_alive():
        vm.destroy(gracefully=False)
    # Back up xml file.
    vm_xml_file = os.path.join(test.tmpdir, "vm.xml")
    if source_path:
        device_source = os.path.join(test.virtdir, device_source_name)
    else:
        device_source = device_source_name
    virsh.dumpxml(vm_name, extra="--inactive", to_file=vm_xml_file)

    # Create virtual device file.
    create_device_file(device_source)

    if vm.is_alive():
        vm.destroy(gracefully=False)

    # If we are testing cdrom device, we need to detach hdc in VM first.
    if device == "cdrom":
        if vm.is_alive():
            vm.destroy(gracefully=False)
        s_detach = virsh.detach_disk(vm_name, device_target, "--config")
        if not s_detach:
            logging.error("Detach hdc failed before test.")

    # If we are testing detach-disk, we need to attach certain device first.
    if test_cmd == "detach-disk" and no_attach != "yes":
        s_attach = virsh.attach_disk(vm_name, device_source, device_target,
                                     "--driver qemu --config").exit_status
        if s_attach != 0:
            logging.error("Attaching device failed before testing detach-disk")

        if test_twice:
            device_target2 = params.get("at_dt_disk_device_target2",
                                        device_target)
            create_device_file(device_source)
            s_attach = virsh.attach_disk(vm_name, device_source, device_target2,
                                         "--driver qemu --config").exit_status
            if s_attach != 0:
                logging.error("Attaching device failed before testing "
                              "detach-disk test_twice")

    vm.start()
    vm.wait_for_login()

    # Add acpiphp module before testing if VM's os type is rhle5.*
    if not acpiphp_module_modprobe(vm, os_type):
        raise error.TestError("Add acpiphp module failed before test.")

    # Turn VM into certain state.
    if pre_vm_state == "paused":
        logging.info("Suspending %s..." % vm_name)
        if vm.is_alive():
            vm.pause()
    elif pre_vm_state == "shut off":
        logging.info("Shuting down %s..." % vm_name)
        if vm.is_alive():
            vm.destroy(gracefully=False)

    # Get disk count before test.
    disk_count_before_cmd = vm_xml.VMXML.get_disk_count(vm_name)

    # Test.
    domid = vm.get_id()
    domuuid = vm.get_uuid()

    # Confirm how to reference a VM.
    if vm_ref == "name":
        vm_ref = vm_name
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "uuid":
        vm_ref = domuuid
    else:
        vm_ref = ""

    if test_cmd == "attach-disk":
        status = virsh.attach_disk(vm_ref, device_source, device_target,
                                   at_options, debug=True).exit_status
    elif test_cmd == "detach-disk":
        status = virsh.detach_disk(vm_ref, device_target, dt_options,
                                   debug=True).exit_status
    if test_twice:
        device_target2 = params.get("at_dt_disk_device_target2", device_target)
        create_device_file(device_source)
        if test_cmd == "attach-disk":
            status = virsh.attach_disk(vm_ref, device_source,
                                       device_target2, at_options, debug=True).exit_status
        elif test_cmd == "detach-disk":
            status = virsh.detach_disk(vm_ref, device_target2, dt_options,
                                       debug=True).exit_status

    # Resume guest after command. On newer libvirt this is fixed as it has
    # been a bug. The change in xml file is done after the guest is resumed.
    if pre_vm_state == "paused":
        vm.resume()

    # Check disk count after command.
    check_count_after_cmd = True
    disk_count_after_cmd = vm_xml.VMXML.get_disk_count(vm_name)
    if test_cmd == "attach-disk":
        if disk_count_after_cmd == disk_count_before_cmd:
            check_count_after_cmd = False
    elif test_cmd == "detach-disk":
        if disk_count_after_cmd < disk_count_before_cmd:
            check_count_after_cmd = False

    # Recover VM state.
    if pre_vm_state == "shut off":
        vm.start()

    # Check in VM after command.
    check_vm_after_cmd = True
    check_vm_after_cmd = check_vm_partition(vm, device, os_type, device_target)

    # Destroy VM.
    vm.destroy(gracefully=False)

    # Check disk count after VM shutdown (with --config).
    check_count_after_shutdown = True
    disk_count_after_shutdown = vm_xml.VMXML.get_disk_count(vm_name)
    if test_cmd == "attach-disk":
        if disk_count_after_shutdown == disk_count_before_cmd:
            check_count_after_shutdown = False
    elif test_cmd == "detach-disk":
        if disk_count_after_shutdown < disk_count_before_cmd:
            check_count_after_shutdown = False

    # Recover VM.
    if vm.is_alive():
        vm.destroy(gracefully=False)
    virsh.undefine(vm_name)
    virsh.define(vm_xml_file)
    if os.path.exists(device_source):
        os.remove(device_source)

    # Check results.
    if status_error == 'yes':
        if status == 0:
            raise error.TestFail("virsh %s exit with unexpected value."
                                 % test_cmd)
    else:
        if status != 0:
            raise error.TestFail("virsh %s failed." % test_cmd)
        if test_cmd == "attach-disk":
            if at_options.count("config"):
                if not check_count_after_shutdown:
                    raise error.TestFail("Cannot see config attached device "
                                         "in xml file after VM shutdown.")
            else:
                if not check_count_after_cmd:
                    raise error.TestFail("Cannot see device in xml file"
                                         " after attach.")
                if not check_vm_after_cmd:
                    raise error.TestFail("Cannot see device in VM after"
                                         " attach.")
                if check_count_after_shutdown:
                    raise error.TestFail("See non-config attached device "
                                         "in xml file after VM shutdown.")
        elif test_cmd == "detach-disk":
            if dt_options.count("config"):
                if check_count_after_shutdown:
                    raise error.TestFail("See config detached device in "
                                         "xml file after VM shutdown.")
            else:
                if check_count_after_cmd:
                    raise error.TestFail("See device in xml file after detach.")
                if check_vm_after_cmd:
                    raise error.TestFail("See device in VM after detach.")
                if not check_count_after_shutdown:
                    raise error.TestFail("Cannot see non-config detached "
                                         "device in xml file after VM shutdown.")
        else:
            raise error.TestError("Unknown command %s." % test_cmd)
