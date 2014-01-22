import logging
import time
import re
from autotest.client.shared import error
from virttest import utils_misc, utils_test, aexpect, utils_net


@error.context_aware
def run(test, params, env):
    """
    Test 802.1Q vlan of NIC, config it by vconfig/ip command.

    1) Create two VMs.
    2) load 8021q module in guest.
    3) Setup vlans by vconfig/ip in guest and using hard-coded ip address.
    4) Enable arp_ignore for all ipv4 device in guest.
    5) Repeat steps 2 - 4 in every guest.
    6) Test by ping between same and different vlans of two VMs.
    7) Test by flood ping between same vlan of two VMs.
    8) Test by TCP data transfer between same vlan of two VMs.
    9) Remove the named vlan-device.
    10) Test maximal plumb/unplumb vlans.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def add_vlan(session, v_id, iface="eth0", cmd_type="ip"):
        """
        Creates a vlan-device on iface by cmd that assigned by cmd_type
        now only support 'ip' and 'vconfig'
        """
        vlan_if = '%s.%s' % (iface, v_id)
        txt = "Create vlan interface '%s' on %s" % (vlan_if, iface)
        error.context(txt, logging.info)
        if cmd_type == "vconfig":
            cmd = "vconfig add %s %s" % (iface, v_id)
        elif cmd_type == "ip":
            v_name = "%s.%s" % (iface, v_id)
            cmd = "ip link add link %s %s type vlan id %s " % (iface,
                                                               v_name, v_id)
        else:
            err_msg = "Unexpected vlan operation command: %s, " % cmd_type
            err_msg += "only support 'ip' and 'vconfig' now"
            raise error.TestError(err_msg)
        session.cmd(cmd)

    def set_ip_vlan(session, v_id, vlan_ip, iface="eth0"):
        """
        Set ip address of vlan interface
        """
        iface = "%s.%s" % (iface, v_id)
        txt = "Assign IP '%s' to vlan interface '%s'" % (vlan_ip, iface)
        error.context(txt, logging.info)
        session.cmd("ifconfig %s %s" % (iface, vlan_ip))

    def set_arp_ignore(session):
        """
        Enable arp_ignore for all ipv4 device in guest
        """
        error.context("Enable arp_ignore for all ipv4 device in guest",
                      logging.info)
        ignore_cmd = "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore"
        session.cmd(ignore_cmd)

    def rem_vlan(session, v_id, iface="eth0", cmd_type="ip"):
        """
        Removes the named vlan interface(iface+v_id)
        """
        v_iface = '%s.%s' % (iface, v_id)
        if cmd_type == "vconfig":
            rem_vlan_cmd = "vconfig rem %s" % v_iface
        elif cmd_type == "ip":
            rem_vlan_cmd = "ip link delete %s" % v_iface
        else:
            err_msg = "Unexpected vlan operation command: %s, " % cmd_type
            err_msg += "only support 'ip' and 'vconfig' now"
            raise error.TestError(err_msg)

        send_cmd = "[ -e /proc/net/vlan/%s ] && %s" % (v_iface, rem_vlan_cmd)
        error.context("Remove vlan interface '%s'." % v_iface, logging.info)
        return session.cmd_status(send_cmd)

    def nc_transfer(src, dst):
        """
        Transfer file by netcat
        """
        nc_port = utils_misc.find_free_port(1025, 5334, vm_ip[dst])
        listen_cmd = params.get("listen_cmd")
        send_cmd = params.get("send_cmd")

        #listen in dst
        listen_cmd = listen_cmd % (nc_port, "receive")
        sessions[dst].sendline(listen_cmd)
        time.sleep(2)
        # send file from src to dst
        send_cmd = send_cmd % (vlan_ip[dst], str(nc_port), "file")
        sessions[src].cmd(send_cmd, timeout=60)
        try:
            sessions[dst].read_up_to_prompt(timeout=60)
        except aexpect.ExpectError:
            #kill server
            session_ctl[dst].cmd_output_safe("killall -9 nc")
            raise error.TestFail("Fail to receive file"
                                 " from vm%s to vm%s" % (src + 1, dst + 1))
        # check MD5 message digest of receive file in dst
        output = sessions[dst].cmd_output("md5sum receive").strip()
        digest_receive = re.findall(r'(\w+)', output)[0]
        if digest_receive == digest_origin[src]:
            logging.info("File succeed received in vm %s", vlan_ip[dst])
        else:
            logging.info("Digest_origin is  %s", digest_origin[src])
            logging.info("Digest_receive is %s", digest_receive)
            raise error.TestFail("File transferred differ from origin")
        sessions[dst].cmd("rm -f receive")

    def flood_ping(src, dst):
        """
        Flood ping test
        # we must use a dedicated session because the aexpect
        # does not have the other method to interrupt the process in
        # the guest rather than close the session.
        """
        error.context("Flood ping from %s interface %s to %s" % (vms[src].name,
                      ifname[src], vlan_ip[dst]), logging.info)
        session_flood = vms[src].wait_for_login(timeout=60)
        utils_test.ping(vlan_ip[dst], flood=True,
                        interface=ifname[src],
                        session=session_flood, timeout=10)
        session_flood.close()

    vms = []
    sessions = []
    session_ctl = []
    ifname = []
    vm_ip = []
    digest_origin = []
    vlan_ip = ['', '']
    ip_unit = ['1', '2']
    subnet = params.get("subnet", "192.168")
    vlan_num = int(params.get("vlan_num", 5))
    maximal = int(params.get("maximal", 4094))
    file_size = params.get("file_size", 4096)
    cmd_type = params.get("cmd_type", "ip")
    login_timeout = int(params.get("login_timeout", 360))

    vms.append(env.get_vm(params["main_vm"]))
    vms.append(env.get_vm("vm2"))
    for vm_ in vms:
        vm_.verify_alive()

    for vm_index, vm in enumerate(vms):
        error.base_context("Prepare test env on %s" % vm.name)
        session = vm.wait_for_login(timeout=login_timeout)
        if not session:
            err_msg = "Could not log into guest %s" % vm.name
            raise error.TestError(err_msg)
        sessions.append(session)
        logging.info("Logged in %s successful" % vm.name)
        session_ctl.append(vm.wait_for_login(timeout=login_timeout))
        ifname.append(utils_net.get_linux_ifname(session,
                                                 vm.get_mac_address()))
        # get guest ip
        vm_ip.append(vm.get_address())
        # produce sized file in vm
        dd_cmd = "dd if=/dev/urandom of=file bs=1M count=%s"
        session.cmd(dd_cmd % file_size)
        # record MD5 message digest of file
        md5sum_output = session.cmd("md5sum file", timeout=60)
        digest_origin.append(re.findall(r'(\w+)', md5sum_output)[0])

        # stop firewall in vm
        session.cmd_output_safe("service iptables stop; iptables -F; true")
        error.context("Load 8021q module in guest %s" % vm.name,
                      logging.info)
        session.cmd_output_safe("modprobe 8021q")

        error.context("Setup vlan environment in guest %s" % vm.name,
                      logging.info)
        for vlan_i in range(1, vlan_num + 1):
            add_vlan(session, vlan_i, ifname[vm_index], cmd_type)
            v_ip = "%s.%s.%s" % (subnet, vlan_i, ip_unit[vm_index])
            set_ip_vlan(session, vlan_i, v_ip, ifname[vm_index])
        set_arp_ignore(session)

    try:
        for vlan in range(1, vlan_num + 1):
            error.base_context("Test for vlan %s" % vlan, logging.info)
            error.context("Ping test between vlans", logging.info)
            interface = ifname[0] + '.' + str(vlan)
            for vm_index, vm in enumerate(vms):
                for vlan2 in range(1, vlan_num + 1):
                    interface = ifname[vm_index] + '.' + str(vlan)
                    dest = ".".join((subnet, str(vlan2),
                                     ip_unit[(vm_index + 1) % 2]))
                    status, output = utils_test.ping(dest, count=2,
                            interface=interface, session=sessions[vm_index],
                            timeout=30)
                    if ((vlan == vlan2) ^ (status == 0)):
                        err_msg = "%s ping %s unexpected, " % (interface, dest)
                        err_msg += "error info: %s" % output
                        raise error.TestFail(err_msg)

            error.context("Flood ping between vlans", logging.info)
            vlan_ip[0] = ".".join((subnet, str(vlan), ip_unit[0]))
            vlan_ip[1] = ".".join((subnet, str(vlan), ip_unit[1]))
            flood_ping(0, 1)
            flood_ping(1, 0)

            error.context("Transferring data between vlans by nc",
                          logging.info)
            nc_transfer(0, 1)
            nc_transfer(1, 0)

    finally:
        #If client can not connect the nc server, need kill the server.
        for session in session_ctl:
            session.cmd_output_safe("killall -9 nc")
        error.base_context("Remove vlan")
        for vm_index, vm in enumerate(vms):
            for vlan in range(1, vlan_num + 1):
                rem_vlan(sessions[vm_index], vlan, ifname[vm_index], cmd_type)

    # Plumb/unplumb maximal number of vlan interfaces
    if params.get("do_maximal_test", "no") == "yes":
        try:
            error.base_context("Vlan scalability test")
            error.context("Testing the plumb of vlan interface", logging.info)
            for vlan_index in range(1, maximal + 1):
                add_vlan(sessions[0], vlan_index, ifname[0], cmd_type)
                vlan_added = vlan_index
            if vlan_added != maximal:
                raise error.TestFail("Maximal interface plumb test failed")
        finally:
            for vlan_index in range(1, vlan_added + 1):
                if not rem_vlan(sessions[0], vlan_index, ifname[0], cmd_type):
                    logging.error("Remove vlan %s failed" % vlan_index)

    sessions.extend(session_ctl)
    for sess in sessions:
        if sess:
            sess.close()
