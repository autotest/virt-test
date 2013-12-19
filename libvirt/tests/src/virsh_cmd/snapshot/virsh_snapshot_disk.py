import os
import logging
import re
import tempfile

from autotest.client.shared import error
from virttest import virsh, qemu_storage, data_dir


def run(test, params, env):
    """
    Test virsh snapshot command when disk in all kinds of type.

    (1). Init the variables from params.
    (2). Create a image by specifice format.
    (3). Attach disk to vm.
    (4). Snapshot create.
    (5). Snapshot revert.
    (6). cleanup.
    """
    # Init variables.
    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm = env.get_vm(vm_name)
    image_format = params.get("snapshot_image_format", "qcow2")
    status_error = ("yes" == params.get("status_error", "no"))
    snapshot_from_xml = ("yes" == params.get("snapshot_from_xml", "no"))
    snapshot_current = ("yes" == params.get("snapshot_current", "no"))
    snapshot_revert_paused = ("yes" == params.get("snapshot_revert_paused",
                                                  "no"))

    # Some variable for xmlfile of snapshot.
    snapshot_memory = params.get("snapshot_memory", "internal")
    snapshot_disk = params.get("snapshot_disk", "internal")

    # Get a tmp_dir.
    tmp_dir = data_dir.get_tmp_dir()
    # Create a image.
    params['image_name'] = "snapshot_test"
    params['image_format'] = image_format
    params['image_size'] = "1M"
    image = qemu_storage.QemuImg(params, tmp_dir, "snapshot_test")
    img_path, _ = image.create(params)
    # Do the attach action.
    result = virsh.attach_disk(vm_name, source=img_path, target="vdf",
                               extra="--persistent --subdriver %s" % image_format)
    if result.exit_status:
        raise error.TestNAError("Failed to attach disk %s to VM."
                                "Detail: %s." % (img_path, result.stderr))

    # Init snapshot_name
    snapshot_name = None
    snapshot_external_disk = []
    try:
        # Create snapshot.
        if snapshot_from_xml:
            snapshot_name = "snapshot_test"
            lines = ["<domainsnapshot>\n",
                     "<name>%s</name>\n" % snapshot_name,
                     "<description>Snapshot Test</description>\n"]
            if snapshot_memory == "external":
                memory_external = os.path.join(tmp_dir, "snapshot_memory")
                snapshot_external_disk.append(memory_external)
                lines.append("<memory snapshot=\'%s\' file='%s'/>\n" %
                             (snapshot_memory, memory_external))
            else:
                lines.append("<memory snapshot='%s'/>\n" % snapshot_memory)

            # Add all disks into xml file.
            disks = vm.get_disk_devices().values()
            lines.append("<disks>\n")
            for disk in disks:
                lines.append("<disk name='%s' snapshot='%s'>\n" %
                             (disk['source'], snapshot_disk))
                if snapshot_disk == "external":
                    disk_external = os.path.join(tmp_dir,
                                                 "%s.snap" % os.path.basename(disk['source']))
                    snapshot_external_disk.append(disk_external)
                    lines.append("<source file='%s'/>\n" % disk_external)
                lines.append("</disk>\n")
            lines.append("</disks>\n")
            lines.append("</domainsnapshot>")

            snapshot_xml_path = "%s/snapshot_xml" % tmp_dir
            snapshot_xml_file = open(snapshot_xml_path, "w")
            snapshot_xml_file.writelines(lines)
            snapshot_xml_file.close()
            snapshot_result = virsh.snapshot_create(
                vm_name, ("--xmlfile %s" % snapshot_xml_path))
            if snapshot_result.exit_status:
                if status_error:
                    return
                else:
                    raise error.TestFail("Failed to create snapshot. Error:%s."
                                         % snapshot_result.stderr.strip())
        else:
            options = ""
            snapshot_result = virsh.snapshot_create(vm_name, options)
            if snapshot_result.exit_status:
                if status_error:
                    return
                else:
                    raise error.TestFail("Failed to create snapshot. Error:%s."
                                         % snapshot_result.stderr.strip())
            snapshot_name = re.search(
                "\d+", snapshot_result.stdout.strip()).group(0)
            if snapshot_current:
                lines = ["<domainsnapshot>\n",
                         "<description>Snapshot Test</description>\n",
                         "<state>running</state>\n",
                         "<creationTime>%s</creationTime>" % snapshot_name,
                         "</domainsnapshot>"]
                snapshot_xml_path = "%s/snapshot_xml" % tmp_dir
                snapshot_xml_file = open(snapshot_xml_path, "w")
                snapshot_xml_file.writelines(lines)
                snapshot_xml_file.close()
                options += "--redefine %s --current" % snapshot_xml_path
                if snapshot_result.exit_status:
                    raise error.TestFail("Failed to create snapshot --current."
                                         "Error:%s." %
                                         snapshot_result.stderr.strip())

        if status_error:
            raise error.TestFail("Success to create snapshot in negative case\n"
                                 "Detail: %s" % snapshot_result)

        # Touch a file in VM.
        if vm.is_dead():
            vm.start()
        session = vm.wait_for_login()

        # Init a unique name for tmp_file.
        tmp_file = tempfile.NamedTemporaryFile(prefix=("snapshot_test_"),
                                               dir="/tmp")
        tmp_file_path = tmp_file.name
        tmp_file.close()

        status, output = session.cmd_status_output("touch %s" % tmp_file_path)
        if status:
            raise error.TestFail("Touch file in vm failed. %s" % output)

        session.close()

        # Destroy vm for snapshot revert.
        virsh.destroy(vm_name)
        # Revert snapshot.
        revert_options = ""
        if snapshot_revert_paused:
            revert_options += " --paused"
        revert_result = virsh.snapshot_revert(vm_name, snapshot_name,
                                              revert_options)
        if revert_result.exit_status:
            raise error.TestFail(
                "Revert snapshot failed. %s" % revert_result.stderr.strip())

        if vm.is_dead():
            raise error.TestFail("Revert snapshot failed.")

        if snapshot_revert_paused:
            if vm.is_paused():
                vm.resume()
            else:
                raise error.TestFail("Revert command successed, but VM is not "
                                     "paused after reverting with --paused option.")
        # login vm.
        session = vm.wait_for_login()
        # Check the result of revert.
        status, output = session.cmd_status_output("cat %s" % tmp_file_path)
        if not status:
            raise error.TestFail("Tmp file exists, revert failed.")

        # Close the session.
        session.close()

    finally:
        virsh.detach_disk(vm_name, target="vdf", extra="--persistent")
        image.remove()
        if snapshot_name:
            virsh.snapshot_delete(vm_name, snapshot_name, "--metadata")
        for disk in snapshot_external_disk:
            if os.path.exists(disk):
                os.remove(disk)
