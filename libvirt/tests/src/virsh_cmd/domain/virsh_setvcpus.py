import re
import os
import logging
import commands
from autotest.client.shared import error, utils
from virttest import remote, virsh, libvirt_xml
from xml.dom.minidom import parse


def run_virsh_setvcpus(test, params, env):
    """
    Test command: virsh setvcpus.

    The conmand can change the number of virtual CPUs in the guest domain.
    1.Prepare test environment,destroy or suspend a VM.
    2.Perform virsh setvcpus operation.
    3.Recover test environment.
    4.Confirm the test result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    xml_file = params.get("setvcpus_xml_file", "vm.xml")
    tmp_file = params.get("setvcpus_tmp_file", "tmp.xml")
    pre_vm_state = params.get("setvcpus_pre_vm_state")
    command = params.get("setvcpus_command", "setvcpus")
    options = params.get("setvcpus_options", "")
    count = params.get("setvcpus_count", "equal")
    status_error = params.get("status_error", "no")

    def get_current_vcpus():
        """
        Get current vcpu number.
        """
        vcpus_set = ""
        virsh.dumpxml(vm_name, extra="", to_file=tmp_file)
        dom = parse(tmp_file)
        root = dom.documentElement
        vcpus_2 = root.getElementsByTagName("vcpu")
        for n in vcpus_2:
            if n.hasAttribute("current"):
                vcpus_set = int(n.getAttribute("current"))
        if vcpus_set == "":
            vcpus_set = int(vcpus_2[0].firstChild.data)
        dom.unlink()
        return vcpus_set

    def get_max_vcpus():
        """
        Get max vcpu number.
        """
        virsh.dumpxml(vm_name, extra="--inactive", to_file=tmp_file)
        dom = parse(tmp_file)
        root = dom.documentElement
        vcpus_2 = root.getElementsByTagName("vcpu")
        vcpus_set = int(vcpus_2[0].firstChild.data)
        dom.unlink()
        return vcpus_set

    def get_host_vcpus():
        """
        Get host vcpus.
        """
        result = utils.run("cat /proc/cpuinfo | grep \"processor\" | wc -l",
                           ignore_status=True)
        if result.exit_status:
            raise error.TestError("Failed to get host vcpus '%s'",
                                  result.stderr)
        return int(result.stdout)

    virsh.dumpxml(vm_name, extra="", to_file=xml_file)

    is_plug = False
    is_max = False
    current_vcpu_count = get_current_vcpus()
    host_vcpus = get_host_vcpus()

    if count == "add":
        is_plug = True
        new_vcpu_count = current_vcpu_count + 1
    elif count == "sub":
        new_vcpu_count = current_vcpu_count - 1
    elif count == "equal":
        new_vcpu_count = current_vcpu_count
    elif count == "guest":
        is_max = True
        new_vcpu_count = current_vcpu_count
    elif count == "host":
        is_max = True
        new_vcpu_count = host_vcpus
    else:
        raise error.TestError("Unknown setvcpus_count option '%s'", count)


    if is_plug:
        vm.destroy()
        vm_xml = libvirt_xml.VMXML()
        vm_xml.set_vm_vcpus(vm_name, new_vcpu_count)

    is_online = ((options.count("--live") or options.count("--current"))
                 and pre_vm_state != "shut off")

    if not vm.is_alive():
        vm.start()

    if is_online:
        if not is_plug and vm.driver_type != "xen":
            raise error.TestNAError("Vcpu hot unplug is available "
                                    "only with Xen.")
        else:
            if vm.driver_type == "qemu":
                status = virsh.qemu_monitor_command(vm.name,
                    "{ \"execute\": \"cpu-add\", \"arguments\": "
                    "{ \"id\": 0 } }", qmp=True)
                if status.exit_status:
                    raise error.TestNAError("Vcpu hot plug is not available "
                                            "with actual qemu version.")

    if is_max:
        options = "%s --maximum" % options

    session = None
    if pre_vm_state == "shut off":
        vm.destroy()
    else:
        session = vm.wait_for_login()

    if pre_vm_state == "paused":
        vm.pause()

    status = virsh.setvcpus(vm.name, new_vcpu_count, options,
                            ignore_status=True, debug=True)

    if pre_vm_state == "paused":
        virsh.resume(vm_name, ignore_status=True)

    fail_msg = None
    if is_online:
        s, o = session.cmd_status_output(
            "cat /proc/cpuinfo | grep \"processor\" | wc -l")
        if s:
            fail_msg = "Unexpected error '%s'" % o
        else:
            if int(o) != new_vcpu_count:
                fail_msg = ("The vcpu count in guest '%s' is different than "
                            "requested count '%s'" % (o, new_vcpu_count))

    if is_max:
        guest_max_vcpus = get_max_vcpus()
        if new_vcpu_count != guest_max_vcpus:
            fail_msg = ("The maximum count in guest '%s' is different than "
                        "requested count '%s'" % (new_vcpu_count,
                        guest_max_vcpus))

    virsh.destroy(vm_name)
    virsh.undefine(vm_name)
    virsh.define(xml_file)
    if os.path.exists(xml_file):
        os.remove(xml_file)
    if os.path.exists(tmp_file):
        os.remove(tmp_file)

    # check status_error
    requested_status = 0
    if status_error == "yes":
        requested_status = 1
    if status.exit_status != requested_status:
        logging.debug("requested status: %d\nexit status: %d",
            requested_status, status.exit_status)
        raise error.TestFail("Run failed with error message '%s'",
            status.stderr)
    if fail_msg:
        raise error.TestFail(fail_msg)
