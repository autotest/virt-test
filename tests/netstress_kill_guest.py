import logging
import os
import signal
import re
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc, data_dir, utils_net


@error.context_aware
def run(test, params, env):
    """
    Try to kill the guest after/during network stress in guest.
    1) Boot up VM and log VM with serial.
    For driver mode test:
    2) Unload network driver(s).
    3) Load network driver(s) again.
    4) Repeat step 2 and 3 for 50 times.
    5) Check that we can kill VM with signal 0.
    For load mode test:
    2) Stop iptables in guest and host.
    3) Setup run netperf server in host and guest.
    4) Start heavy network load host <=> guest by running netperf
       client in host and guest.
    5) During netperf running, Check that we can kill VM with signal 0.
    6) Clean up netperf server in host and guest.(guest may already killed)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def get_ethernet_driver(session):
        """
        Get driver of network cards.

        :param session: session to machine
        """
        modules = []
        cmd = params.get("nic_module_cmd")
        out = session.cmd(cmd)
        for module in out.split("\n"):
            if not cmd in module:
                modules.append(module.split("/")[-1])
        modules.remove("")
        return set(modules)

    def kill_and_check(vm):
        vm_pid = vm.get_pid()
        vm.destroy(gracefully=False)
        time.sleep(2)
        try:
            os.kill(vm_pid, 0)
            logging.error("VM is not dead")
            raise error.TestFail("VM is not dead after sending signal 0 to it")
        except OSError:
            logging.info("VM is dead as expected")

    def netload_kill_problem(session_serial):
        setup_cmd = params.get("setup_cmd")
        clean_cmd = params.get("clean_cmd")
        firewall_flush = params.get("firewall_flush", "service iptables stop")
        error.context("Stop firewall in guest and host.", logging.info)
        try:
            utils.run(firewall_flush)
        except Exception:
            logging.warning("Could not stop firewall in host")

        try:
            session_serial.cmd(firewall_flush)
        except Exception:
            logging.warning("Could not stop firewall in guest")

        netperf_links = params["netperf_links"].split()
        remote_dir = params.get("remote_dir", "/var/tmp")
        # netperf_links support multi links. In case we need apply patchs to
        # netperf or need copy other files.
        for netperf_link in netperf_links:
            if utils.is_url(netperf_link):
                download_dir = data_dir.get_download_dir()
                netperf_link = utils.unmap_url_cache(download_dir,
                                                     netperf_link)
                netperf_dir = download_dir
            elif netperf_link:
                netperf_link = utils_misc.get_path(data_dir.get_deps_dir(),
                                                   netperf_link)
            vm.copy_files_to(netperf_link, remote_dir)
            utils.force_copy(netperf_link, remote_dir)

        guest_ip = vm.get_address(0)
        server_ip = utils_net.get_correspond_ip(guest_ip)

        error.context("Setup and run netperf server in host and guest",
                      logging.info)
        session_serial.cmd(setup_cmd % remote_dir, timeout=200)
        utils.run(setup_cmd % remote_dir, timeout=200)

        try:
            session_serial.cmd(clean_cmd)
        except Exception:
            pass
        session_serial.cmd(params.get("netserver_cmd") % remote_dir)

        utils.run(clean_cmd, ignore_status=True)
        utils.run(params.get("netserver_cmd") % remote_dir)
        p_size = params.get("packet_size", "1500")
        host_netperf_cmd = params.get("netperf_cmd") % (remote_dir,
                                                        "TCP_STREAM",
                                                        guest_ip,
                                                        p_size)
        guest_netperf_cmd = params.get("netperf_cmd") % (remote_dir,
                                                         "TCP_STREAM",
                                                         server_ip,
                                                         p_size)
        try:
            error.context("Start heavy network load host <=> guest.",
                          logging.info)
            session_serial.sendline(guest_netperf_cmd)
            utils.BgJob(host_netperf_cmd)

            # Wait for create big network usage.
            time.sleep(10)
            msg = "During netperf running, Check that we can kill VM with signal 0"
            error.context(msg, logging.info)
            kill_and_check(vm)

        finally:
            error.context("Clean up netperf server in host and guest.",
                          logging.info)
            utils.run(clean_cmd, ignore_status=True)
            try:
                session_serial.cmd(clean_cmd)
            except Exception:
                pass

    def netdriver_kill_problem(session_serial):
        r_time = int(params.get("repeat_times", 50))
        modules = get_ethernet_driver(session_serial)
        logging.debug("Guest network driver(s): %s" % modules)
        msg = "Repeatedly load/unload network driver(s) for %s times." % r_time
        error.context(msg, logging.info)
        for round in range(r_time):
            for module in modules:
                error.context("Unload driver %s. Repeat: %s/%s" % (module,
                                                                   round,
                                                                   r_time))
                session_serial.cmd_output_safe("rmmod %s" % module)
            for module in modules:
                error.context("Load driver %s. Repeat: %s/%s" % (module,
                                                                 round,
                                                                 r_time))
                session_serial.cmd_output_safe("modprobe %s" % module)

        error.context("Check that we can kill VM with signal 0.", logging.info)
        kill_and_check(vm)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)
    session.close()
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)

    mode = params.get("mode")
    if mode == "driver":
        netdriver_kill_problem(session_serial)
    elif mode == "load":
        netload_kill_problem(session_serial)
