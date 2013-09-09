import logging
from autotest.client.shared import error
from virttest import utils_test


@error.context_aware
def run_set_link(test, params, env):
    """
    KVM guest link test:
    1) Boot up guest with one nic
    2) Disable guest link by set_link
    3) Ping guest from host
    4) Re-enable guest link by set_link
    5) Ping guest from host
    6) Call utils_test.run_file_transfer function to test file transfer.
       It will do following steps:
       6.1) Create a large file by dd on host.
       6.2) Copy this file from host to guest.
       6.3) Copy this file from guest to host.
       6.4) Check if file transfers ended good.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = utils_test.get_living_vm(env, params["main_vm"])
    timeout = float(params.get("login_timeout", 360))
    # Waiting for guest boot up.
    session = vm.wait_for_login(timeout=timeout)
    session.close()

    def set_link_test(linkid):
        """
        Issue set_link commands and test its function

        @param linkid: id of netdev or devices to be tested
        """
        ip = vm.get_address(0)
        error.context("Disable guest link by set_link", logging.info)
        vm.set_link(linkid, up=False)
        error.context("Ping guest from host", logging.info)
        s, o = utils_test.ping(ip, count=10, timeout=20)
        if utils_test.get_loss_ratio(o) != 100:
            raise error.TestFail("Still can ping the %s after down %s" %
                                 (ip, linkid))

        error.context("Re-enable guest link by set_link", logging.info)
        vm.set_link(linkid, up=True)
        # Waiting for guest network up again.
        session = vm.wait_for_login(timeout=timeout)
        session.close()
        error.context("Ping guest from host", logging.info)
        s, o = utils_test.ping(ip, count=10, timeout=20)
        # we use 100% here as the notification of link status changed may be
        # delayed in guest driver
        if utils_test.get_loss_ratio(o) == 100:
            raise error.TestFail("Packet loss during ping %s after up %s" %
                                 (ip, linkid))

    netdev_id = vm.virtnet[0].netdev_id
    device_id = vm.virtnet[0].device_id
    logging.info("Issue set_link commands for netdevs")
    set_link_test(netdev_id)
    logging.info("Issue set_link commands for network devics")
    set_link_test(device_id)

    utils_test.run_file_transfer(test, params, env)
