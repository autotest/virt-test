import re
import time
import logging
from autotest.client.shared import error, utils
from virttest import utils_test, utils_net


@error.context_aware
def get_first_network_devname(session, nic_interface_filter):
    """
    Get first active network interface in guest.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param nic_interface_filter: Regular Expressions used to filter network
                                 interface.
    :type nic_interface_filter: Regular Expressions string
    :return: First active network interface name in guest.
    :rtype: String
    """
    cmd = "ifconfig -a"
    status, output = session.cmd_status_output(cmd)
    if status:
        msg = "Guest command '%s' fail with output: %s." % (cmd, output)
        raise error.TestError(msg)
    devnames = re.findall(nic_interface_filter, output, re.S)
    if not devnames:
        msg = "Fail to get network interface name in guest."
        msg += "ifconfig output in guest: %s" % output
        raise error.TestError(msg)
    return devnames[0]


@error.context_aware
def get_guest_service_status(session, service):
    """
    Get service's status in guest. It will return 'active' for 'running' and
    'active'. Return 'inactive' for 'stopped' and 'inactive'.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param service: Service name that we want to check status.
    :type service: String
    :return: service's status in guest.  'active' or 'inactive'
    :rtype: String
    """
    cmd = "service %s status" % service
    output = session.cmd_output(cmd)
    service_status_filter = "running|active"
    if re.search("running|active", output, re.I):
        status = "active"
    elif re.search("stopped|inactive", output, re.I):
        status = "inactive"
    else:
        msg = "Fail to get '%s' service status. " % service
        msg += " Command output in guest: %s" % output
        raise error.TestError(msg)
    return status


@error.context_aware
def get_irq_smp_affinity(session, irq):
    """
    Get irq's affinity cpu in guest.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param irq: irq we want to check in guest.
    :type irq: String
    :return: Cpu list the irq affinity to.
    :rtype: List
    """
    cmd = "cat /proc/irq/%s/smp_affinity" % irq
    status, output = session.cmd_status_output(cmd)
    if status:
        msg = "Fail to get affinity cpu for IRQ '%s'" % irq
        raise error.TestError(msg)
    cpus = []
    bit_list = list(bin(int(output.strip(), 16)))
    bit_list.reverse()
    while "1" in bit_list:
        index = bit_list.index("1")
        bit_list[index] = "0"
        cpus.append(index)
    if cpus:
        msg = "IRQ '%s' has affinity cpu %s" % (irq, cpus)
        logging.info(msg)
        return cpus


@error.context_aware
def set_irq_smp_affinity(session, irq, cpus):
    """
    Set irq's affinity cpu in guest.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param irq: irq we want to check in guest.
    :type irq: String
    :param cpus: Cpu list that we want to set irq's affinity.
    :type cpus: List
    """
    num = 0
    for cpu in cpus:
        num += 2 ** cpu
    if num == 0:
        raise error.TestError("Please set available cpus")
    cmd = "echo %s > /proc/irq/%s/smp_affinity" % (num, irq)
    status = session.cmd_status(cmd)
    if status:
        msg = "Fail to set affinity cpu to %s for IRQ '%s'" % (cpus, irq)
        raise error.TestFail(msg)


@error.context_aware
def get_guest_irq_info(session, devname, cpu_count):
    """
    Get irq balance information by reading /proc/interrupts in guest.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param devname:  Network interface name in guest.
    :type devname: String
    :param cpu_count: Guest's cpu number.
    :type cpu_count: int
    :return: irq_num_dict, It contains how many irq handled by every cpu
             for specified network interface in guest.
    :rtype: dict

    """
    irq_num_dict = {}
    cmd = "cat /proc/interrupts | grep %s-" % devname
    status, output = session.cmd_status_output(cmd)
    if status:
        msg = "Command '%s' fail in guest with output:%s" % (cmd, output)
        raise error.TestError(msg)
    irq_info_filter = "([0-9]*):" + "\s*([0-9]*)" * cpu_count
    irq_infos = re.findall(irq_info_filter, output)
    if not irq_infos:
        msg = "Fail to get irq information for device %s. " % devname
        msg += "Command output: %s" % output
        raise error.TestError(msg)
    for irq_info in irq_infos:
        irq_info = list(irq_info)
        irq = irq_info.pop(0)
        irq_num_dict[irq] = irq_info
    return irq_num_dict


@error.context_aware
def check_irqbalance(session, devname, cpu_count, irqs, count=6,
                     interval=10):
    """
    Check that whether irqbalance works. Make sure specified irqs is handled in
    specified cpu. Raise error.TestFail if specified irqs count is not grow in
    specified cpu.

    :param session: An Expect or ShellSession instance to operate on
    :type devices: Expect or ShellSession class
    :param devname:  Network interface name in guest.
    :type devname: String
    :param cpu_count: Guest's cpu number.
    :type cpu_count: int
    :param irqs: IRQ list
    :type irqs: list
    :param count: Times we want to repeat check.
    :type count: int
    :param interval: Time interval.
    """
    irq_cpus_dict = {}
    for irq in irqs:
        cpus = get_irq_smp_affinity(session, irq)
        irq_cpus_dict[irq] = cpus

    pre_irq_num_dict = get_guest_irq_info(session, devname, cpu_count)
    num = 0
    while num < count:
        time.sleep(interval)
        irq_num_dict = get_guest_irq_info(session, devname, cpu_count)
        for irq in irqs:
            for cpu in irq_cpus_dict[irq]:
                if (int(pre_irq_num_dict[irq][cpu]) >=
                   int(irq_num_dict[irq][cpu])):
                    msg = "'Cpu%s' did not handle more interrupt" % cpu
                    msg += "for irq '%s'." % irq
                    msg += "IRQ balance information for IRQ '%s'\n" % irq
                    msg += "%s second ago: %s\n" % (interval,
                                                    pre_irq_num_dict[irq])
                    msg += "Just now: %s" % irq_num_dict[irq]
                    raise error.TestFail(msg)
        num += 1
        pre_irq_num_dict = irq_num_dict


