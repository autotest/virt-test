import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_xml
from virttest.libvirt_xml import vm_xml, xcepts


def run_virsh_dompmsuspend(test, params, env):
    """
    Test command: virsh dompmsuspend <domain> <target>
    The command suspends a running domain using guest OS's power management.
    """

    def check_vm_guestagent(session):
        # Check if qemu-ga already started automatically
        cmd = "rpm -q qemu-guest-agent || yum install -y qemu-guest-agent"
        stat_install = session.cmd_status(cmd, 300)
        if stat_install != 0:
            raise error.TestFail("Fail to install qemu-guest-agent, make"
                                 "sure that you have usable repo in guest")

        # Check if qemu-ga already started
        stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
        if stat_ps != 0:
            session.cmd("qemu-ga -d")
            # Check if the qemu-ga really started
            stat_ps = session.cmd_status("ps aux |grep [q]emu-ga")
            if stat_ps != 0:
                raise error.TestFail("Fail to run qemu-ga in guest")

    def check_pm_utils(session):
        # Check if pm-utils is present in vm
        cmd = "rpm -q pm-utils || yum install -y pm-utils"
        stat_install = session.cmd_status(cmd, 300)
        if stat_install != 0:
            raise error.TestFail("Fail to install pm-utils, make"
                                 "sure that you have usable repo in guest")

    # MAIN TEST CODE ###
    # Process cartesian parameters
    vm_name = params.get("main_vm")
    vm = env.get_vm(vm_name)

    vm_state = params.get("vm_state", "running")
    suspend_target = params.get("pm_suspend_target", "mem")
    status_error = "yes" == params.get("status_error", "yes")
    virsh_dargs = {'debug': True}

    # A backup of original vm
    vmxml_backup = vm_xml.VMXML.new_from_inactive_dumpxml(vm_name)
    logging.debug("original xml is %s", vmxml_backup)

    try:
        if vm.is_alive():
            vm.destroy()
        libvirt_xml.VMXML.set_agent_channel(vm_name)
        vm.start()
        session = vm.wait_for_login()

        check_vm_guestagent(session)
        check_pm_utils(session)

        session.close()

        # Set vm state
        if vm_state == "paused":
            vm.pause()
        elif vm_state == "shutoff":
            vm.destroy()

        # Run test case
        result = virsh.dompmsuspend(vm_name, suspend_target, **virsh_dargs)
        status = result.exit_status
        err = result.stderr.strip()

        # Check status_error
        if status_error:
            if status == 0 or err == "":
                raise error.TestFail("Expect fail, but run successfully!")
        else:
            if status != 0 or err != "":
                raise error.TestFail("Run failed with right command")
    finally:
        # cleanup
        if vm_state == "paused":
            vm.resume()

        if suspend_target == "mem" or suspend_target == "hybrid":
            if vm.state() == "pmsuspended":
                virsh.dompmwakeup(vm_name)

        # Recover xml of vm.
        vmxml_backup.sync()
