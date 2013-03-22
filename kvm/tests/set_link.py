import logging
from autotest.client.shared import error
from autotest.client.virt import utils_test


def run_set_link(test, params, env):
    """
    KVM guest link test:
    1) Boot up guest with one nic
    2) Ping guest from host
    3) Disable guest link and ping guest from host
    4) Re-enable guest link and ping guest from host
    5) Do file transfer test

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = utils_test.get_living_vm(env, params.get("main_vm"))
    timeout = float(params.get("login_timeout", 360))
    session = utils_test.wait_for_login(vm, 0, timeout, 0, 2)

    def set_link_test(linkid):
        """
        Issue set_link commands and test its function

        @param linkid: id of netdev or devices to be tested
        """
        ip = vm.get_address(0)

        vm.set_link(linkid, up=False)
        _, o = utils_test.ping(ip, count=10, timeout=20)
        if utils_test.get_loss_ratio(o) != 100:
            raise error.TestFail("Still can ping the %s after down %s" %
                                 (ip, linkid))

        vm.set_link(linkid, up=True)
        _, o = utils_test.ping(ip, count=10, timeout=20)
        # we use 100% here as the notification of link status changed may be
        # delayed in guest driver
        if utils_test.get_loss_ratio(o) == 100:
            raise error.TestFail("Packet loss during ping %s after up %s" %
                                 (ip, linkid))

    netdev_id = vm.netdev_id[0]
    device_id = vm.get_peer(netdev_id)
    logging.info("Issue set_link commands for netdevs")
    set_link_test(netdev_id)
    logging.info("Issue set_link commands for network devics")
    set_link_test(device_id)

    utils_test.run_file_transfer(test, params, env)
    session.close()
