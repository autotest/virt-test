import logging
from autotest.client.shared import error
from virttest import utils_test, utils_net, remote


@error.context_aware
def run_set_link(test, params, env):
    """
    KVM guest link test:
    1) Boot up guest with one nic
    2) Disable guest link by set_link
    3) Check guest nic operstate, and ping guest from host
    4) Reboot the guest, then check guest nic operstate and do ping test
    5) Re-enable guest link by set_link
    6) Check guest nic operstate and ping guest from host
    7) Reboot the guest, then check guest nic operstate and do ping test
    8) Call utils_test.run_file_transfer function to test file transfer.
       It will do following steps:
       8.1) Create a large file by dd on host.
       8.2) Copy this file from host to guest.
       8.3) Copy this file from guest to host.
       8.4) Check if file transfers ended good.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 360))
    # Waiting for guest boot up.
    session = vm.wait_for_login(timeout=timeout)
    os_type = params.get("os_type")
    if os_type == "linux":
        guest_ifname = utils_net.get_linux_ifname(session,
                                                  vm.get_mac_address())
    else:
        guest_ifname = ""

    guest_ip = vm.get_address()
    session.close()

    # Windows guest '2' represent 'Connected',
    # '7' represent 'Media disconnected'
    win_media_connected = params.get("win_media_connected", "2")
    win_media_disconnected = params.get("win_media_disconnected", "7")

    def guest_reboot(reboot_method, link_up):
        """
        Reboot guest by different method (shell/system_reset)
        """
        try:
            vm.reboot(method=reboot_method, timeout=120)
        except remote.LoginError:
            if not link_up:
                logging.info("Login error is expected when net link is down")


    def guest_netwok_connecting_check(guest_ip, link_up):
        """
        Check whether guest network is connective by ping
        """
        if link_up:
            vm.wait_for_login()
            guest_ip = vm.get_address()
        s, o = utils_test.ping(guest_ip, count=10, timeout=20)
        if not link_up and utils_test.get_loss_ratio(o) != 100:
            err_msg = "guest network still connecting after down the link"
            raise error.TestFail(err_msg)
        elif link_up and utils_test.get_loss_ratio(o) == 100:
            err_msg = "All packets lost during ping guest ip after link up"
            raise error.TestFail(err_msg)
        else:
            logging.info("Guest network connecting is exactly as expected")


    def guest_interface_operstate_check(expect_status, guest_ifname=""):
        """
        Check Guest interface operstate
        """
        session = vm.wait_for_serial_login()

        os_type = params.get("os_type")
        if os_type == "linux":
            if_operstate  = utils_net.get_net_if_operstate(guest_ifname,
                                                           session.cmd)
        else:
            if_operstate = utils_net.get_windows_nic_attribute(session,
                "macaddress", vm.get_mac_address(), "netconnectionstatus")
        session.close()

        if if_operstate != expect_status:
            err_msg = "Guest interface %s status error, " % guest_ifname
            err_msg = "currently interface status is '%s', " % if_operstate
            err_msg += "but expect status is '%s'" % expect_status
            raise error.TestError(err_msg)
        logging.info("Guest interface operstate '%s' is exactly as expected" %
                     if_operstate)


    def set_link_test(linkid, link_up, expect_status,
                      operstate_always_up=False):
        """
        Issue set_link commands and test its function

        :param linkid: id of netdev or devices to be tested
        :param link_up: flag linkid is up or down
        :param expect_status : expect guest operstate status"
        :param operstate_always_up: when linkid is netdev id, guest interface
                                    operstate will never change,
                                    need set it to True.

        """
        vm.set_link(linkid, up=link_up)
        error.context("Check guest interface operstate", logging.info)
        if operstate_always_up:
            if expect_status == "down":
                expect_status = "up"
            if expect_status == win_media_disconnected:
                expect_status = win_media_connected
        guest_interface_operstate_check(expect_status, guest_ifname)

        error.context("Check if guest network connective", logging.info)
        guest_netwok_connecting_check(guest_ip, link_up)

        reboot_method = params.get("reboot_method", "shell")
        error.context("Reboot guest by '%s' and recheck interface operstate" %
                       reboot_method, logging.info)
        guest_reboot(reboot_method, link_up)
        guest_interface_operstate_check(expect_status, guest_ifname)

        error.context("Check guest network connecting after reboot by '%s'" %
                      reboot_method, logging.info)
        guest_netwok_connecting_check(guest_ip, link_up)


    netdev_id = vm.virtnet[0].netdev_id
    device_id = vm.virtnet[0].device_id
    expect_down_status = params.get("down-status", "down")
    expect_up_status = params.get("up-status", "up")

    error.context("Disable guest netdev link '%s' by set_link" % netdev_id,
                  logging.info)
    set_link_test(netdev_id, False, expect_down_status, True)

    error.context("Re-enable guest netdev link '%s' by set_link" % netdev_id,
                  logging.info)
    set_link_test(netdev_id, True, expect_up_status, True)

    error.context("Disable guest nic device '%s' by set_link" % device_id,
                  logging.info)
    set_link_test(device_id, False, expect_down_status)

    error.context("Re-enable guest nic device '%s' by set_link" % device_id,
                  logging.info)
    set_link_test(device_id, True, expect_up_status)

    error.context("Do file transfer after setlink on and off", logging.info)
    utils_test.run_file_transfer(test, params, env)
