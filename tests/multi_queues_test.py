import logging
import re
import os
import time
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_net, data_dir, utils_misc


@error.context_aware
def run_multi_queues_test(test, params, env):
    """
    Enable MULTI_QUEUE feature in guest

    1) Boot up VM(s)
    2) Login guests one by one
    3) Enable MQ for all virtio nics by ethtool -L
    4) Run netperf on guest
    5) check vhost threads on host, if vhost is enable
    6) check cpu affinity if smp == queues

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def run_netperf(vm_session, n_instance, host_ip, client_path, test_time,
                    ext_args, taskset_cpu=[]):
        cmd = ""
        if taskset_cpu:
            cmd += "taskset -c %s " % " ".join(taskset_cpu)
        cmd += "/home/netperf_agent.py %d " % n_instance
        cmd += "%s -D 1 -H %s -l %s %s" % (client_path, host_ip,
                                           int(test_time) * 1.5, ext_args)
        cmd += " > /home/netperf_log &"
        session.cmd(cmd, timeout=120)

    def netperf_env_setup(session, host_path):
        tmp_dir = params.get("tmp_dir")
        agent_path = os.path.join(test.virtdir, "scripts/netperf_agent.py")
        guest_root_path = params.get("tmp_dir", "/home")
        vm.copy_files_to(agent_path, guest_root_path)
        vm.copy_files_to(host_path, guest_root_path, timeout=transfer_timeout)
        error.context("Setup env in linux guest")
        session.cmd("service iptables stop; true")
        session.cmd("iptables -F; true")
        session.cmd(setup_cmd % tmp_dir)

    def get_virtio_queues_irq(session):
        """
        Return multi queues input irq list
        """
        guest_irq_info = session.cmd_output("cat /proc/interrupts")
        return re.findall(r"(\d+):.*virtio\d+-input.\d", guest_irq_info)

    def get_cpu_affinity_hint(session, irq_number):
        """
        Return the cpu affinity_hint of irq_number
        """
        cmd_get_cpu_affinity = r"cat /proc/irq/%s/affinity_hint" % irq_number
        return session.cmd_output(cmd_get_cpu_affinity).strip()

    def get_cpu_index(cpu_id):
        """
        Transfer cpu_id to cpu index
        """
        cpu_used_index = []
        for cpu_index in range(int(vm.cpuinfo.smp)):
            if int(cpu_id) & (0b1 << cpu_index) != 0:
                cpu_used_index.append(cpu_index)
        return cpu_used_index

    def set_cpu_affinity(session):
        """
        Set cpu affinity
        """
        cmd_set_cpu_affinity = r"echo $(cat /proc/irq/%s/affinity_hint)"
        cmd_set_cpu_affinity += " > /proc/irq/%s/smp_affinity"
        irq_list = get_virtio_queues_irq(session)
        for irq in irq_list:
            session.cmd(cmd_set_cpu_affinity % (irq, irq))

    def get_cpu_irq_statistics(session, irq_number, cpu_id=None):
        """
        Get guest interrupts statistics
        """
        cmd = r"cat /proc/interrupts | sed -n '/^\s\+%s:/p'" % irq_number
        irq_statics = session.cmd_output(cmd)
        irq_statics_list = map(int, irq_statics.split()[1:-2])
        if irq_statics_list:
            if cpu_id and cpu_id < len(irq_statics_list):
                return irq_statics_list[cpu_id]
            if not cpu_id:
                return irq_statics_list
        return []

    login_timeout = int(params.get("login_timeout", 360))
    transfer_timeout = int(params.get("transfer_timeout", 360))
    queues = int(params.get("queues", 1))
    setup_cmd = params.get("setup_cmd")
    vms = params.get("vms").split()
    if queues == 1:
        logging.info("No need to enable MQ feature for single queue")
        return
    for vm in vms:
        vm = env.get_vm(vm)
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)
        for i, nic in enumerate(vm.virtnet):
            if "virtio" in nic['nic_model']:
                ifname = utils_net.get_linux_ifname(session,
                                                    vm.get_mac_address(0))
                session.cmd_output("ethtool -L %s combined %d" % (ifname,
                                                                  queues))
                o = session.cmd_output("ethtool -l %s" % ifname)
                if len(re.findall(r"Combined:\s+%d\s" % queues, o)) != 2:
                    raise error.TestError("Fail to enable MQ feature of (%s)"
                                          % nic.nic_name)
                logging.info("MQ feature of (%s) is enabled" % nic.nic_name)

        # Run netperf under ground
        error.context("Set netperf test env on host", logging.info)
        download_dir = data_dir.get_download_dir()
        download_link = params.get("netperf_download_link")
        md5sum = params.get("pkg_md5sum")
        pkg = utils.unmap_url_cache(download_dir, download_link, md5sum)
        utils.system(setup_cmd % download_dir)

        os_type = params.get("os_type")
        if os_type == "linux":
            netperf_env_setup(session, pkg)
        else:
            raise

        error.context("Run netperf server on the host")
        netserver_path = "%s/netperf-2.6.0/src/netserver" % download_dir
        utils.system("pidof netserver || %s" % netserver_path)

        host_ip = utils_net.get_host_ip_address(params)
        n_instance = int(params.get("instance", queues))
        client_path = "%s/netperf-2.6.0/src/netperf" % "/home"

        error.context("Run %s netperf on the guest" % int(queues))
        ext_args = params.get("ext_args", "")
        test_time = params.get("test_time", 60)
        taskset_cpu = params.get("netperf_taskset_cpu", [])
        check_cpu_affinity = params.get("check_cpu_affinity", 'yes')

        if check_cpu_affinity == 'yes' and (vm.cpuinfo.smp == queues):
            utils.system("systemctl stop irqbalance.service")
            set_cpu_affinity(session)

        netperf_thread = utils.InterruptedThread(run_netperf, (session,
                                                               n_instance,
                                                               host_ip,
                                                               client_path,
                                                               test_time,
                                                               ext_args,
                                                               taskset_cpu))

        netperf_thread.start()

        def all_clients_works():
            try:
                content = session.cmd("grep -c MIGRATE /home/netperf_log")
                if int(n_instance) == int(content):
                    return True
            except:
                content = 0
            return False

        if utils_misc.wait_for(all_clients_works, 120, 5, 5,
                               "Wait until all netperf clients start to work"):
            logging.debug("All netperf clients start to work.")
        else:
            raise error.TestNAError("Error, not all netperf clients at work")

        if params.get("vhost") == 'vhost=on':
            error.context("Check vhost threads on host", logging.info)
            vhost_thread_pattern = params.get("vhost_thread_pattern",
                                              r"\w+\s+(\d+)\s.*\[vhost-%s\]")
            vhost_threads = vm.get_vhost_threads(vhost_thread_pattern)
            time.sleep(10)

            top_cmd = r"top -n 1 -p %s -b" % ",".join(map(str, vhost_threads))
            top_info = utils.system_output(top_cmd)
            logging.info("%s", top_info)
            vhost_re = re.compile(r"S(\s+0.0+){2}.*vhost-\d+[\d|+]")
            sleep_vhost_thread = len(vhost_re.findall(top_info, re.I))
            running_threads = len(vhost_threads) - int(sleep_vhost_thread)

            n_instance = min(n_instance, int(queues), int(vm.cpuinfo.smp))
            if (running_threads != n_instance):
                err_msg = "Run %s netperf session, but %s queues works"
                raise error.TestError(err_msg % (n_instance, running_threads))

        # check cpu affinity
        error.context("Check cpu affinity", logging.info)
        if check_cpu_affinity == 'yes' and (vm.cpuinfo.smp == queues):
            vectors = params.get("vectors", None)
            expect_vectors = 2 * int(queues) + 1
            if (not vectors) and (params.get("enable_msix_vectors") == "yes"):
                vectors = expect_vectors
            if vectors and (vectors >= expect_vectors) and taskset_cpu:
                cpu_irq_affinity = {}
                for irq in get_virtio_queues_irq(session):
                    cpu_id = get_cpu_affinity_hint(session, irq)
                    cpu_index = get_cpu_index(cpu_id)
                    if cpu_index:
                        for cpu in cpu_index:
                            cpu_irq_affinity["%s" % cpu] = irq
                    else:
                        raise error.TestError("Can not get the cpu")

                irq_number = cpu_irq_affinity[taskset_cpu]
                irq_ori = get_cpu_irq_statistics(session, irq_number)
                logging.info("Cpu irq info: %s" % irq_ori)
                time.sleep(10)
                irq_cur = get_cpu_irq_statistics(session, irq_number)
                logging.info("After 10s, cpu irq info: %s" % irq_cur)

                irq_change_list = map(lambda x: x[0] - x[1],
                                      zip(irq_cur, irq_ori))
                cpu_affinity = irq_change_list.index(max(irq_change_list))
                if cpu_affinity != int(taskset_cpu):
                    err_msg = "Error, taskset on cpu %s, but queues use cpu %s"
                    raise error.TestError(err_msg % (taskset_cpu,
                                                     cpu_affinity))

        netperf_thread.join()
        session.cmd("rm -rf /home/netperf*")
        session.close()
