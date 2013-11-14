import logging
import re
from autotest.client.shared import error
from virttest import utils_net, utils_test, utils_misc


@error.context_aware
def run(test, params, env):
    """
    Test Step:
        1. Boot up two virtual machine
        2. Set openflow rules
        3. Run ping test, nc(tcp, udp) test, check whether openflow rules take
           effect.
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """
    def run_tcpdump_bg(session, addresses, dump_protocol):
        """
        Run tcpdump in background, tcpdump will exit once catch a packet
        match the rules.
        """
        tcpdump_cmd = "killall -9 tcpdump; "
        tcpdump_cmd += "tcpdump -iany -n -v %s and 'src %s and dst %s' -c 1 &"
        session.cmd_output_safe(tcpdump_cmd % (dump_protocol,
                                               addresses[0], addresses[1]))
        if not utils_misc.wait_for(lambda: tcpdump_is_alive(session),
                                   30, 0, 1, "Waiting tcpdump start..."):
            raise error.TestNAError("Error, can not run tcpdump")

    def dump_catch_data(session, dump_log, catch_reg):
        """
        Search data from dump_log
        """
        dump_info = session.cmd_output("cat %s" % dump_log)
        if re.findall(catch_reg, dump_info, re.I):
            return True
        return False

    def tcpdump_is_alive(session):
        """
        Check whether tcpdump is alive
        """
        if session.cmd_status("pidof tcpdump"):
            return False
        return True

    def tcpdump_catch_packet_test(session, drop_flow=False):
        """
        Check whether tcpdump catch match rules packets, once catch a packet
        match rules tcpdump will exit.
        when drop_flow is 'True', tcpdump couldn't catch any packets.
        """
        packet_receive = not tcpdump_is_alive(session)
        if packet_receive == drop_flow:
            err_msg = "Error, flow %s dropped, tcpdump %s receive the packets"
            raise error.TestError(err_msg % ((drop_flow and "was" or "wasn't"),
                                  (packet_receive and "can" or "can not")))
        logging.info("Correct, flow %s dropped, tcpdump %s receive the packet"
                     % ((drop_flow and "was" or "was not"),
                         (packet_receive and "can" or "can not")))

    def arp_entry_clean(session, entry=None):
        """
        Clean arp catch in guest
        """
        if not entry:
            arp_clean_cmd = "arp -n | awk '/^[1-2]/{print \"arp -d \" $1}'|sh"
        else:
            arp_clean_cmd = "arp -d %s" % entry
        for session in sessions:
            session.cmd_output_safe(arp_clean_cmd)

    def ping_test(session, dst, drop_flow=False):
        """
        Ping test, check icmp
        """
        ping_status, ping_output = utils_test.ping(dest=dst, count=10,
                                                   timeout=20, session=session)
        # when drop_flow is true, ping should failed(return not zero)
        # drop_flow is false, ping should success
        packets_lost = 100
        if ping_status and not drop_flow:
            raise error.TestError("Ping should success when not drop_icmp")
        elif not ping_status:
            packets_lost = utils_test.get_loss_ratio(ping_output)
            if drop_flow and packets_lost != 100:
                raise error.TestError("When drop_icmp, ping shouldn't works")
            if not drop_flow and packets_lost == 100:
                raise error.TestError("When not drop_icmp, ping should works")

        info_msg = "Correct, icmp flow %s dropped, ping '%s', "
        info_msg += "packets lost rate is: '%s'"
        logging.info(info_msg % ((drop_flow and "was" or "was not"),
                                 (ping_status and "failed" or "success"),
                                 packets_lost))

    def nc_connect_test(sessions, addresses, drop_flow=False, nc_port="8899",
                        udp_model=False):
        """
        Nc connect test, check tcp and udp
        """
        nc_log = "/tmp/nc_log"
        server_cmd = "nc -l %s"
        client_cmd = "echo client | nc %s %s"
        if udp_model == True:
            server_cmd += " -u -w 3"
            client_cmd += " -u -w 3"
        server_cmd += " > %s &"
        client_cmd += " &"
        try:
            sessions[1].cmd_output_safe(server_cmd % (nc_port, nc_log))
            sessions[0].cmd_output_safe(client_cmd % (addresses[1], nc_port))

            nc_protocol = udp_model and "UDP" or "TCP"
            nc_connect = False
            if utils_misc.wait_for(
                    lambda: dump_catch_data(sessions[1], nc_log, "client"),
                    10, 0, 2, text="Wait '%s' connect" % nc_protocol):
                nc_connect = True
            if nc_connect == drop_flow:
                err_msg = "Error, '%s' flow %s dropped, nc connect should '%s'"
                raise error.TestError(err_msg % (nc_protocol,
                                      (drop_flow and "was" or "was not"),
                                      (nc_connect and "failed" or "success")))

            logging.info("Correct, '%s' flow %s dropped, and nc connect %s" %
                        (nc_protocol, (drop_flow and "was" or "was not"),
                         (nc_connect and "success" or "failed")))
        finally:
            for session in sessions:
                session.cmd_output_safe("killall nc || killall ncat")
                session.cmd("%s %s" % (clean_cmd, nc_log),
                            ignore_all_errors=True)

    timeout = int(params.get("login_timeout", '360'))
    clean_cmd = params.get("clean_cmd", "rm -f")
    sessions = []
    addresses = []
    vms = []

    error.context("Init boot the vms")
    for vm_name in params.get("vms", "vm1 vm2").split():
        vms.append(env.get_vm(vm_name))
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())

    # set openflow rules:
    br_name = params.get("netdst", "ovs0")
    f_protocol = params.get("flow", "arp")
    f_base_options = "%s,nw_src=%s,nw_dst=%s" % (f_protocol, addresses[0],
                                                 addresses[1])
    for session in sessions:
        session.cmd("service iptables stop; iptables -F",
                    ignore_all_errors=True)
    try:
        for drop_flow in [True, False]:
            if drop_flow:
                f_command = "add-flow"
                f_options = f_base_options + ",action=drop"
                drop_icmp = eval(params.get("drop_icmp", 'True'))
                drop_tcp = eval(params.get("drop_tcp", 'True'))
                drop_udp = eval(params.get("drop_udp", 'True'))
            else:
                f_command = "mod-flows"
                f_options = f_base_options + ",action=normal"
                drop_icmp = False
                drop_tcp = False
                drop_udp = False

            error.base_context("Test prepare")
            error.context("Do %s %s on %s" % (f_command, f_options, br_name))
            utils_net.openflow_manager(br_name, f_command, f_options)

            error.context("Run tcpdump in guest %s" % vms[1].name, logging.info)
            run_tcpdump_bg(sessions[1], addresses, f_protocol)

            error.context("Clean arp cache in both guest", logging.info)
            arp_entry_clean(sessions[0], addresses[1])

            error.base_context("Exec '%s' flow '%s' test" %
                               (f_protocol, drop_flow and "drop" or "normal"))
            error.context("Ping test form vm1 to vm2", logging.info)
            ping_test(sessions[0], addresses[1], drop_icmp)

            error.context("Run nc connect test via tcp", logging.info)
            nc_connect_test(sessions, addresses, drop_tcp)

            error.context("Run nc connect test via udp", logging.info)
            nc_connect_test(sessions, addresses, drop_udp, udp_model=True)

            error.context("Check tcpdump data catch", logging.info)
            tcpdump_catch_packet_test(sessions[1], drop_flow)

    finally:
        utils_net.openflow_manager(br_name, "del-flows", f_protocol)
        for session in sessions:
            session.close()
