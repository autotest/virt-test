import os, time
from autotest.client.shared import error
from autotest.client import utils
from virttest import libvirt_vm, virsh
from virttest.libvirt_xml import vm_xml

def run_virsh_domblkinfo(test, params, env):
    """
    Test command: virsh domblkinfo.
    1.Prepare test environment. 
    2.Get vm's driver.
    3.According to driver perform virsh domblkinfo operation.
    4.Recover test environment. 
    5.Confirm the test result. 
    """

    vm_name = params.get("main_vm", "virt-test-vm1")
    vm = env.get_vm(vm_name)

    #run test case
    vm_ref = params.get("domblkinfo_vm_ref")
    device = params.get("domblkinfo_device", "yes")
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
        vm_ref = "%s %s" %(vm_name, extra)
    elif  vm_ref == "uuid":
        vm_ref = domuuid

    if vm_ref == "test_attach_disk":
        try:
            cmd_create_img = "dd if=/dev/zero of=%s count=512 bs=1024K" %\
                              test_attach_disk
            utils.run(cmd_create_img)
            front_dev = params.get ("domblkinfo_front_dev", "vdd")
            cmd_attach = "virsh attach-disk %s --target %s --source %s" %\
                          (vm_name, front_dev, test_attach_disk)
            utils.run(cmd_attach)
            vm_ref = vm_name
            result_source = virsh.domblkinfo(vm_ref, test_attach_disk, 
                                             ignore_status=True)
            status_source = result_source.exit_status
            output_source = result_source.stdout.strip()
            if driver == "qemu":
                result_target = virsh.domblkinfo(vm_ref, front_dev, 
                                                 ignore_status=True)
                status_target = result_target.exit_status
                output_target = result_target.stdout.strip()
            else:
                status_target = 0
                output_target = "xen doesn't support domblkinfo target!"

            cmd_detach = "virsh detach-disk %s --target %s" %\
                         (vm_name, front_dev)
            utils.run(cmd_detach)
        except error.CmdError:
            status_target = 1
            output_target = ""
            status_source = 1
            output_source = ""
    else:
        result_source = virsh.domblkinfo(vm_ref, test_disk_source, 
                                         ignore_status=True)
        status_source = result_source.exit_status
        output_source = result_source.stdout.strip()
        if driver == "qemu":
            result_target = virsh.domblkinfo(vm_ref, test_disk_target, 
                                             ignore_status=True)
            status_target = result_target.exit_status
            output_target = result_target.stdout.strip()
        else:
            status_target = 0
            output_target = "xen doesn't support domblkinfo target!"

    #recover enviremont
    if os.path.exists(test_attach_disk):
        os.remove(test_attach_disk)

    #check status_error
    if status_error == "yes":
        if status_target == 0 or status_source == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status_target != 0 or status_source != 0 or\
           output_target == "" or output_source == "":
            raise error.TestFail("Run failed with right command")
    else:
        raise error.TestFail("The status_error must be 'yes' or 'no'!")
