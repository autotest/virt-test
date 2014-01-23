import os
import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_xml


def reset_domain(vm, vm_state, needs_agent=False):
    """
    Set domain vcpu number to 4 and current vcpu as 1

    :param vm: the vm object
    :param vm_state: the given vm state string "shut off" or "running"
    """
    if vm.is_alive():
        vm.destroy()
    vm_xml = libvirt_xml.VMXML()
    vm_xml.set_vm_vcpus(vm.name, 4, 1)
    if needs_agent:
        logging.debug("Attempting to set guest agent channel")
        vm_xml.set_agent_channel(vm.name)
    if not vm_state == "shut off":
        vm.start()
        session = vm.wait_for_login()
        if needs_agent:
            # Check if qemu-ga already started automatically
            cmd = "rpm -q qemu-guest-agent || yum install -y qemu-guest-agent"
            stat_install = session.cmd_status(cmd, 300)
            if stat_install != 0:
                raise error.TestFail("Fail to install qemu-guest-agent, make "
                                     "sure that you have usable repo in guest")

            # Check if qemu-ga already started
            stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
            if stat_ps != 0:
                session.cmd("qemu-ga -d")
                # Check if the qemu-ga really started
                stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
                if stat_ps != 0:
                    raise error.TestFail("Fail to run qemu-ga in guest")


def chk_output_running(output, expect_out, options):
    """
    Check vcpucount when domain is running

    :param output: the output of vcpucount command
    :param expect_out: the list of expected result
    :parma options: the vcpucount command options string
    """
    if options == "":
        out = output.split('\n')
        for i in range(4):
            if int(out[i].split()[-1]) != expect_out[i]:
                raise error.TestFail("Output is not expected")
    elif "--config" in options:
        if "--active" in options:
            if int(output) != expect_out[2]:
                raise error.TestFail("Output is not expected")
        elif "--maximum" in options:
            if int(output) != expect_out[0]:
                raise error.TestFail("Output is not expected")
        elif "--current" in options:
            pass
        elif "--live" in options:
            pass
        elif options == "--config":
            pass
        else:
            raise error.TestFail("Options %s should failed" % options)
    elif "--live" or "--current" in options:
        if "--active" in options:
            if int(output) != expect_out[3]:
                raise error.TestFail("Output is not expected")
        elif "--maximum" in options:
            if int(output) != expect_out[1]:
                raise error.TestFail("Output is not expected")
        elif "--guest" in options:
            pass
        elif options == "--live" or options == "--current":
            pass
        else:
            raise error.TestFail("Options %s should failed" % options)
    elif options == "--active":
        pass
    elif options == "--guest":
        if int(output) != expect_out[4]:
            raise error.TestFail("Output is not expected")
    else:
        raise error.TestFail("Options %s should failed" % options)


def chk_output_shutoff(output, expect_out, options):
    """
    Check vcpucount when domain is shut off

    :param output: the output of vcpucount command
    :param expect_out: the list of expected result
    :param options: the vcpucount command options string
    """
    if options == "":
        out = output.split('\n')
        for i in range(2):
            if int(out[i].split()[-1]) != expect_out[i]:
                raise error.TestFail("Output is not expected")
    elif "--config" or "--current" in options:
        if "--active" in options:
            if int(output) != expect_out[1]:
                raise error.TestFail("Output is not expected")
        elif "--maximum" in options:
            if int(output) != expect_out[0]:
                raise error.TestFail("Output is not expected")
        elif options == "--config" or options == "--current":
            pass
        else:
            raise error.TestFail("Options %s should failed" % options)
    else:
        raise error.TestFail("Options %s should failed" % options)


def reset_env(vm_name, xml_file):
    virsh.destroy(vm_name)
    virsh.undefine(vm_name)
    virsh.define(xml_file)
    if os.path.exists(xml_file):
        os.remove(xml_file)


