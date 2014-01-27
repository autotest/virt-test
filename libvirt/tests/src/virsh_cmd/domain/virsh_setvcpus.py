import re
import os
import logging
from autotest.client.shared import error
from virttest import remote, virsh, libvirt_xml, libvirt_vm
from xml.dom.minidom import parse

def remote_test(remote_ip, local_ip, remote_pwd, remote_prompt, vm_name):
    """
    Test remote case
    """
    err = ""
    try:
        remote_uri = libvirt_vm.complete_uri(local_ip)
        session = remote.remote_login("ssh", remote_ip, "22",
                                      "root", remote_pwd, remote_prompt)
        session.cmd_output('LANG=C')
        command = "virsh -c %s setvcpus %s 1 --live" % (remote_uri, vm_name)
        if virsh.has_command_help_match(command, "--live") is None:
            status_error = "yes"
        status, output = session.cmd_status_output(command, internal_timeout=5)
        session.close()
        if status != 0:
            err = output
    except error.CmdError:
        status = 1
        status_error = "yes"
        err = "remote test failed"
    return status, status_error, err

def get_xmldata(vm_name, xml_file, options):
    """
    Get some values out of the guests xml
    Returns:
        count => Number of vCPUs set for the guest
        current => If there is a 'current' value set
                   in the xml indicating the ability
                   to add vCPUs. If 'current' is not
                   set, then return 0 for this value.
        os_machine => Name of the <os> <type machine=''>
                      to be used to determine if we can
                      support hotplug
    """
    # Grab a dump of the guest - if we're using the --config,
    # then get an --inactive dump.
    extra_opts=""
    if "--config" in options:
        extra_opts="--inactive"
    vcpus_current = ""
    virsh.dumpxml(vm_name, extra=extra_opts, to_file=xml_file)
    dom = parse(xml_file)
    root = dom.documentElement
    # get the vcpu value
    vcpus_parent = root.getElementsByTagName("vcpu")
    vcpus_count = int(vcpus_parent[0].firstChild.data)
    for n in vcpus_parent:
        vcpus_current += n.getAttribute("current")
        if vcpus_current != "":
            vcpus_current = int(vcpus_current)
        else:
            vcpus_current = 0
    # get the machine type
    os_parent = root.getElementsByTagName("os")
    os_machine = ""
    for os_elem in os_parent:
        for node in os_elem.childNodes:
            if node.nodeName == "type":
                os_machine = node.getAttribute("machine")
    dom.unlink()
    return vcpus_count, vcpus_current, os_machine

