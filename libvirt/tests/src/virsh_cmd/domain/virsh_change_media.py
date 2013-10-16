import logging
import os
from autotest.client.shared import error, utils
from virttest import virsh, utils_libvirtd
from virttest.libvirt_xml import vm_xml


def run_virsh_change_media(test, params, env):
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
        utils.run("dd if=/dev/urandom of=%s/old bs=10M count=1" % cdrom_dir)
        utils.run("dd if=/dev/urandom of=%s/new bs=10M count=1" % cdrom_dir)
        utils.run("mkisofs -o %s %s/old" % (old_iso, cdrom_dir))
        utils.run("mkisofs -o %s %s/new" % (new_iso, cdrom_dir))

    @error.context_aware
    def check_media(session, target_file, action):
        """
        Check guest cdrom files

        :param session: guest session
        :param target_file: the expected files
        :param action: test case action
        """
        if action != "--eject ":
            error.context("Checking guest cdrom files")
            session.cmd("mount /dev/cdrom /media || mount /dev/cdrom /media")
            session.cmd("test -f /media/%s" % target_file)
            session.cmd("umount /dev/cdrom")

        else:
            error.context("Ejecting guest cdrom files")
            if session.cmd_status("mount /dev/cdrom /media -o loop") == 32:
                logging.info("Eject succeeded")

    def add_cdrom_device(vm_name, init_cdrom):
        """
        Add cdrom device for test vm

        :param vm_name: guest name
        :param init_cdrom: source file
        """
        if vm.is_alive():
            virsh.destroy(vm_name)

        virsh.attach_disk(vm_name, init_cdrom,
                          disk_device, " --type cdrom --sourcetype file --config",
                          debug=True)

    def update_cdrom(vm_name, init_iso, options, start_vm):
        """
        Update cdrom iso file for test case

        :param vm_name: guest name
        :param init_iso: source file
        :param options: update-device option
        :param start_vm: guest start flag
        """
        snippet = """
<disk type='file' device='cdrom'>
<driver name='qemu' type='raw'/>
<source file='%s'/>
<target dev='%s' bus='ide'/>
<readonly/>
</disk>
""" % (init_iso, disk_device)
        update_iso_file = open(update_iso_xml, "w")
        update_iso_file.write(snippet)
        update_iso_file.close()

        cmd_options = "--force "
        if options == "--config" or start_vm == "no":
            cmd_options += " --config"

        # Give domain the ISO image file
        virsh.update_device(domainarg=vm_name,
                            filearg=update_iso_xml, flagstr=cmd_options,
                            debug=True)

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    vm_ref = params.get("change_media_vm_ref")
    action = params.get("change_media_action")
    start_vm = params.get("start_vm")
    options = params.get("change_media_options")
    disk_device = params.get("change_media_disk_device")
    libvirtd = params.get("libvirtd", "on")
    source_name = params.get("change_media_source")
    status_error = params.get("status_error", "no")
    check_file = params.get("change_media_check_file")
    init_cdrom = params.get("change_media_init_cdrom")
    update_iso_xml_name = params.get("change_media_update_iso_xml")
    init_iso_name = params.get("change_media_init_iso")
    old_iso_name = params.get("change_media_old_iso")
    new_iso_name = params.get("change_media_new_iso")
    source_path = params.get("change_media_source_path", "yes")
    cdrom_dir = os.path.join(test.tmpdir, "tmp")

    old_iso = os.path.join(cdrom_dir, old_iso_name)
    new_iso = os.path.join(cdrom_dir, new_iso_name)
    update_iso_xml = os.path.join(cdrom_dir, update_iso_xml_name)
    if not os.path.exists(cdrom_dir):
        os.mkdir(cdrom_dir)
    if not init_iso_name:
        init_iso = ""
    else:
        init_iso = os.path.join(cdrom_dir, init_iso_name)

    if vm_ref == "name":
        vm_ref = vm_name

    env_pre(old_iso, new_iso)
    # Check domain's disk device
    disk_blk = vm_xml.VMXML.get_disk_blk(vm_name)
    logging.info("disk_blk %s" % disk_blk)
    if disk_device not in disk_blk:
        logging.info("Adding cdrom device")
        add_cdrom_device(vm_name, init_cdrom)

    if vm.is_alive() and start_vm == "no":
        logging.info("Destroying guest...")
        vm.destroy()

    elif vm.is_dead() and start_vm == "yes":
        logging.info("Starting guest...")
        vm.start()

    update_cdrom(vm_name, init_iso, options, start_vm)

    if libvirtd == "off":
        utils_libvirtd.libvirtd_stop()

    # Libvirt will ignore --source when action is eject
    if action == "--eject ":
        source = ""
    else:
        source = os.path.join(cdrom_dir, source_name)
        if source_path == "no":
            source = source_name

    all_options = action + options + " " + source
    result = virsh.change_media(vm_ref, disk_device,
                                all_options, ignore_status=True, debug=True)
    if status_error == "yes":
        if start_vm == "no" and vm.is_dead():
            try:
                vm.start()
            except Exception, detail:
                result.exit_status = 1
                result.stderr = str(detail)

    status = result.exit_status

    if status_error == "no":
        if options == "--config" and vm.is_alive():
            vm.destroy()
        if vm.is_dead():
            vm.start()
        session = vm.wait_for_login()
        check_media(session, check_file, action)
        session.close()

    # Recover libvirtd service start
    if libvirtd == "off":
        utils_libvirtd.libvirtd_start()

    # Clean the cdrom dir  and clean the cdrom device
    update_cdrom(vm_name, "", options, start_vm)

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
            raise error.TestFail("Unexpected error (positive testing). "
                                 "Output: %s" % result.stderr.strip())
        else:
            logging.info("Expected success. Output: %s", result.stdout.strip())

    else:
        raise error.TestError("Invalid value for status_error '%s' "
                              "(must be 'yes' or 'no')" % status_error)
