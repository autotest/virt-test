from autotest.client.shared import error
from virttest import libvirt_vm, virsh, libvirt_xml

def run_virsh_domblkstat(test, params, env):
    """
    Test command: virsh domblkstat.

    The command get device block stats for a running domain.
    1.Prepare test environment.
    2.When the libvirtd == "off", stop the libvirtd service.
    3.Perform virsh domblkstat operation.
    4.Recover test environment.
    5.Confirm the test result.
    """
    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(vm_name)

    domid = vm.get_id()
    domuuid = vm.get_uuid()
    blklist = libvirt_xml.VMXML.get_disk_blk(vm_name)
    if blklist == None:
        raise error.TestFail("Cannot find disk in %s" % vm_name)
    #Select a block device from disks
    blk = blklist[0]
    libvirtd = params.get("libvirtd", "on")
    vm_ref = params.get("domblkstat_vm_ref")
    options = params.get("domblkstat_option", "")
    status_error = params.get("status_error", "no")
    if params.get("domblkinfo_dev") == "no":
        blk = ""

    if vm_ref == "id":
        vm_ref = domid
    elif  vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = "%s %s" % (vm_name, params.get("domblkstat_extra"))

    option_list = options.split(" ")
    for option in option_list:
        if virsh.has_command_help_match("domblkstat", option) == None:
            status_error = "yes"
            break
    if libvirtd == "off":
        libvirt_vm.libvirtd_stop()

    result = virsh.domblkstat(vm_ref, blk, options, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()

    #recover libvirtd service start
    if libvirtd == "off":
        libvirt_vm.libvirtd_start()
    #check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
