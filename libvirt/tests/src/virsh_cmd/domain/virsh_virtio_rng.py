import re, os, commands, logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import libvirt_vm, virsh, virt_vm
from virttest.libvirt_xml import VMXML, LibvirtXMLError

def run_virsh_virtio_rng(test, params, env):
    """
    Test command: virsh virtio_rng checks
    whether guest comes with RNG.

    Convert domain XML config to a native guest configuration format.
    1.Prepare test environment.
    2.Perform virsh dumpxml to path configuration file.
    3.Edit the file with virtio_rng and define with it.
    4.Recover test environment.
    5.Confirm the test result.

    TODO : Run the egd daemon process in background on port 9000 and check.
    """

    def do_rename(vm, new_name, uuid=None, fail_info=[]):
        # Change name in XML
        logging.info("Rename %s to %s.", vm.name, new_name)
        try:
            vm = VMXML.vm_rename(vm, new_name, uuid)  # give it a new uuid
        except LibvirtXMLError, detail:
            raise error.TestFail("Rename %s to %s failed:\n%s"
                                         % (vm.name, new_name, detail))
        try:
            vm.start()
        except virt_vm.VMStartError, detail:
            fail_info.append("Start guest %s failed:%s"
                                          % (vm.name, detail))
        vm.destroy()
        return fail_info

    vm_name = params.get("main_vm")
    vm = env.get_vm(params["main_vm"])
    new_name = params.get("new_name", "test")
    uuid = vm.get_uuid()
    logging.info("Original uuid: %s", vm.get_uuid())
    fail_info = do_rename(vm, new_name)
    logging.info("Generated uuid: %s", vm.get_uuid())

    file_xml = params.get("dtn_file_xml")
    virsh.dumpxml(new_name, extra="", to_file=file_xml)
    h_rng=params.get("h_rng")
    s_rng=params.get("s_rng")

    def edit_rng(rng,file_xml):
        # Change the file with RNG
        edit_xml=open(file_xml, "r")
        lines_of_file = edit_xml.readlines()
        edit_xml.close()
        edit_xml=open(file_xml, "w")

        if (rng == "/dev/hwrng" or rng == "/dev/random") :
            lines_of_file.insert(-3, "<rng model=\'virtio\'> \n")
            lines_of_file.insert(-3, "<backend model='random'>%s</backend> \n" %rng)
            lines_of_file.insert(-3, "</rng> \n")
        if rng == "egd" :
            lines_of_file.insert(-3, "<rng model=\'virtio\'> \n")
            lines_of_file.insert(-3, "<backend model='egd' type='tcp'> \n")
            lines_of_file.insert(-3, "<source mode='connect' host='127.0.0.1' service='9000'/> \n")
            lines_of_file.insert(-3, "</backend> \n")
            lines_of_file.insert(-3, "</rng> \n")

        edit_xml.writelines(lines_of_file)
        edit_xml.close()


    # Hardware RNG
    edit_rng(h_rng,file_xml)

    # Software RNG
    s, o = commands.getstatusoutput("rpm -qa | grep egd")
    if s == 0 :
        s, o = commands.getstatusoutput("ps -ef | grep egd | grep 9000")
        if s == 0 :
            edit_rng(s_rng,file_xml)
    else:
        raise error.TestFail("egd is not installed or egd daemon is not running on port 9000")

    virsh.define(file_xml)
    vm.start()
    status=0

    os_type = params.get("os_type", "linux")
    try:
        if os_type == "linux":
            session = vm.wait_for_login()
            cmd = "cat /sys/devices/virtual/misc/hw_random/rng_available"
            s,o = session.cmd_status_output(cmd)
            o=o.strip()
            if o != "virtio":
                status=1
            s,o = session.cmd_status_output("ls /dev/hwrng")
            if s != 0:
                status=1
            s, o = session.cmd_status_output("lsmod | grep virtio")
            o=o.strip()
            if (s != 0 and o != "virtio_rng"):
                status=1

    except error.CmdError, detail:
        logging.debug("Debug failures %s" %detail)
    if status:
        raise error.TestFail("Run failed with right command")

    # Recover the environment
    fail_info = do_rename(vm, vm_name, uuid, fail_info)
    logging.info("Final uuid: %s", vm.get_uuid())

    if len(fail_info):
        raise error.TestFail(fail_info)

    if os.path.exsits(file_xml)
        os.remove(file_xml)
