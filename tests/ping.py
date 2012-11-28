import logging
from autotest.client.shared import error
from autotest.client import utils
from autotest.client.virt import utils_test


@error.context_aware
def run_ping(test, params, env):
    """
    Ping the guest with different size of packets.

    Packet Loss Test:
    1) Ping the guest with different size/interval of packets.
    2) Ping the external host from guest. (Optional)

    Stress Test:
    1) Flood ping the guest.
    2) Check if the network is still usable.

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    def _get_loss_ratio(output):
        if params.get("strict_check", "no") == "yes":
            ratio = utils_test.get_loss_ratio(output)
            if ratio != 0:
                raise error.TestFail("Loss ratio is %s" % ratio)


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    ping_ext_host = params.get("ping_ext_host", "no") == "yes"
    if ping_ext_host:
        default_host = "www.redhat.com"
        ext_host_get_cmd = params.get("ext_host_get_cmd", "")
        try:
            ext_host = utils.system_output(ext_host_get_cmd)
        except error.CmdError:
            logging.warn("Can't get specified host with cmd '%s',"
                         " Fallback to default host '%s'",
                         ext_host_get_cmd, default_host)
            ext_host = default_host

        if not ext_host:
            # Fallback to a hardcode host, eg:
            ext_host = default_host

    counts = params.get("ping_counts", 100)
    flood_minutes = float(params.get("flood_minutes", 10))

    packet_sizes = [0, 1, 4, 48, 512, 1440, 1500, 1505, 4054, 4055, 4096, 4192,
                    8878, 9000, 32767, 65507]

    try:
        for i, nic in enumerate(vm.virtnet):
            nic_name = nic.get("nic_name")
            ip = vm.get_address(i)
            if not ip:
                logging.error("Could not get the ip of nic index %d: %s",
                              i, nic_name)
                continue

            error.base_context("Ping test on nic %s (index %d) from host"
                               " side" % (nic_name, i), logging.info)
            for size in packet_sizes:
                error.context("Ping with packet size %s" % size, logging.info)
                status, output = utils_test.ping(ip, 10, packetsize=size,
                                                 timeout=20)
                _get_loss_ratio(output)

                if status != 0:
                    raise error.TestFail("Ping failed, status: %s,"
                                         " output: %s" % (status, output))

            error.context("Flood ping test", logging.info)
            utils_test.ping(ip, None, flood=True, output_func=None,
                                timeout=flood_minutes * 60)

            error.context("Final ping test, Check if the network is still"
                          " usable.", logging.info)
            status, output = utils_test.ping(ip, counts,
                                             timeout=float(counts) * 1.5)
            _get_loss_ratio(output)

            if status != 0:
                raise error.TestFail("Ping returns non-zero value %s" %
                                     output)

            if ping_ext_host:
                error.base_context("Ping test from guest side,"
                                   " dest: '%s'" % ext_host, logging.info)
                pkt_sizes = packet_sizes
                # There is no ping program for guest, so let's hardcode...
                cmd = ['ping']
                cmd.append(ext_host) # external host
                if params.get("os_type") == "windows":
                    cmd.append("-n 10")
                    cmd.append("-l %s")
                    # Windows doesn't support ping with packet
                    # larger than '65500'
                    pkt_sizes = [p for p in packet_sizes if p < 65500]
                    # Add a packet size just equal '65500' for windows
                    pkt_sizes.append(65500)
                else:
                    cmd.append("-c 10") # ping 10 times
                    cmd.append("-s %s") # packet size
                cmd = " ".join(cmd)
                for size in pkt_sizes:
                    error.context("Ping with packet size %s" % size,
                                  logging.info)
                    status, output = session.cmd_status_output(cmd % size,
                                                               timeout=20)
                    _get_loss_ratio(output)

                    if status != 0:
                        raise error.TestFail(("Ping external host failed,"
                                             " status: %s, output: %s" %
                                             (status, output)))
    finally:
        session.close()
