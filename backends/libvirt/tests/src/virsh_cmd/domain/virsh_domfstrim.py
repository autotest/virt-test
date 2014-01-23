import logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import virsh, utils_misc
from virttest.libvirt_xml import vm_xml
from virttest.libvirt_xml.devices.disk import Disk
from virttest.libvirt_xml.devices.controller import Controller


def run(test, params, env):
    """
    Test domfstrim command, make sure that all supported options work well

    Test scenaries:
    1. fstrim without options
    2. fstrim with --minimum with large options
    3. fstrim with --minimum with small options

    Note: --mountpoint still not supported so will not test here
    """

    if not virsh.has_help_command('domfstrim'):
        raise error.TestNAError("This version of libvirt does not support "
                                "the domfstrim test")

    try:
        utils_misc.find_command("lsscsi")
    except ValueError:
        raise error.TestNAError("Command 'lsscsi' is missing. You must "
                                "install it.")

    vm_name = params.get("main_vm", "virt-tests-vm1")
    status_error = ("yes" == params.get("status_error", "no"))
    minimum = params.get("domfstrim_minimum")
    mountpoint = params.get("domfstrim_mountpoint")
    options = params.get("domfstrim_options", "")
    is_fulltrim = ("yes" == params.get("is_fulltrim", "yes"))

    def recompose_xml(vm_name, scsi_disk):
        """
        Add scsi disk, guest agent and scsi controller for guest
        :param: vm_name: Name of domain
        :param: scsi_disk: scsi_debug disk name
        """
        # Get disk path of scsi_disk
        path_cmd = "udevadm info --name %s | grep /dev/disk/by-path/ | " \
                   "cut -d' ' -f4" % scsi_disk
        disk_path = utils.run(path_cmd).stdout.strip()

        # Add qemu guest agent in guest xml
        vm_xml.VMXML.set_agent_channel(vm_name)

        vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
        # Add scsi disk xml
        scsi_disk = Disk(type_name="block")
        scsi_disk.device = "lun"
        scsi_disk.source = scsi_disk.new_disk_source(
            **{'attrs': {'dev': disk_path}})
        scsi_disk.target = {'dev': "sdb", 'bus': "scsi"}
        vmxml.add_device(scsi_disk)

        # Add scsi disk controller
        scsi_controller = Controller("controller")
        scsi_controller.type = "scsi"
        scsi_controller.index = "0"
        scsi_controller.model = "virtio-scsi"
        vmxml.add_device(scsi_controller)

        # Redefine guest
        vmxml.sync()

    def start_guest_agent(session):
        """
        Start guest agent service in guest
        :param: session: session in guest
        """
        # Check if qemu-ga installed
        check_cmd = "rpm -q qemu-guest-agent||yum install -y qemu-guest-agent"
        session.cmd(check_cmd)
        session.cmd("service qemu-guest-agent start")
        # Check if the qemu-ga really started
        stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
        if stat_ps != 0:
            raise error.TestFail("Fail to run qemu-ga in guest")

    # Do backup for origin xml
    xml_backup = vm_xml.VMXML.new_from_dumpxml(vm_name)
    try:
        vm = env.get_vm(vm_name)
        if not vm.is_alive():
            vm.start()
        session = vm.wait_for_login()
        bef_list = session.cmd_output("fdisk -l|grep ^/dev|"
                                      "cut -d' ' -f1").split("\n")
        session.close()
        vm.destroy()

        # Load module and get scsi disk name
        utils.load_module("scsi_debug lbpu=1 lbpws=1")
        scsi_disk = utils.run("lsscsi|grep scsi_debug|"
                              "awk '{print $6}'").stdout.strip()
        # Create partition
        open("/tmp/fdisk-cmd", "w").write("n\np\n\n\n\nw\n")
        output = utils.run("fdisk %s < /tmp/fdisk-cmd"
                           % scsi_disk).stdout.strip()
        logging.debug("fdisk output %s", output)
        # Format disk
        output = utils.run("mkfs.ext3 %s1" % scsi_disk).stdout.strip()
        logging.debug("output %s", output)
        # Add scsi disk and agent channel in guest
        recompose_xml(vm_name, scsi_disk)

        vm.start()
        guest_session = vm.wait_for_login()
        start_guest_agent(guest_session)
        # Get new generated disk
        af_list = guest_session.cmd_output("fdisk -l|grep ^/dev|"
                                           "cut -d' ' -f1").split('\n')
        new_disk = "".join(list(set(bef_list) ^ set(af_list)))
        # Mount disk in guest
        guest_session.cmd("mkdir -p /home/test && mount %s /home/test" %
                          new_disk)

        # Do first fstrim before all to get original map for compare
        cmd_result = virsh.domfstrim(vm_name)
        if cmd_result.exit_status != 0:
            raise error.TestFail("Fail to do virsh domfstrim, error %s" %
                                 cmd_result.stderr)

        def get_diskmap_size():
            """
            Collect size from disk map
            :return: disk size
            """
            map_cmd = "cat /sys/bus/pseudo/drivers/scsi_debug/map"
            diskmap = utils.run(map_cmd).stdout.strip('\n\x00')
            logging.debug("disk map is %s", diskmap)
            sum = 0
            for i in diskmap.split(","):
                sum = sum + int(i.split("-")[1]) - int(i.split("-")[0])
            return sum

        ori_size = get_diskmap_size()

        # Write date in disk
        dd_cmd = "dd if=/dev/zero of=/home/test/file bs=1048576 count=5"
        guest_session.cmd(dd_cmd)

        def _full_mapped():
            """
            Do full map check
            :return: True or False
            """
            full_size = get_diskmap_size()
            return (ori_size < full_size)

        if not utils_misc.wait_for(_full_mapped, timeout=30):
            raise error.TestError("Scsi map is not updated after dd command.")

        full_size = get_diskmap_size()

        # Remove disk content in guest
        guest_session.cmd("rm -rf /home/test/*")
        guest_session.close()

        def _trim_completed():
            """
            Do empty fstrim check
            :return: True of False
            """
            cmd_result = virsh.domfstrim(vm_name, minimum, mountpoint, options)
            if cmd_result.exit_status != 0:
                if not status_error:
                    raise error.TestFail("Fail to do virsh domfstrim, error %s"
                                         % cmd_result.stderr)
                else:
                    logging.info("Fail to do virsh domfstrim as expected: %s",
                                 cmd_result.stderr)
                    return True

            empty_size = get_diskmap_size()

            if is_fulltrim:
                return empty_size <= ori_size
            else:
                # For partly trim will check later
                return False

        if not utils_misc.wait_for(_trim_completed, timeout=30):
            if not is_fulltrim:
                # Get result again to check partly fstrim
                empty_size = get_diskmap_size()
                if ori_size < empty_size <= full_size:
                    logging.info("Success to do fstrim partly")
                    return True
            raise error.TestFail("Fail to do fstrim %s, %s")
        logging.info("Success to do fstrim")

    finally:
        # Do domain recovery
        xml_backup.sync()
        utils.unload_module("scsi_debug")
