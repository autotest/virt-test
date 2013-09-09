import logging
import re
from autotest.client.shared import error
from virttest import utils_net


@error.context_aware
def run_enable_mq(test, params, env):
    """
    Enable MULTI_QUEUE feature in guest

    1) Boot up VM(s)
    2) Login guests one by one
    3) Enable MQ for all virtio nics by ethtool -L

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """

    login_timeout = int(params.get("login_timeout", 360))
    queues = int(params.get("queues", 1))
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
                ifname = utils_net.get_linux_ifname(
                    session, vm.get_mac_address(0))
                session.cmd_output("ethtool -L %s combined %d"
                                   % (ifname, queues))
                o = session.cmd_output("ethtool -l %s" % ifname)
                if len(re.findall("Combined:\s+%d\s" % queues, o)) != 2:
                    raise error.TestError("Fail to enable MQ feature of (%s)"
                                          % nic.nic_name)

                logging.info("MQ feature of (%s) is enabled" % nic.nic_name)

        session.close()
