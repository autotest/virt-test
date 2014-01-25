import os
import logging
import tempfile
from autotest.client.shared import error
from virttest import virsh, data_dir
from virttest.libvirt_xml import vm_xml

def run(test, params, env):
    """
    Test command: virsh blockpull <domain> <path>

    1) Prepare test environment.
    2) Populate a disk from its backing image.
    3) Recover test environment.
    4) Check result.
    """

    def make_disk_snapshot():
        # Add all disks into commandline.
        disks = vm.get_disk_devices()

        # Make three external snapshots for disks only
        for count in range(1, 4):
            options = "snapshot%s snap%s-desc " \
                      "--disk-only --atomic --no-metadata" % (count, count)

            for disk in disks:
                disk_detail = disks[disk]
                basename = os.path.basename(disk_detail['source'])

                # Remove the original suffix if any, appending ".snap[0-9]"
                diskname = basename.split(".")[0]
                disk_external = os.path.join(tmp_dir,
                                             "%s.snap%s" % (diskname, count))

                snapshot_external_disks.append(disk_external)
                options += " %s,snapshot=external,file=%s" % (disk, disk_external)

            cmd_result = virsh.snapshot_create_as(vm_name, options,
                                                  ignore_status=True, debug=True)
            status = cmd_result.exit_status
            if status != 0:
                raise error.TestFail("Failed to make snapshots for disks!")

            # Create a file flag in VM after each snapshot
            flag_file = tempfile.NamedTemporaryFile(prefix=("snapshot_test_"),dir="/tmp")
            file_path = flag_file.name
            flag_file.close()

            status, output = session.cmd_status_output("touch %s" % file_path)
            if status:
                raise error.TestFail("Touch file in vm failed. %s" % output)
            snapshot_flag_files.append(file_path)


    # MAIN TEST CODE ###
    # Process cartesian parameters
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login()

    with_timeout = ("yes" == params.get("with_timeout_option", "no"))
    status_error = ("yes" == params.get("status_error", "no"))
    base_option = params.get("base_option", "none")
    virsh_dargs = {'debug': True}

    # A backup of original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    logging.debug("original xml is %s", vmxml_backup)

    # Abort the test if there are snapshots already
    exsiting_snaps = virsh.snapshot_list(vm_name)
    if len(exsiting_snaps) != 0:
        raise error.TestFail("There are snapshots created for %s already" % vm_name)

    try:
        # Get a tmp_dir.
        tmp_dir = data_dir.get_tmp_dir()

        # The first disk is supposed to include OS
        # We will perform blockpull operation for it.
        first_disk = vm.get_first_disk_devices()

        snapshot_external_disks = []
        snapshot_flag_files = []
        make_disk_snapshot()

        blockpull_options = "--wait --verbose"

        if with_timeout:
            blockpull_options += " --timeout 1"

        base_image = None
        basename = os.path.basename(first_disk['source'])
        diskname = basename.split(".")[0]
        if base_option == "shallow":
            base_image = os.path.join(tmp_dir, "%s.snap2" % diskname)
        elif base_option == "base":
            base_image = os.path.join(tmp_dir, "%s.snap1" % diskname)
        elif base_option == "top":
            base_image = os.path.join(tmp_dir, "%s.snap3" % diskname)

        if base_option != "none":
            blockpull_options += " --base %s" % base_image

        # Run test case
        result = virsh.blockpull(vm_name, first_disk['target'],
                                 blockpull_options, **virsh_dargs)
        status = result.exit_status

        # Check status_error
        if status_error and status == 0:
            raise error.TestFail("Expect fail, but run successfully!")
        elif not status_error and  status != 0:
            raise error.TestFail("Run failed with right command")

        # If base image is the top layer of snapshot chain,
        # virsh blockpull should fail, return directly
        if base_option == "top":
            return

        # Check flag files
        for flag in snapshot_flag_files:
            status, output = session.cmd_status_output("cat %s" % flag)
            if status:
                raise error.TestFail("blockpull failed: %s" % output)

    finally:
        for disk in snapshot_external_disks:
            if os.path.exists(disk):
                os.remove(disk)

        # Recover xml of vm.
        vmxml_backup.sync()