def run(test, params, env):
    """
    Test the command virsh vcpucount

    (1) Iterate perform setvcpus operation with four valid options.
    (2) Iterate call virsh vcpucount with given options.
    (3) Check whether the virsh vcpucount works as expected.
    (4) Recover test environment.

    The test works for domain state as "shut off" or "running", it check
    vcpucount result after vcpu hotplug using setvcpus.

    For setvcpus, include four valid options:
      --config
      --config --maximum
      --live
      --guest

    For vcpucount options, restrict up to 2 options together, upstream libvirt
    support more options combinations now (e.g. 3 options together or single
    --maximum option), for backward support, only following options are
    checked:
      None
      --config --active
      --config --maximum
      --live --active
      --live --maximum
      --current --active
      --current --maximum
      --guest
    """

    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)
    xml_file = params.get("vcpucount_xml_file", "vm.xml")
    virsh.dumpxml(vm_name, extra="--inactive", to_file=xml_file)
    pre_vm_state = params.get("vcpucount_pre_vm_state")
    options = params.get("vcpucount_options")
    status_error = params.get("status_error")
    set_option = ["--config", "--config --maximum", "--live", "--guest"]

    # maximum options should be 2
    if len(options.split()) > 2:
        raise error.TestNAError("Options exceeds 2 is not supported")

    # Prepare domain
    try:
        reset_domain(vm, pre_vm_state, (options == "--guest"))
    except Exception, details:
        reset_env(vm_name, xml_file)
        error.TestFail(details)

    # Perform guest vcpu hotplug
    for i in range(len(set_option)):
        # Hotplug domain vcpu
        result = virsh.setvcpus(vm_name, 2, set_option[i], ignore_status=True,
                                debug=True)
        setvcpus_status = result.exit_status

        # Call virsh vcpucount with option
        result = virsh.vcpucount(vm_name, options, ignore_status=True,
                                 debug=True)
        output = result.stdout.strip()
        vcpucount_status = result.exit_status

        if "--guest" in options:
            if result.stderr.count("doesn't support option") or \
               result.stderr.count("command guest-get-vcpus has not been found"):
                reset_env(vm_name, xml_file)
                raise error.TestNAError("Option %s is not supported" % options)

        # Reset domain
        reset_domain(vm, pre_vm_state)

        # Check result
        if status_error == "yes":
            if vcpucount_status == 0:
                reset_env(vm_name, xml_file)
                raise error.TestFail("Run successfully with wrong command!")
            else:
                logging.info("Run failed as expected")
        else:
            if vcpucount_status != 0:
                reset_env(vm_name, xml_file)
                raise error.TestFail("Run command failed with options %s" %
                                     options)
            elif setvcpus_status == 0:
                if pre_vm_state == "shut off":
                    if i == 0:
                        expect_out = [4, 2]
                        chk_output_shutoff(output, expect_out, options)
                    elif i == 1:
                        expect_out = [2, 1]
                        chk_output_shutoff(output, expect_out, options)
                    else:
                        reset_env(vm_name, xml_file)
                        raise error.TestFail("setvcpus should failed")
                else:
                    if i == 0:
                        expect_out = [4, 4, 2, 1, 1]
                        chk_output_running(output, expect_out, options)
                    elif i == 1:
                        expect_out = [2, 4, 1, 1, 1]
                        chk_output_running(output, expect_out, options)
                    elif i == 2:
                        expect_out = [4, 4, 1, 2, 2]
                        chk_output_running(output, expect_out, options)
                    else:
                        expect_out = [4, 4, 1, 1, 2]
                        chk_output_running(output, expect_out, options)
            else:
                if pre_vm_state == "shut off":
                    expect_out = [4, 1]
                    chk_output_shutoff(output, expect_out, options)
                else:
                    expect_out = [4, 4, 1, 1, 1]
                    chk_output_running(output, expect_out, options)

    # Recover env
    reset_env(vm_name, xml_file)
