import time
import logging
from autotest.client.shared import error
from virttest import virsh, utils_test
from virttest.libvirt_xml import vm_xml
from xml.etree import ElementTree


def run_virsh_snapshot_par_cur(test, params, env):
    """
    Test command: virsh snapshot-parent, virsh snapshot-current
    Test cases: snapshot-parent --current name
                snapshot-parent no options
                snapshot-parent --current
                snapshot-parent --snapshotname name
                snapshot-current --name name
                snapshot-current --security-info
                snapshot-current --snapshotname name
                snapshot-current no options
    and all cases in readonly/readwrite mode
    """

    vm_name = params.get("main_vm")
    pstatus_error = params.get("parent_status_error", "no")
    cstatus_error = params.get("current_status_error", "no")
    snap_parent_opt = params.get("snapshot_parent_option")
    snap_cur_opt = params.get("snapshot_current_option")
    passwd = params.get("snapshot_current_passwd")
    snap_num = int(params.get("snapshot_num"))
    readonly = params.get("readonly", False)

    snap_opt = []
    for i in range(1, snap_num + 1):
        snap_opt.append(params.get("screate_opt%s" % i))

    # Do xml backup for final recovery
    vmxml_backup = vm_xml.VMXML.new_from_dumpxml(vm_name)

    # Add passwd for snapshot-current --security-info testing
    if snap_cur_opt is not None and "security-info" in snap_cur_opt:
        vm = env.get_vm(vm_name)
        if vm.is_alive():
            vm.destroy()
        vm_xml.VMXML.add_security_info(vm_xml.VMXML.new_from_dumpxml(vm_name),
                                       passwd)
        vm.start()

    def current_snapshot_test():
        """
        Do current snapshot test and xml check
        :params: xml_root: ElementTree object including snapshot xml info
        """

        output = virsh.snapshot_current(vm_name, snap_cur_opt,
                                        readonly=readonly)

        # If run fail with cstatus_error = no, then error will raise in command
        if cstatus_error == "yes":
            if output.exit_status == 0:
                raise error.TestFail("Unexpected snapshot-current success")
            else:
                logging.info("Failed to run snapshot-current as expected:%s",
                             output.stderr)
                return

        # Check if snapshot xml have security info
        if "--security-info" in snap_cur_opt and \
           "--name" not in snap_cur_opt:
            xml_root = ElementTree.fromstring(output)
            get_graphic = xml_root.find("domain/devices/graphics")
            try:
                if passwd == get_graphic.attrib["passwd"]:
                    logging.info("Success to check current snapshot with"
                                 " security info")
                else:
                    raise error.TestFail("Passwd is not same as set")
            except KeyError:
                raise error.TestFail("Can not find passwd in snapshot xml")

        # Check if --snapshotname may change current snapshot
        if "--snapshotname" in snap_cur_opt:
            current_snap = virsh.snapshot_current(vm_name, readonly=readonly)
            if current_snap == snap_cur_opt.split()[1]:
                logging.info("Success to check current snapshot changed to %s",
                             current_snap)
            else:
                raise error.TestFail("Failed to change current snapshot to %s,"
                                     "current is %s" %
                                    (snap_cur_opt.split()[1], current_snap))

    def parent_snapshot_check(snap_parent):
        """
        Do parent snapshot check
        :params: snap_parent: parent snapshot name that need to check
        """

        # get snapshot name which is parent snapshot's child
        if "--current" in snap_parent_opt:
            snap_name = virsh.snapshot_current(vm_name)
        else:
            snap_name = snap_parent_opt.split()[-1]

        # check parent snapshot in snapshot-list
        output = virsh.command("snapshot-list %s --parent" % vm_name).stdout
        for i in range(2, snap_num + 3):
            if output.split('\n')[i].split()[0] == snap_name:
                expect_name = output.split('\n')[i].split()[-1]
                break

        if snap_parent == expect_name:
            logging.info("Success to check parent snapshot")
        else:
            raise error.TestFail("Failed to check parent "
                                 "snapshot, expect %s, get %s"
                                 % (expect_name, snap_parent))

    def parent_snapshot_test():
        """
        Do parent snapshot test
        """

        cmd_result = virsh.snapshot_parent(vm_name, snap_parent_opt,
                                           readonly=readonly)

        # check status
        if pstatus_error == "yes":
            if cmd_result.exit_status == 0:
                raise error.TestFail("Unexpected success")
            else:
                logging.info("Run failed as expected:%s", cmd_result.stderr)
        elif cmd_result.exit_status != 0:
            raise error.TestFail("Run failed with right command:%s" %
                                 cmd_result.stderr)
        else:
            parent_snapshot_check(cmd_result.stdout.strip())

    try:
        # Create disk snapshot before all to make the origin image clean
        ret = virsh.snapshot_create_as(vm_name, "snap-temp --disk-only")
        if ret.exit_status != 0:
            raise error.TestFail("Fail to create temp snap, Error: %s",
                                 ret.stderr.strip())

        # Create snapshots
        for opt in snap_opt:
            result = virsh.snapshot_create_as(vm_name, opt)
            if result.exit_status:
                raise error.TestFail("Failed to create snapshot. Error:%s."
                                     % result.stderr.strip())
            time.sleep(1)

        # Do parent snapshot test
        if snap_parent_opt is not None:
            parent_snapshot_test()

        # Do current snapshot test
        if snap_cur_opt is not None:
            current_snapshot_test()

    finally:
        utils_test.libvirt.clean_up_snapshots(vm_name)
        vmxml_backup.sync("--snapshots-metadata")
