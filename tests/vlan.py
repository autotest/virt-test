import logging, time, re
from autotest.client.shared import error
from virttest import utils_misc, utils_test, aexpect, utils_net


@error.context_aware
def run_vlan(test, params, env):
    """
    Test 802.1Q vlan of NIC, config it by vconfig command.

    1) Create two VMs.
    2) load 8021q module in guest for vconfig.
    3) Setup vlans by vconfig in guest and using hard-coded
       ip address.
    4) Enable arp_ignore for all ipv4 device in guest.
    5) Repeat steps 2 - 4 in every guest.
    6) Test by ping between same and different vlans of two VMs.
    7) Test by flood ping between same vlan of two VMs.
    8) Test by TCP data transfer between same vlan of two VMs.
    9) Remove the named vlan-device.
    10) Test maximal plumb/unplumb vlans.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """


    def add_vlan(session, v_id, iface="eth0"):
        txt = "Create a vlan-device on interface %s with vlan id %s" % (iface,
                                                                        v_id)
        error.context(txt, logging.info)
        session.cmd("vconfig add %s %s" % (iface, v_id))


    def set_ip_vlan(session, v_id, ip, iface="eth0"):
        iface = "%s.%s" % (iface, v_id)
        txt = "Set ip to '%s' for interface '%s'" % (iface, ip)
        error.context(txt, logging.info)
        session.cmd("ifconfig %s %s" % (iface, ip))


    def set_arp_ignore(session, iface="eth0"):
        error.context("Enable arp_ignore for all ipv4 device  in guest",
                       logging.info)
        ignore_cmd = "echo 1 > /proc/sys/net/ipv4/conf/all/arp_ignore"
        session.cmd(ignore_cmd)


    def rem_vlan(session, v_id, iface="eth0"):
        rem_vlan_cmd = "if [[ -e /proc/net/vlan/%s ]];then vconfig rem %s;fi"
        iface = "%s.%s" % (iface, v_id)
        error.context("Remove the named vlan-device '%s'." % iface,
                       logging.info)
        return session.cmd_status(rem_vlan_cmd % (iface, iface))


    def nc_transfer(src, dst):
        nc_port = utils_misc.find_free_port(1025, 5334, vm_ip[dst])
        listen_cmd = params.get("listen_cmd")
        send_cmd = params.get("send_cmd")

        #listen in dst
        listen_cmd = listen_cmd % (nc_port, "receive")
        session[dst].sendline(listen_cmd)
        time.sleep(2)
        #send file from src to dst
        send_cmd = send_cmd % (vlan_ip[dst], str(nc_port), "file")
        session[src].cmd(send_cmd, timeout=60)
        try:
            session[dst].read_up_to_prompt(timeout=60)
        except aexpect.ExpectError:
            raise error.TestFail ("Fail to receive file"
                                    " from vm%s to vm%s" % (src+1, dst+1))
        #check MD5 message digest of receive file in dst
        output = session[dst].cmd_output("md5sum receive").strip()
        digest_receive = re.findall(r'(\w+)', output)[0]
        if digest_receive == digest_origin[src]:
            logging.info("file succeed received in vm %s", vlan_ip[dst])
        else:
            logging.info("digest_origin is  %s", digest_origin[src])
            logging.info("digest_receive is %s", digest_receive)
            raise error.TestFail("File transfered differ from origin")
        session[dst].cmd_output("rm -f receive")


    def flood_ping(src, dst):
        # we must use a dedicated session becuase the aexpect
        # does not have the other method to interrupt the process in
        # the guest rather than close the session.
        error.context("Flood ping from %s interface %s to %s" % (vm[src].name,
                      ifname[src], vlan_ip[dst]), logging.info)
        session_flood = vm[src].wait_for_login(timeout=60)
        utils_test.ping(vlan_ip[dst], flood=True,
                          interface=ifname[src],
                          session=session_flood, timeout=10)
        session_flood.close()


    vm = []
    session = []
    ifname = []
    vm_ip = []
    digest_origin = []
    vlan_ip = ['', '']
    ip_unit = ['1', '2']
    subnet = params.get("subnet")
    vlan_num = int(params.get("vlan_num"))
    maximal = int(params.get("maximal"))
    file_size = params.get("file_size")

    vm.append(env.get_vm(params["main_vm"]))
    vm.append(env.get_vm("vm2"))
    for vm_ in vm:
        vm_.verify_alive()

    for i in range(2):
        session.append(vm[i].wait_for_login(
            timeout=int(params.get("login_timeout", 360))))
        if not session[i] :
            raise error.TestError("Could not log into guest(vm%d)" % i)
        logging.info("Logged in")

        ifname.append(utils_net.get_linux_ifname(session[i],
                      vm[i].get_mac_address()))
        #get guest ip
        vm_ip.append(vm[i].get_address())

        #produce sized file in vm
        dd_cmd = "dd if=/dev/urandom of=file bs=1024k count=%s"
        session[i].cmd(dd_cmd % file_size)
        #record MD5 message digest of file
        output = session[i].cmd("md5sum file", timeout=60)
        digest_origin.append(re.findall(r'(\w+)', output)[0])

        #stop firewall in vm
        session[i].cmd_output("/etc/init.d/iptables stop")

        error.context("load 8021q module in guest for vconfig", logging.info)
        session[i].cmd("modprobe 8021q")

    try:
        for i in range(2):
            logging.info("Setup vlan environment in guest %s" % vm[i].name)
            for vlan_i in range(1, vlan_num+1):
                add_vlan(session[i], vlan_i, ifname[i])
                set_ip_vlan(session[i], vlan_i, "%s.%s.%s" %
                            (subnet, vlan_i, ip_unit[i]), ifname[i])
            set_arp_ignore(session[i], ifname[i])

        for vlan in range(1, vlan_num+1):
            logging.info("Test for vlan %s", vlan)

            error.context("Ping test between vlans", logging.info)
            interface = ifname[0] + '.' + str(vlan)
            for vlan2 in range(1, vlan_num+1):
                for i in range(2):
                    interface = ifname[i] + '.' + str(vlan)
                    dest = subnet +'.'+ str(vlan2)+ '.' + ip_unit[(i+1)%2]
                    s, o = utils_test.ping(dest, count=2,
                                              interface=interface,
                                              session=session[i], timeout=30)
                    if ((vlan == vlan2) ^ (s == 0)):
                        raise error.TestFail ("%s ping %s unexpected" %
                                                    (interface, dest))

            vlan_ip[0] = subnet + '.' + str(vlan) + '.' + ip_unit[0]
            vlan_ip[1] = subnet + '.' + str(vlan) + '.' + ip_unit[1]

            flood_ping(0, 1)
            flood_ping(1, 0)

            error.context("Transfering data through nc", logging.info)
            nc_transfer(0, 1)
            nc_transfer(1, 0)

    finally:
        for vlan in range(1, vlan_num+1):
            logging.info("rem vlan: %s", vlan)
            rem_vlan(session[0], vlan, ifname[0])
            rem_vlan(session[1], vlan, ifname[1])

    # Plumb/unplumb maximal number of vlan interfaces
    i = 1
    s = 0
    try:
        error.context("Testing the plumb of vlan interface", logging.info)
        for i in range (1, maximal+1):
            add_vlan(session[0], i, ifname[0])
    finally:
        for j in range (1, i+1):
            s = s or rem_vlan(session[0], j, ifname[0])
        if s == 0:
            logging.info("maximal interface plumb test done")
        else:
            logging.error("maximal interface plumb test failed")

    session[0].close()
    session[1].close()
