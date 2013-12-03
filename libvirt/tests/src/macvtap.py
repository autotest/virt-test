import os
import time
from autotest.client.shared import error
from virttest import virsh, remote, utils_net, aexpect
from virttest.libvirt_xml import vm_xml
from virttest.utils_test import ping


def run_macvtap(test, params, env):
    """
    This test is for macvtap nic

    1. Check and backup environment
    2. Configure guest, add new nic and set a static ip address
    3. According to nic mode, start test
    4. Recover environment
    """
    vm_names = params.get("vms").split()
    remote_ip = params.get("remote_ip")
    iface_mode = params.get("mode", "vepa")
    eth_card_no = params.get("eth_card_no")
    vm1_ip = params.get("vm1_ip")
    vm2_ip = params.get("vm2_ip")

    vm1 = env.get_vm(vm_names[0])
    vm2 = None
    if len(vm_names) > 1:
        vm2 = env.get_vm(vm_names[1])
    try:
        iface_cls = utils_net.Interface(eth_card_no)
        origin_status = iface_cls.is_up()
        if not origin_status:
            iface_cls.up()
    except error.CmdError, detail:
        raise error.TestNAError(str(detail))
    br_cls = utils_net.Bridge()
    if eth_card_no in br_cls.list_iface():
        raise error.TestNAError("%s has been used!" % eth_card_no)
    eth_config_file = "/etc/sysconfig/network-scripts/ifcfg-eth1"
    persistent_net_file = "/etc/udev/rules.d/70-persistent-net.rules"
    vmxml1 = vm_xml.VMXML.new_from_inactive_dumpxml(vm_names[0])
    if vm2:
        vmxml2 = vm_xml.VMXML.new_from_inactive_dumpxml(vm_names[1])

    def guest_config(vm, ip_addr):
        """
        Add a new nic to guest and set a static ip address

        :param vm: Configured guest
        :param ip_addr: Set ip address
        """
        # Attach an interface device
        # Use attach-device, not attach-interface, because attach-interface
        # doesn't support 'direct'
        interface_class = vm_xml.VMXML.get_device_class('interface')
        interface = interface_class(type_name="direct")
        interface.source = dict(dev=str(eth_card_no), mode=str(iface_mode))
        interface.model = "virtio"
        interface.xmltreefile.write()
        if vm.is_alive():
            vm.destroy(gracefully=False)
        virsh.attach_device(vm.name, interface.xml, flagstr="--config")
        os.remove(interface.xml)
        vmxml = vm_xml.VMXML.new_from_inactive_dumpxml(vm.name)
        new_nic = vmxml.get_devices(device_type="interface")[-1]

        # Modify new interface's IP
        vm.start()
        session = vm.wait_for_login()
        session.cmd("rm -f %s" % eth_config_file)
        def add_detail(detail):
            """
            Add detail into a desired file
            """
            cmd = "echo %s >> %s" % (detail, eth_config_file)
            session.cmd(cmd)
            time.sleep(1)
        add_detail("DEVICE=eth1")
        add_detail("HWADDR=%s" % new_nic.mac_address)
        add_detail("ONBOOT=yes")
        add_detail("BOOTPROTO=static")
        add_detail("IPADDR=%s" % ip_addr)
        try:
            session.cmd("ifup eth1")
        except aexpect.ShellCmdError:
            pass

    def guest_clean(vm, vmxml):
        """
        Recover guest configuration

        :param: Recovered guest
        """
        if vm.is_dead():
            vm.start()
        session = vm.wait_for_login()
        session.cmd("rm -f %s" % eth_config_file)
        time.sleep(1)
        try:
            # Delete the last 3 lines
            session.cmd('sed -i "$[$(cat %s | wc -l) - 2],$"d %s'
                        % (persistent_net_file, persistent_net_file))
            time.sleep(1)
        except aexpect.ShellCmdError:
            # This file may not exists
            pass
        vm.destroy()
        vmxml.sync()

    def vepa_test(session):
        """
        vepa mode test.
        Check guest can ping remote host
        """
        ping_s, _ = ping(remote_ip, count=1, timeout=5, session=session)
        if ping_s:
            raise error.TestFail("%s ping %s failed." % (vm1.name, remote_ip))

    def private_test(session):
        """
        private mode test.
        Check guest cannot ping other guest, but can pin remote host
        """
        ping_s, _ = ping(remote_ip, count=1, timeout=5, session=session)
        if ping_s:
            raise error.TestFail("%s ping %s failed." % (vm1.name, remote_ip))
        ping_s, _ = ping(vm2_ip, count=1, timeout=5, session=session)
        if not ping_s:
            raise error.TestFail("%s ping %s succeed, but expect failed."
                                 % (vm1.name, vm2.name))
        try:
            iface_cls.down()
        except error.CmdError, detail:
            raise error.TestNAError(str(detail))
        ping_s, _ = ping(vm2_ip, count=1, timeout=5, session=session)
        if not ping_s:
            raise error.TestFail("%s ping %s succeed, but expect failed."
                                 % (vm1.name, remote_ip))

    def passthrough_test(session):
        """
        passthrough mode test.
        Check guest can ping remote host.
        When guest is running, local host cannot ping remote host,
        When guest is poweroff, local host can ping remote host,

        """
        ping_s, _ = ping(remote_ip, count=1, timeout=5, session=session)
        if ping_s:
            raise error.TestFail("%s ping %s failed."
                                 % (vm1.name, remote_ip))
        ping_s, _ = ping(remote_ip, count=1, timeout=5)
        if not ping_s:
            raise error.TestFail("host ping %s succeed, but expect fail."
                                 % remote_ip)
        vm1.destroy(gracefully=False)
        ping_s, _ = ping(remote_ip, count=1, timeout=5)
        if ping_s:
            raise error.TestFail("host ping %s failed."
                                 % remote_ip)

    def bridge_test(session):
        """
        bridge mode test.
        Check guest can ping remote host
        guest can ping other guest when macvtap nic is up
        guest cannot ping remote host when macvtap nic is up
        """
        ping_s, _ = ping(remote_ip, count=1, timeout=5, session=session)
        if ping_s:
            raise error.TestFail("%s ping %s failed."
                                 % (vm1.name, remote_ip))
        ping_s, _ = ping(vm2_ip, count=1, timeout=5, session=session)
        if ping_s:
            raise error.TestFail("%s ping %s failed."
                                 % (vm1.name, vm2.name))
        try:
            iface_cls.down()
        except error.CmdError, detail:
            raise error.TestNAError(str(detail))
        ping_s, _ = ping(remote_ip, count=1, timeout=5, session=session)
        if not ping_s:
            raise error.TestFail("%s ping %s success, but expected fail."
                                 % (vm1.name, remote_ip))
    # Test start

    try:
        try:
            guest_config(vm1, vm1_ip)
        except aexpect.ShellCmdError, fail:
            raise error.TestFail(str(fail))
        if vm1.is_dead():
            vm1.start()
        try:
            session = vm1.wait_for_login()
        except remote.LoginTimeoutError, detail:
            raise error.TestFail(str(detail))
        if vm2:
            try:
                guest_config(vm2, vm2_ip)
            except aexpect.ShellCmdError, fail:
                raise error.TestFail(str(fail))
            if vm2.is_dead():
                vm2.start()
            try:
                # Just make sure it has been completely started.
                # No need to get a session
                vm2.wait_for_login()
            except remote.LoginTimeoutError, detail:
                raise error.TestFail(str(detail))

        # Four mode test
        if iface_mode == "vepa":
            vepa_test(session)
        elif iface_mode == "bridge":
            bridge_test(session)
        elif iface_mode == "private":
            private_test(session)
        elif iface_mode == "passthrough":
            passthrough_test(session)
    finally:
        if iface_cls.is_up():
            if not origin_status:
                iface_cls.down()
        else:
            if origin_status:
                iface_cls.up()
        guest_clean(vm1, vmxml1)
        if vm2:
            guest_clean(vm2, vmxml2)
