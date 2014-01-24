import os
import shutil
import logging
from autotest.client.shared import error, utils
from virttest import virsh, data_dir, virt_vm, utils_misc
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test command: virsh change-media.

    The command changes the media used by CD or floppy drives.

    Test steps:
    1. Prepare test environment.
    2. Perform virsh change-media operation.
    3. Recover test environment.
    4. Confirm the test result.
    """
    @error.context_aware
    def env_pre(old_iso, new_iso):
        """
        Prepare ISO image for test

        :param old_iso: sourse file for insert
        :param new_iso: sourse file for update
        """
        error.context("Preparing ISO images")
        utils.run("dd if=/dev/urandom of=%s/old bs=1M count=1" % iso_dir)
        utils.run("dd if=/dev/urandom of=%s/new bs=1M count=1" % iso_dir)
        utils.run("mkisofs -o %s %s/old" % (old_iso, iso_dir))
        utils.run("mkisofs -o %s %s/new" % (new_iso, iso_dir))

    @error.context_aware
    def check_media(session, target_file, action):
        """
        Check guest cdrom/floppy files

        :param session: guest session
        :param target_file: the expected files
        :param action: test case action
        """
        if action != "--eject ":
            error.context("Checking guest %s files" % target_device)
            if target_device == "hdc":
                mount_cmd = "mount /dev/sr0 /media"
            else:
                if not os.path.exists("/dev/fd0"):
                    session.cmd("mknod /dev/fd0 b 2 0")
                mount_cmd = "mount /dev/fd0 /media"
            session.cmd(mount_cmd)
            session.cmd("test -f /media/%s" % target_file)
            session.cmd("umount /media")

        else:
            error.context("Ejecting guest cdrom files")
            if target_device == "hdc":
                if session.cmd_status("mount /dev/sr0 /media -o loop") == 32:
                    logging.info("Eject succeeded")
            else:
                if not os.path.exists("/dev/fd0"):
                    session.cmd("mknod /dev/fd0 b 2 0")
                if session.cmd_status("mount /dev/fd0 /media -o loop") == 32:
                    logging.info("Eject succeeded")

    def add_device(vm_name, init_source="''"):
        """
        Add device for test vm

        :param vm_name: guest name
        :param init_source: source file
        """
        if vm.is_alive():
            virsh.destroy(vm_name)

        virsh.attach_disk(vm_name, init_source,
                          target_device,
                          "--type %s --sourcetype file --config" % device_type,
                          debug=True)

    def update_device(vm_name, init_iso, options, start_vm):
        """
        Update device iso file for test case

        :param vm_name: guest name
        :param init_iso: source file
        :param options: update-device option
        :param start_vm: guest start flag
        """
        snippet = """
<disk type='file' device='%s'>
<driver name='qemu' type='raw'/>
<source file='%s'/>
<target dev='%s'/>
<readonly/>
</disk>
""" % (device_type, init_iso, target_device)
        update_iso_file = open(update_iso_xml, "w")
        update_iso_file.write(snippet)
        update_iso_file.close()

        cmd_options = "--force "
        if options == "--config" or start_vm == "no":
            cmd_options += " --config"

        # Give domain the ISO image file
        return virsh.update_device(domainarg=vm_name,
                            filearg=update_iso_xml, flagstr=cmd_options,
                            debug=True)

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm_ref = params.get("change_media_vm_ref")
    action = params.get("change_media_action")
    start_vm = params.get("start_vm")
    options = params.get("change_media_options")
    device_type = params.get("change_media_device_type", "cdrom")
    target_device = params.get("change_media_target_device", "hdc")
    source_name = params.get("change_media_source")
    status_error = params.get("status_error", "no")
    check_file = params.get("change_media_check_file")
    update_iso_xml_name = params.get("change_media_update_iso_xml")
    init_iso_name = params.get("change_media_init_iso")
    old_iso_name = params.get("change_media_old_iso")
    new_iso_name = params.get("change_media_new_iso")
    source_path = params.get("change_media_source_path", "yes")

    if device_type not in ['cdrom', 'floppy']:
        raise error.TestNAError("Got a invalid device type:/n%s" % device_type)

    # Backup for recovery.
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    iso_dir = os.path.join(data_dir.get_tmp_dir(), "tmp")
    old_iso = os.path.join(iso_dir, old_iso_name)
    new_iso = os.path.join(iso_dir, new_iso_name)
    update_iso_xml = os.path.join(iso_dir, update_iso_xml_name)
    if not os.path.exists(iso_dir):
        os.mkdir(iso_dir)
    if not init_iso_name:
        init_iso = ""
    else:
        init_iso = os.path.join(iso_dir, init_iso_name)

    if vm_ref == "name":
        vm_ref = vm_name

    env_pre(old_iso, new_iso)
    # Check domain's disk device
    disk_blk = vm_xml.VMXML.get_disk_blk(vm_name)
    logging.info("disk_blk %s", disk_blk)
    if target_device not in disk_blk:
        logging.info("Adding device")
        add_device(vm_name)

    if vm.is_alive() and start_vm == "no":
        logging.info("Destroying guest...")
        vm.destroy()

    elif vm.is_dead() and start_vm == "yes":
        logging.info("Starting guest...")
        vm.start()

    # If test target is floppy, you need to set selinux to Permissive mode.
    result = update_device(vm_name, init_iso, options, start_vm)

    # If the selinux is set to enforcing, if we FAIL, then just SKIP
    force_SKIP = False
    if result.exit_status == 1 and utils_misc.selinux_enforcing() and \
       result.stderr.count("unable to execute QEMU command 'change':"):
        force_SKIP = True

    # Libvirt will ignore --source when action is eject
    if action == "--eject ":
        source = ""
    else:
        source = os.path.join(iso_dir, source_name)
        if source_path == "no":
            source = source_name

    all_options = action + options + " " + source
    result = virsh.change_media(vm_ref, target_device,
                                all_options, ignore_status=True, debug=True)
    if status_error == "yes":
        if start_vm == "no" and vm.is_dead():
            try:
                vm.start()
            except virt_vm.VMStartError, detail:
                result.exit_status = 1
                result.stderr = str(detail)
        if start_vm == "yes" and vm.is_alive():
            vm.destroy(gracefully=False)
            try:
                vm.start()
            except virt_vm.VMStartError, detail:
                result.exit_status = 1
                result.stderr = str(detail)

    status = result.exit_status

    try:
        if status_error == "no":
            if options == "--config" and vm.is_alive():
                vm.destroy()
            if vm.is_dead():
                vm.start()
            session = vm.wait_for_login()
            check_media(session, check_file, action)
            session.close()
    finally:
        # Clean the iso dir  and clean the device
        update_device(vm_name, "", options, start_vm)
        # Recover xml of vm.
        vmxml_backup.sync()
        utils.safe_rmdir(iso_dir)

    # Check status_error
    # Negative testing
    if status_error == "yes":
        if status:
            logging.info("Expected error (negative testing). Output: %s",
                         result.stderr.strip())
        else:
            raise error.TestFail("Unexpected return code %d "
                                 "(negative testing)" % status)

    # Positive testing
    elif status_error == "no":
        if status:
            if force_SKIP:
                raise error.TestNAError("SELinux is set to enforcing and has "
                                        "resulted in this test failing to open "
                                        "the iso file for a floppy.")
            raise error.TestFail("Unexpected error (positive testing). "
                                 "Output: %s" % result.stderr.strip())
        else:
            logging.info("Expected success. Output: %s", result.stdout.strip())

    else:
        raise error.TestError("Invalid value for status_error '%s' "
                              "(must be 'yes' or 'no')" % status_error)
