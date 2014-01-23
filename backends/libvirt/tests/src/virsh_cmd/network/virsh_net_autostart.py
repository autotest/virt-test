import logging
from autotest.client.shared import error
from virttest import virsh, utils_libvirtd
from virttest.libvirt_xml import network_xml, xcepts


def run(test, params, env):
    """
    Test command: virsh net-autostart.
    """
    # Gather test parameters
    status_error = "yes" == params.get("status_error", "no")
    net_ref = params.get("net_autostart_net_ref", "netname")
    disable = "yes" == params.get("net_autostart_disable", "no")
    extra = params.get("net_autostart_extra", "")  # extra cmd-line params.
    net_name = params.get("net_autostart_net_name", "autotest")

    # Prepare environment and record current net_state_dict
    backup = network_xml.NetworkXML.new_all_networks_dict()
    backup_state = virsh.net_state_dict()
    logging.debug("Backed up network(s): %s", backup_state)

    # Generate our own bridge
    # First check if a bridge of this name already exists
    try:
        _ = backup[net_name]
    except (KeyError, AttributeError):
        pass  # Not found - good
    else:
        raise error.TestNAError("Found network bridge '%s' - skipping" %
                                (net_name))

    # Define a very bare bones bridge, don't provide UUID - use whatever
    # libvirt ends up generating.  We need to define a persistent network
    # since we'll be looking to restart libvirtd as part of this test.
    #
    # This test cannot use the 'default' bridge (virbr0) since undefining
    # it causes issues for libvirtd restart since it's expected that a
    # default network is defined
    #
    temp_bridge = """
<network>
   <name>%s</name>
   <bridge name="vir%sbr0"/>
</network>
""" % (net_name, net_name)

    try:
        test_xml = network_xml.NetworkXML(network_name=net_name)
        test_xml.xml = temp_bridge
        test_xml.define()
    except xcepts.LibvirtXMLError, detail:
        raise error.TestNAError("Failed to define a test network.\n"
                                "Detail: %s." % detail)

    # To guarantee cleanup will be executed
    try:
        # Run test case

        # Get the updated list and make sure our new bridge exists
        currents = network_xml.NetworkXML.new_all_networks_dict()
        current_state = virsh.net_state_dict()
        logging.debug("Current network(s): %s", current_state)
        try:
            testbr_xml = currents[net_name]
        except (KeyError, AttributeError):
            raise error.TestError("Did not find newly defined bridge '%s'" %
                                  (net_name))

        # Prepare default property for network
        # Transient network can not be set autostart
        # So confirm persistent is true for test
        testbr_xml['persistent'] = True

        # Set network to inactive
        # Since we do not reboot host to check(instead of restarting libvirtd)
        # If default network is active, we cannot check "--disable".
        # Because active network will not be inactive after restarting libvirtd
        # even we set autostart to False. While inactive network will be active
        # after restarting libvirtd if we set autostart to True
        testbr_xml['active'] = False

        # Prepare options and arguments
        if net_ref == "netname":
            net_ref = testbr_xml.name
        elif net_ref == "netuuid":
            net_ref = testbr_xml.uuid

        if disable:
            net_ref += " --disable"

        # Run test case
        # Use function in virsh module directly for both normal and error test
        result = virsh.net_autostart(net_ref, extra)
        logging.debug(result)
        status = result.exit_status

        # Check if autostart or disable is successful with libvirtd restart.
        # TODO: Since autostart is designed for host reboot,
        #       we'd better check it with host reboot.
        utils_libvirtd.libvirtd_restart()

        # Reopen testbr_xml
        currents = network_xml.NetworkXML.new_all_networks_dict()
        current_state = virsh.net_state_dict()
        logging.debug("Current network(s): %s", current_state)
        testbr_xml = currents[net_name]
        is_active = testbr_xml['active']

    finally:
        test_xml.undefine()

    # Check Result
    if status_error:
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if disable:
            if status or is_active:
                raise error.TestFail("Disable autostart failed.")
        else:
            if status or (not is_active):
                raise error.TestFail("Set network autostart failed.")
