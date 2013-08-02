import logging
import re
import tempfile

from autotest.client.shared import error
from virttest import virsh, qemu_storage


def run_virsh_snapshot_disk(test, params, env):
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

    # Get a tmp_dir.
    tmp_dir = test.tmpdir
    # Create a image.
    params['image_name'] = "snapshot_test"
    params['image_format'] = image_format
    image = qemu_storage.QemuImg(params, tmp_dir, "snapshot_test")
    img_path, _ = image.create(params) 
    # Do the attach action.
    virsh.attach_disk(vm_name, source=img_path, target="vdf", extra="--persistent --subdriver %s" % image_format)

    # Init snapshot_name
    snapshot_name = None
    try:
        # Create snapshot.
        if snapshot_from_xml:
            snapshot_name = "snapshot_test"
            lines = ["<domainsnapshot>\n",
                     "<name>%s</name>\n" % snapshot_name,
                     "<description>Snapshot Test</description>\n",
                     "<memory snapshot=\'internal\'/>\n",
                     "</domainsnapshot>"]
            snapshot_xml_path = "%s/snapshot_xml" % tmp_dir
            snapshot_xml_file = open(snapshot_xml_path, "w")
            snapshot_xml_file.writelines(lines)
            snapshot_xml_file.close()
            snapshot_result = virsh.snapshot_create(vm_name, ("--xmlfile %s" % snapshot_xml_path))
            if snapshot_result.exit_status:
                if status_error:
                    return
                else:
                    raise error.TestFail("Failed to create snapshot. Error:%s."
                                         % snapshot_result.stderr.strip())
        else:
            snapshot_result = virsh.snapshot_create(vm_name)
            if snapshot_result.exit_status:
                if status_error:
                    return
                else:
                    raise error.TestFail("Failed to create snapshot. Error:%s."
                                         % snapshot_result.stderr.strip())
            snapshot_name = re.search("\d+", snapshot_result.stdout.strip()).group(0)


        # Touch a file in VM.
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
        revert_result = virsh.snapshot_revert(vm_name, snapshot_name)
        if revert_result.exit_status:
            raise error.TestFail("Revert snapshot failed. %s" % revert_result.stderr.strip())

        if not vm.is_alive():
            raise error.TestFail("Revert snapshot failed.")
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
            virsh.snapshot_delete(vm_name, snapshot_name)
