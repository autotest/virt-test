import logging, os, shutil
from autotest.client.shared import error, utils
from virttest import libvirt_vm, virsh
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
        1. guest session
        2. the expected files
        3. test case action
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
        """
        if vm.is_alive():
            virsh.destroy(vm_name)

        virsh.attach_disk(vm_name, init_cdrom,
                          " hdc", " --type cdrom --sourcetype file --config",
                          debug=True)

    def update_cdrom(vm_name, init_iso, options, start_vm ):
        """
        Update cdrom iso file for test case
        """
        snippet = """
<disk type='file' device='cdrom'>
<driver name='qemu' type='raw'/>
<source file='%s'/>
<target dev='hdc' bus='ide'/>
<readonly/>
</disk>
""" % (init_iso)
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
    vm_ref = params.get("vm_ref")
    action = params.get("action")
    start_vm = params.get("start_vm")
    options = params.get("options")
    cdrom_dir = os.path.join(test.tmpdir, "tmp")
    if not os.path.exists(cdrom_dir):
        os.mkdir(cdrom_dir)

    old_iso_name = params.get("old_iso")
    new_iso_name = params.get("new_iso")
    old_iso = cdrom_dir + old_iso_name
    new_iso = cdrom_dir + new_iso_name
    init_cdrom = params.get("init_cdrom")
    update_iso_xml_name = params.get("update_iso_xml")
    update_iso_xml = cdrom_dir + update_iso_xml_name
    init_iso_name = params.get("init_iso")
    if not init_iso_name :
        init_iso = ""

    else:
        init_iso = cdrom_dir + init_iso_name

    if vm_ref == "name":
        vm_ref = vm_name

    env_pre(old_iso, new_iso)
    # Check domain's disk device
    disk_blk =  vm_xml.VMXML.get_disk_blk(vm_name)
    logging.info("disk_blk %s" % disk_blk)
    if "hdc" not in  disk_blk:
        logging.info("Adding cdrom device")
        add_cdrom_device(vm_name, init_cdrom)

    if vm.is_alive() and start_vm == "no":
        logging.info("Destroying guest...")
        vm.destroy()

    elif vm.is_dead() and start_vm == "yes":
        logging.info("Starting guest...")
        vm.start()

    update_cdrom(vm_name, init_iso, options, start_vm)
    disk_device = params.get("disk_device")
    libvirtd = params.get("libvirtd", "on")

    if libvirtd == "off":
        libvirt_vm.libvirtd_stop()

    source_name = params.get("change_media_source")
    # Libvirt will ignore --source when action is eject
    if action == "--eject ":
        source = ""

    else:
        source = cdrom_dir + source_name

    all_options = action + options + " " + source
    result = virsh.change_media(vm_ref, disk_device,
                                all_options, ignore_status=True, debug=True)
    status = result.exit_status
    status_error =  params.get("status_error", "no")

    if status_error == "no":
        if options == "--config" and vm.is_alive():
            vm.destroy()

        vm.start()
        session = vm.wait_for_login()
        check_file = params.get("check_file")
        check_media(session, check_file, action)
        session.close()

    # Recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()

    # Clean the cdrom dir  and clean the cdrom device
    update_cdrom(vm_name, "", options, start_vm)
    shutil.rmtree(cdrom_dir)

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
