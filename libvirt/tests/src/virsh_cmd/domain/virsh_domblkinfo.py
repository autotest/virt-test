import os
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import vm_xml


def run(test, params, env):
    """
    Test command: virsh domblkinfo.
    1.Prepare test environment.
    2.Get vm's driver.
    3.According to driver perform virsh domblkinfo operation.
    4.Recover test environment.
    5.Confirm the test result.
    """

    def attach_disk_test():
        """
        Attach-disk testcase.
        1.Attch a disk to guest.
        2.Perform domblkinfo operation.
        3.Detach the disk.

        :return: Command status and output.
        """
        try:
            source_file = open(test_disk_source, 'wb')
            source_file.seek((512 * 1024 * 1024) - 1)
            source_file.write(str(0))
            source_file.close()
            virsh.attach_disk(vm_name, test_disk_source, front_dev, debug=True)
            vm_ref = vm_name
            result_source = virsh.domblkinfo(vm_ref, test_disk_source,
                                             ignore_status=True, debug=True)
            status_source = result_source.exit_status
            output_source = result_source.stdout.strip()
            if driver == "qemu":
                result_target = virsh.domblkinfo(vm_ref, front_dev,
                                                 ignore_status=True, debug=True)
                status_target = result_target.exit_status
                output_target = result_target.stdout.strip()
            else:
                status_target = 0
                output_target = "Xen doesn't support domblkinfo target!"
            virsh.detach_disk(vm_name, front_dev, debug=True)
            return status_target, output_target, status_source, output_source
        except (error.CmdError, IOError):
            return 1, "", 1, ""

    def check_disk_info():
        """
        Ckeck virsh domblkinfo output.
        """
        if driver == "qemu" and output_source.strip() != output_target.strip():
            raise error.TestFail("Command domblkinfo target/source"
                                 " got different information!")
        if output_source != "":
            lines = output_source.splitlines()
            capacity_cols = lines[0].split(":")
            size = int(capacity_cols[1].strip())
            if disk_size != size and disk_size_check:
                raise error.TestFail("Command domblkinfo output is wrong! "
                                     "'%d' != '%d'" % (disk_size, size))
        else:
            raise error.TestFail("Command domblkinfo has no output!")

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    # Get all parameters from configuration.
    vm_ref = params.get("domblkinfo_vm_ref")
    device = params.get("domblkinfo_device", "yes")
    front_dev = params.get("domblkinfo_front_dev", "vdd")
    extra = params.get("domblkinfo_extra", "")
    status_error = params.get("status_error", "no")
    test_attach_disk = os.path.join(test.virtdir, "tmp.img")

    domid = vm.get_id()
    domuuid = vm.get_uuid()
    driver = virsh.driver()

    blklist = vm_xml.VMXML.get_disk_blk(vm_name)
    sourcelist = vm_xml.VMXML.get_disk_source(vm_name)
    test_disk_target = blklist[0]
    test_disk_source = sourcelist[0].find('source').get('file')
    test_disk_format = sourcelist[0].find('driver').get('type')

    disk_size_check = False
    if test_disk_format == "raw":
        disk_size_check = True
    if device == "no":
        test_disk_target = ""
        test_disk_source = ""

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, extra)
    elif vm_ref == "uuid":
        vm_ref = domuuid

    if vm_ref == "test_attach_disk":
        test_disk_source = test_attach_disk
        disk_size_check = True
        (status_target, output_target,
         status_source, output_source) = attach_disk_test()
    else:
        result_source = virsh.domblkinfo(vm_ref, test_disk_source,
                                         ignore_status=True, debug=True)
        status_source = result_source.exit_status
        output_source = result_source.stdout.strip()
        if driver == "qemu":
            result_target = virsh.domblkinfo(vm_ref, test_disk_target,
                                             ignore_status=True, debug=True)
            status_target = result_target.exit_status
            output_target = result_target.stdout.strip()
        else:
            status_target = 0
            output_target = "xen doesn't support domblkinfo target!"
    disk_size = 0
    if os.path.exists(test_disk_source):
        disk_size = os.path.getsize(test_disk_source)

    # Recover enviremont
    if os.path.exists(test_attach_disk):
        os.remove(test_attach_disk)

    # Check status_error
    if status_error == "yes":
        if status_target == 0 or status_source == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status_target != 0 or status_source != 0:
            raise error.TestFail("Run failed with right command")
        # Check source information.
        check_disk_info()
    else:
        raise error.TestFail("The status_error must be 'yes' or 'no'!")