@error.context_aware
def run_sr_iov_irqbalance(test, params, env):
    """
    Qemu guest irqbalance inactive/active test:
    1) Setup host for sr-iov test.
    2) Boot VM with sr-iov vf/pf assigned and multi vcpu.
    3) Update irqbalance service status in guest. stop/start this server
       according to request.
    4) Get available network interface name in guest.
    5) Start background network stress in guest.
    6) Get irq number assigned to attached vfs/pfs.
    7) Get the cpu number the irq running.
    8) Check specified IRQ count grow on specified cpu.
    9) Repeat step 7 for every 10s.
    10) Balance IRQs generated by vfs/pfs to different vcpus (optional)
       e.g.
       echo 4 > /proc/irq/num/smp_affinity
    11) Repeat step 6, 7
    12) Check that specified IRQ count grow on every cpu. (optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    irqbalance_check_count = int(params.get("irqbalance_check_count", 36))
    nic_interface_filter = params["nic_interface_filter"]

    error.context("Make sure that guest have at least 2 vCPUs.", logging.info)
    cpu_count = vm.get_cpu_count()
    if cpu_count < 2:
        raise error.TestNAError("Test requires at least 2 vCPUs.")

    msg = "Update irqbalance service status in guest if not match request."
    error.context(msg, logging.info)
    irqbalance_status = params.get("irqbalance_status", "active")
    status = get_guest_service_status(session=session, service="irqbalance")
    service_cmd = ""
    if status == "active" and irqbalance_status == "inactive":
        service_cmd = "service irqbalance stop"
    elif status == "inactive" and irqbalance_status == "active":
        service_cmd = "service irqbalance start"
    if service_cmd:
        status, output = session.cmd_status_output(service_cmd)
        if status:
            msg = "Fail to update irqbalance service status in guest."
            msg += " Command output in guest: %s" % output
            raise error.TestError(msg)

    error.context("Get first network interface name in guest.", logging.info)
    devname = get_first_network_devname(session, nic_interface_filter)

    error.context("Start background network stress in guest.", logging.info)
    host_ip = utils_net.get_ip_address_by_interface(params.get('netdst'))
    ping_cmd = "ping %s  -f -q" % host_ip
    ping_timeout = irqbalance_check_count * 10 + 100
    ping_session = vm.wait_for_login(timeout=timeout)
    bg_stress = utils.InterruptedThread(utils_test.raw_ping,
                                        kwargs={'command': ping_cmd,
                                                'timeout': ping_timeout,
                                                'session': ping_session,
                                                'output_func': None})
    bg_stress.start()
    try:
        error.context("Get irq number assigned to attached VF/PF in guest",
                      logging.info)
        irq_nums_dict = get_guest_irq_info(session, devname, cpu_count)
        if irq_nums_dict:
            irqs = irq_nums_dict.keys()

        msg = "Check specified IRQ count grow on specified cpu."
        error.context(msg, logging.info)
        check_irqbalance(session, devname, cpu_count, irqs)
        irq_cpus_dict = {}
        for irq in irqs:
            cpus = get_irq_smp_affinity(session, irq)
            irq_cpus_dict[irq] = cpus

        if irqbalance_status == "inactive":
            msg = "balance IRQs generated by vfs/pfs to different vcpus."
            error.context(msg, logging.info)
            post_irq_cpus_dict = {}
            for irq in irq_cpus_dict:
                balance_cpu_count = 1
                cpus = []
                for cpu in xrange(cpu_count):
                    if cpu not in irq_cpus_dict[irq]:
                        cpus.append(cpu)
                        if len(cpus) == balance_cpu_count:
                            break
                set_irq_smp_affinity(session, irq, cpus)
                post_irq_cpus_dict[irq] = cpus

            for irq in irqs:
                cpus = get_irq_smp_affinity(session, irq)
                msg = "Fail to balance IRQs generated by vf/pf to different cpu"
                if cpus != post_irq_cpus_dict[irq]:
                    raise error.TestFail(msg)

        msg = "Check specified IRQ count grow on specified cpu."
        error.context(msg, logging.info)
        check_irqbalance(session, devname,
                         cpu_count, irqs,
                         count=irqbalance_check_count)

        if irqbalance_status == "active":
            msg = "Check that specified IRQ count grow on every cpu."
            error.context(msg, logging.info)
            post_irq_nums_dict = get_guest_irq_info(session, devname, cpu_count)

            for irq in irqs:
                if irq not in post_irq_nums_dict.keys():
                    post_irqs = post_irq_nums_dict.keys()
                    msg = "Different irq detected: '%s' and '%s'." % (irqs,
                                                                      post_irqs)
                    raise error.TestError(msg)
                for cpu in xrange(cpu_count):
                    if (int(irq_nums_dict[irq][cpu]) >=
                       int(post_irq_nums_dict[irq][cpu])):
                        msg = "'Cpu%s' did not handle more interrupt" % cpu
                        msg += "for irq '%s'." % irq
                        msg += "IRQ balance information for IRQ '%s'\n" % irq
                        msg += "First time: %s\n" % irq_nums_dict
                        msg += "Just now: %s" % post_irq_nums_dict
                        raise error.TestFail(msg)
    finally:
        if bg_stress.isAlive():
            bg_stress.join(suppress_exception=True)
        else:
            logging.warn("Background stress test already finished")
