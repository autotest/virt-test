import os
import logging
import commands
import time
from autotest.client.shared import error
from virttest.libvirt_xml import vm_xml
from virttest import virsh, aexpect
from virttest.libvirt_xml.devices.emulator import Emulator
from virttest.libvirt_xml.devices.console import Console


def run(test, params, env):
    """
    Virsh create test with --pass-fds for container
    """
    fds_options = params.get("create_lxc_fds_options", "")
    other_options = params.get("create_lxc_other_options", "")
    uri = params.get("connect_uri", "lxc:///")
    vm_name = params.get("vms")
    vcpu = params.get("create_lxc_vcpu", 1)
    max_mem = params.get("create_lxc_maxmem", 500000)
    cur_mem = params.get("create_lxc_curmem", 500000)
    dom_type = params.get("create_lxc_domtype", "lxc")
    os_type = params.get("create_lxc_ostype", "exe")
    os_arch = params.get("create_lxc_osarch", "x86_64")
    os_init = params.get("create_lxc_osinit", "/bin/sh")
    emulator_path = params.get("create_lxc_emulator",
                               "/usr/libexec/libvirt_lxc")
    tmpfile1 = params.get("create_lxc_tmpfile1", "/tmp/foo")
    tmpfile2 = params.get("create_lxc_tmpfile2", "/tmp/bar")
    tmpfile3 = params.get("create_lxc_tmpfile3", "/tmp/wizz")

    def container_xml_generator():
        """
        Generate container xml
        """
        vmxml = vm_xml.VMXML(dom_type)
        vmxml.vm_name = vm_name
        vmxml.max_mem = max_mem
        vmxml.current_mem = cur_mem
        vmxml.vcpu = vcpu
        vmxml.os_type = os_type
        vmxml.os_arch = os_arch
        vmxml.os_init = os_init
        # Generate emulator
        emulator = Emulator()
        emulator.path = emulator_path
        # Generate console
        console = Console()
        # Add emulator and console in devices
        devices = vm_xml.VMXMLDevices()
        devices.append(emulator)
        devices.append(console)
        logging.debug("device is %s", devices)
        vmxml.set_devices(devices)
        return vmxml

    fd1 = open(tmpfile1, 'w')
    fd2 = open(tmpfile2, 'w')
    fd3 = open(tmpfile3, 'w')

    try:
        options = "%s %s,%s,%s %s" % (fds_options, fd1.fileno(), fd2.fileno(),
                                      fd3.fileno(), other_options)
        vmxml = container_xml_generator()
        logging.debug("xml is %s", commands.getoutput("cat %s" % vmxml.xml))
        if "--console" not in options:
            output = virsh.create(vmxml.xml, options, uri=uri)
            if output.exit_status:
                raise error.TestFail("Create %s domain failed:%s" %
                                     (dom_type, output.stderr))
            logging.info("Domain %s created, will check with console", vm_name)
            command = "virsh -c %s console %s" % (uri, vm_name)
        else:
            command = "virsh -c %s create %s %s" % (uri, vmxml.xml, options)

        session = aexpect.ShellSession(command)
        time.sleep(2)
        for i in (tmpfile1, tmpfile2, tmpfile3):
            lsofcmd = "lsof|grep '^sh.*%s'" % i
            cmd_status, cmd_output = session.cmd_status_output(lsofcmd)
            if cmd_status != 0:
                raise error.TestFail("Can not find file %s in container" % i)
            else:
                logging.info("Find open file in guest: %s", cmd_output)

        session.close()
        vm = env.get_vm(vm_name)
        if "--autodestroy" in options:
            if vm.is_alive():
                raise error.TestFail("Guest still exist after close session "
                                     "with option --autodestroy")
            logging.info("Guest already destroyed after session closed")
        elif not vm.is_alive():
            raise error.TestFail("Guest is not running after close session!")
        else:
            logging.info("Guest still exist after session closed")

    finally:
        fd1.close()
        fd2.close()
        fd3.close()
        os.remove(tmpfile1)
        os.remove(tmpfile2)
        os.remove(tmpfile3)