def run(test, params, env):
    """
    Test command: virsh setvcpus.

    The command can change the number of virtual CPUs in the guest domain.
    1.Prepare test environment,destroy or suspend a VM.
    2.Perform virsh setvcpus operation.
    3.Recover test environment.
    4.Confirm the test result.
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    pre_vm_state = params.get("setvcpus_pre_vm_state")
    command = params.get("setvcpus_command", "setvcpus")
    options = params.get("setvcpus_options")
    vm_ref = params.get("setvcpus_vm_ref", "name")
    count = params.get("setvcpus_count")
    set_current = int(params.get("setvcpus_current","0"))
    extra_param = params.get("setvcpus_extra_param")
    count_option = "%s %s" % (count, extra_param)
    status_error = params.get("status_error")
    remote_ip = params.get("remote_ip", "REMOTE.EXAMPLE.COM")
    local_ip = params.get("local_ip", "LOCAL.EXAMPLE.COM")
    remote_pwd = params.get("remote_pwd", "")
    remote_prompt = params.get("remote_prompt", "#")
    tmpxml = os.path.join(test.tmpdir, 'tmp.xml')
    test_set_max = 2

    # Early death
    if vm_ref == "remote" and (remote_ip.count("EXAMPLE.COM") or
                               local_ip.count("EXAMPLE.COM")):
        raise error.TestNAError("remote/local ip parameters not set.")

    # Save original configuration
    orig_config_xml = libvirt_xml.VMXML.new_from_inactive_dumpxml(vm_name)

    # Get the number of cpus, current value if set, and machine type
    orig_set, orig_current, mtype = get_xmldata(vm_name, tmpxml, options)
    logging.debug("orig_set=%d orig_current=%d mtype=%s",
                  orig_set, orig_current, mtype)

    # Normal processing of the test is to set the vcpu count to 2 and then
    # adjust the 'current_vcpu' value to 1 effectively removing a vcpu.
    #
    # This is generally fine when the guest is not running; however, the
    # hotswap functionality hasn't always worked very well and is under
    # going lots of change from using the hmp "cpu_set" command in 1.5
    # to a new qmp "cpu-add" added in 1.6 where the "cpu-set" command
    # seems to have been deprecated making things very messy.
    #
    # To further muddy the waters, the "cpu-add" functionality is supported
    # for specific machine type versions. For the purposes of this test that
    # would be "pc-i440fx-1.5" or "pc-q35-1.5" or later type machines (from
    # guest XML "<os> <type ... machine=''/type> </os>"). Depending on which
    # version of qemu/kvm was used to initially create/generate the XML for
    # the machine this could result in a newer qemu still using 1.4 or earlier
    # for the machine type.
    #
    # If the set_current is set, then we are adding CPU's, thus we must
    # set then 'current_vcpu' value to something lower than our count in
    # order to test that if we start with a current=1 and a count=2 that we
    # can set our current up to our count. If our orig_set count is 1, then
    # don't add a vCPU to a VM that perhaps doesn't want one.  We still need
    # to check if 'virsh setvcpus <domain> 1' would work, so continue on.
    #
    if set_current != 0 and orig_set >= 2:
        if vm.is_alive():
            vm.destroy()
        vm_xml = libvirt_xml.VMXML()
        if set_current >= test_set_max:
            raise error.TestFail("Current(%d) >= test set max(%d)" %
                                 (set_current, test_set_max))
        vm_xml.set_vm_vcpus(vm_name, test_set_max, set_current)
        # Restart, unless that's not our test
        if pre_vm_state != "shut off":
            vm.start()
            vm.wait_for_login()

    if orig_set == 1:
        logging.debug("Original vCPU count is 1, just checking if setvcpus "
                      "can still set current.")

    domid = vm.get_id() # only valid for running
    domuuid = vm.get_uuid()

    if pre_vm_state == "paused":
        vm.pause()
    elif pre_vm_state == "shut off" and vm.is_alive():
        vm.destroy()

    try:
        if vm_ref == "remote":
            setvcpu_exit_status, status_error, \
            setvcpu_exit_stderr = remote_test(remote_ip,
                                              local_ip,
                                              remote_pwd,
                                              remote_prompt,
                                              vm_name)
        else:
            if vm_ref == "name":
                dom_option = vm_name
            elif vm_ref == "id":
                dom_option = domid
                if params.get("setvcpus_hex_id") is not None:
                    dom_option = hex(int(domid))
                elif params.get("setvcpus_invalid_id") is not None:
                    dom_option = params.get("setvcpus_invalid_id")
            elif vm_ref == "uuid":
                dom_option = domuuid
                if params.get("setvcpus_invalid_uuid") is not None:
                    dom_option = params.get("setvcpus_invalid_uuid")
            else:
                dom_option = vm_ref

            option_list = options.split(" ")
            for item in option_list:
                if virsh.has_command_help_match(command, item) is None:
                    status_error = "yes"
                    break
            status = virsh.setvcpus(dom_option, count_option, options,
                                    ignore_status=True, debug=True)
            setvcpu_exit_status = status.exit_status
            setvcpu_exit_stderr = status.stderr.strip()

    finally:
        vcpus_set, vcpus_current, mtype = get_xmldata(vm_name, tmpxml, options)

        # Cleanup
        if pre_vm_state == "paused":
            virsh.resume(vm_name, ignore_status=True)
        orig_config_xml.sync()

    # check status_error
    if status_error == "yes":
        if setvcpu_exit_status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if setvcpu_exit_status != 0:
            # setvcpu/hotplug is only available as of qemu 1.5 and it's still
            # evolving. In general the addition of vcpu's may use the QMP
            # "cpu_set" (qemu 1.5) or "cpu-add" (qemu 1.6 and later) commands.
            # The removal of vcpu's may work in qemu 1.5 due to how cpu_set
            # can set vcpus online or offline; however, there doesn't appear
            # to be a complementary cpu-del feature yet, so we can add, but
            # not delete in 1.6.

            # A 1.6 qemu will not allow the cpu-add command to be run on
            # a configuration using <os> machine property 1.4 or earlier.
            # That is the XML <os> element with the <type> property having
            # an attribute 'machine' which is a tuple of 3 elements separated
            # by a dash, such as "pc-i440fx-1.5" or "pc-q35-1.5".
            if re.search("unable to execute QEMU command 'cpu-add'",
                         setvcpu_exit_stderr):
                raise error.TestNAError("guest <os> machine property '%s' "
                                        "may be too old to allow hotplug.",
                                        mtype)

            # A qemu older than 1.5 or an unplug for 1.6 will result in
            # the following failure.  In general, any time libvirt determines
            # it cannot support adding or removing a vCPU...
            if re.search("cannot change vcpu count of this domain",
                         setvcpu_exit_stderr):
                raise error.TestNAError("virsh setvcpu hotplug unsupported, "
                                        " mtype=%s" % mtype)

            # Otherwise, it seems we have a real error
            raise error.TestFail("Run failed with right command mtype=%s stderr=%s" %
                                 (mtype, setvcpu_exit_stderr))
        else:
            if "--maximum" in options:
                if vcpus_set != int(count):
                    raise error.TestFail("failed to set --maximum vcpus "
                                         "to %s mtype=%s" %
                                         (count, mtype))
            else:
                if orig_set >= 2 and set_current != 0:
                    # If we're adding a cpu we go from:
                    #    <vcpu ... current='1'...>2</vcpu>
                    # to
                    #    <vcpu ... >2</vcpu>
                    # where vcpus_current will be 0 and vcpus_set will be 2
                    if vcpus_current != 0 and vcpus_set != test_set_max:
                        raise error.TestFail("Failed to add current=%d, "
                                             "set=%d, count=%d mtype=%s" %
                                             (vcpus_current, vcpus_set,
                                             test_set_max, mtype))
                elif orig_set >= 2 and set_current == 0:
                    # If we're removing a cpu we go from:
                    #    <vcpu ... >2</vcpu>
                    # to
                    #    <vcpu ... current='1'...>2</vcpu>
                    # where vcpus_current will be 1 and vcpus_set will be 2
                    if vcpus_current != 1 and vcpus_set != test_set_max:
                        raise error.TestFail("Failed to remove current=%d, "
                                             "set=%d, count=%d mtype=%s" %
                                             (vcpus_current, vcpus_set,
                                             test_set_max, mtype))
                # If we have a starting place of 1 vCPUs, then this is rather
                # boring and innocuous case, but libvirt will succeed, so just
                # handle it
                elif orig_set == 1 and vcpus_current != 0 and vcpus_set != 1:
                    raise error.TestFail("Failed when orig_set is 1 current=%d, "
                                             "set=%d, count=%d mtype=%s" %
                                             (vcpus_current, vcpus_set,
                                             test_set_max, mtype))
