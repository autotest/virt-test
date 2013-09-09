import logging
import re
from autotest.client.shared import error
from virttest import utils_misc, utils_net


@error.context_aware
def run_mac_change(test, params, env):
    """
    Change MAC address of guest.

    1) Get a new mac from pool, and the old mac addr of guest.
    2) Set new mac in guest and regain new IP.
    3) Re-log into guest with new MAC.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    # This session will be used to assess whether the IP change worked
    session = vm.wait_for_login(timeout=timeout)
    old_mac = vm.get_mac_address(0)
    while True:
        vm.virtnet.free_mac_address(0)
        new_mac = vm.virtnet.generate_mac_address(0)
        if old_mac != new_mac:
            break

    os_type = params.get("os_type")
    os_variant = params.get("os_variant")
    change_cmd_pattern = params.get("change_cmd")

    logging.info("The initial MAC address is %s", old_mac)
    if os_type == "linux":
        interface = utils_net.get_linux_ifname(session_serial, old_mac)
        if params.get("shutdown_int", "yes") == "yes":
            int_shutdown_cmd = params.get("int_shutdown_cmd",
                                          "ifconfig %s down")
            session_serial.cmd(int_shutdown_cmd % interface)
    else:

        connection_id = utils_net.get_windows_nic_attribute(session,
                                                            "macaddress",
                                                            old_mac,
                                                            "netconnectionid")
        nic_index = utils_net.get_windows_nic_attribute(session,
                                                        "netconnectionid",
                                                        connection_id,
                                                        "index")
        if os_variant == "winxp":
            pnpdevice_id = utils_net.get_windows_nic_attribute(session,
                                                               "netconnectionid",
                                                               connection_id,
                                                               "pnpdeviceid")
            cd_drive = utils_misc.get_winutils_vol(session)
            copy_cmd = r"xcopy %s:\devcon\wxp_x86\devcon.exe c:\ " % cd_drive
            session.cmd(copy_cmd)

    # Start change MAC address
    error.context("Changing MAC address to %s" % new_mac, logging.info)
    if os_type == "linux":
        change_cmd = change_cmd_pattern % (interface, new_mac)
    else:
        change_cmd = change_cmd_pattern % (int(nic_index),
                                           "".join(new_mac.split(":")))
    try:
        session_serial.cmd(change_cmd)

        # Verify whether MAC address was changed to the new one
        error.context("Verify the new mac address, and restart the network",
                      logging.info)
        if os_type == "linux":
            if params.get("shutdown_int", "yes") == "yes":
                int_activate_cmd = params.get("int_activate_cmd",
                                              "ifconfig %s up")
                session_serial.cmd(int_activate_cmd % interface)
            session_serial.cmd("ifconfig | grep -i %s" % new_mac)
            logging.info("Mac address change successfully, net restart...")
            dhclient_cmd = "dhclient -r && dhclient %s" % interface
            session_serial.sendline(dhclient_cmd)
        else:
            mode = "netsh"
            if os_variant == "winxp":
                connection_id = pnpdevice_id.split("&")[-1]
                mode = "devcon"
            utils_net.restart_windows_guest_network(session_serial,
                                                    connection_id,
                                                    mode=mode)

            o = session_serial.cmd("ipconfig /all")
            if not re.findall("%s" % "-".join(new_mac.split(":")), o, re.I):
                raise error.TestFail("Guest mac change failed")
            logging.info("Guest mac have been modified successfully")

        # Re-log into the guest after changing mac address
        if utils_misc.wait_for(session.is_responsive, 120, 20, 3):
            # Just warning when failed to see the session become dead,
            # because there is a little chance the ip does not change.
            logging.warn("The session is still responsive, settings may fail.")
        session.close()

        # Re-log into guest and check if session is responsive
        error.context("Re-log into the guest", logging.info)
        session = vm.wait_for_login(timeout=timeout)
        if not session.is_responsive():
            raise error.TestFail("The new session is not responsive.")
    finally:
        if os_type == "windows":
            clean_cmd_pattern = params.get("clean_cmd")
            clean_cmd = clean_cmd_pattern % int(nic_index)
            session_serial.cmd(clean_cmd)
            utils_net.restart_windows_guest_network(session_serial,
                                                    connection_id,
                                                    mode=mode)
            nic = vm.virtnet[0]
            nic.mac = old_mac
            vm.virtnet.update_db()
        session.close()
