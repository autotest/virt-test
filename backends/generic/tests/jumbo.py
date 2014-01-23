import logging
import commands
import random
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, utils_test, utils_net


@error.context_aware
def run(test, params, env):
    """
    Test the RX jumbo frame function of vnics:

    1) Boot the VM.
    2) Change the MTU of guest nics and host taps depending on the NIC model.
    3) Add the static ARP entry for guest NIC.
    4) Wait for the MTU ok.
    5) Verify the path MTU using ping.
    6) Ping the guest with large frames.
    7) Increment size ping.
    8) Flood ping the guest with large frames.
    9) Verify the path MTU.
    10) Recover the MTU.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    timeout = int(params.get("login_timeout", 360))
    mtu = params.get("mtu", "1500")
    def_max_icmp_size = int(mtu) - 28
    max_icmp_pkt_size = int(params.get("max_icmp_pkt_size",
                                       def_max_icmp_size))
    flood_time = params.get("flood_time", "300")
    os_type = params.get("os_type")
    os_variant = params.get("os_variant")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    session_serial = vm.wait_for_serial_login(timeout=timeout)

    ifname = vm.get_ifname(0)
    guest_ip = vm.get_address(0)
    if guest_ip is None:
        raise error.TestError("Could not get the guest ip address")

    try:
        error.context("Changing the MTU of guest", logging.info)
        # Environment preparation
        mac = vm.get_mac_address(0)
        if os_type == "linux":
            ethname = utils_net.get_linux_ifname(session, mac)
            guest_mtu_cmd = "ifconfig %s mtu %s" % (ethname, mtu)
        else:
            connection_id = utils_net.get_windows_nic_attribute(session,
                    "macaddress", mac, "netconnectionid")

            index = utils_net.get_windows_nic_attribute(session,
                    "netconnectionid", connection_id, "index")
            if os_variant == "winxp":
                pnpdevice_id = utils_net.get_windows_nic_attribute(session,
                        "netconnectionid", connection_id, "pnpdeviceid")
                cd_num = utils_misc.get_winutils_vol(session)
                copy_cmd = r"xcopy %s:\devcon\wxp_x86\devcon.exe c:\ " % cd_num
                session.cmd(copy_cmd)

            reg_set_mtu_pattern = params.get("reg_mtu_cmd")
            mtu_key_word = params.get("mtu_key", "MTU")
            reg_set_mtu = reg_set_mtu_pattern % (int(index), mtu_key_word,
                                                 int(mtu))
            guest_mtu_cmd = "%s " % reg_set_mtu

        session.cmd(guest_mtu_cmd)
        if os_type == "windows":
            mode = "netsh"
            if os_variant == "winxp":
                connection_id = pnpdevice_id.split("&")[-1]
                mode = "devcon"
            utils_net.restart_windows_guest_network(session_serial,
                                                    connection_id,
                                                    mode=mode)

        error.context("Chaning the MTU of host tap ...", logging.info)
        host_mtu_cmd = "ifconfig %s mtu %s"
        #Before change macvtap mtu, must set the base interface mtu
        if params.get("nettype") == "macvtap":
            base_if = utils_net.get_macvtap_base_iface(params.get("netdst"))
            utils.run(host_mtu_cmd % (base_if, mtu))
        utils.run(host_mtu_cmd % (ifname, mtu))

        error.context("Add a temporary static ARP entry ...", logging.info)
        arp_add_cmd = "arp -s %s %s -i %s" % (guest_ip, mac, ifname)
        utils.run(arp_add_cmd)

        def is_mtu_ok():
            status, _ = utils_test.ping(guest_ip, 1, interface=ifname,
                                        packetsize=max_icmp_pkt_size,
                                        hint="do", timeout=2)
            return status == 0

        def verify_mtu():
            logging.info("Verify the path MTU")
            status, output = utils_test.ping(guest_ip, 10, interface=ifname,
                                             packetsize=max_icmp_pkt_size,
                                             hint="do", timeout=15)
            if status != 0:
                logging.error(output)
                raise error.TestFail("Path MTU is not as expected")
            if utils_test.get_loss_ratio(output) != 0:
                logging.error(output)
                raise error.TestFail("Packet loss ratio during MTU "
                                     "verification is not zero")

        def flood_ping():
            logging.info("Flood with large frames")
            utils_test.ping(guest_ip, interface=ifname,
                            packetsize=max_icmp_pkt_size,
                            flood=True, timeout=float(flood_time))

        def large_frame_ping(count=100):
            logging.info("Large frame ping")
            _, output = utils_test.ping(guest_ip, count, interface=ifname,
                                   packetsize=max_icmp_pkt_size,
                                   timeout=float(count) * 2)
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                raise error.TestFail("Loss ratio of large frame ping is %s" %
                                     ratio)

        def size_increase_ping(step=random.randrange(90, 110)):
            logging.info("Size increase ping")
            for size in range(0, max_icmp_pkt_size + 1, step):
                logging.info("Ping %s with size %s", guest_ip, size)
                status, output = utils_test.ping(guest_ip, 1, interface=ifname,
                                                 packetsize=size,
                                                 hint="do", timeout=1)
                if status != 0:
                    status, output = utils_test.ping(guest_ip, 10,
                                                     interface=ifname,
                                                     packetsize=size,
                                                     adaptive=True,
                                                     hint="do",
                                                     timeout=20)

                    fail_ratio = int(params.get("fail_ratio", 50))
                    if utils_test.get_loss_ratio(output) > fail_ratio:
                        raise error.TestFail("Ping loss ratio is greater "
                                             "than 50% for size %s" % size)

        logging.info("Waiting for the MTU to be OK")
        wait_mtu_ok = 10
        if not utils_misc.wait_for(is_mtu_ok, wait_mtu_ok, 0, 1):
            logging.debug(commands.getoutput("ifconfig -a"))
            raise error.TestError("MTU is not as expected even after %s "
                                  "seconds" % wait_mtu_ok)

        # Functional Test
        error.context("Checking whether MTU change is ok", logging.info)
        verify_mtu()
        large_frame_ping()
        size_increase_ping()

        # Stress test
        flood_ping()
        verify_mtu()

    finally:
        # Environment clean
        if session:
            session.close()
        if utils.system("grep '%s.*%s' /proc/net/arp" % (guest_ip, ifname)) == '0':
            utils.run("arp -d %s -i %s" % (guest_ip, ifname))
            logging.info("Removing the temporary ARP entry successfully")
