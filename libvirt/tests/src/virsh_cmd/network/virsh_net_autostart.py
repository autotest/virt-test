import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_vm, utils_libvirtd
from virttest.libvirt_xml import network_xml, xcepts


def run_virsh_net_autostart(test, params, env):
    """
    Test command: virsh net-autostart.
    """
    # Gather test parameters
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    status_error = "yes" == params.get("status_error", "no")
    net_ref = params.get("net_autostart_net_ref", "netname")
    disable = "yes" == params.get("net_autostart_disable", "no")
    extra = params.get("net_autostart_extra", "")  # extra cmd-line params.

    # Make easy to maintain
    virsh_dargs = {'uri': uri, 'debug': False, 'ignore_status': True}
    virsh_instance = virsh.VirshPersistent(**virsh_dargs)

    # Prepare environment and record current net_state_dict
    backup = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)
    backup_state = virsh_instance.net_state_dict()
    logging.debug("Backed up network(s): %s", backup_state)

    try:
        default_xml = backup['default']
    except (KeyError, AttributeError):
        raise error.TestNAError("Test requires default network to exist")

    # To guarantee cleanup will be executed
    try:
        # Remove all network before test
        for netxml in backup.values():
            netxml.orbital_nuclear_strike()

        # Prepare default property for network
        # Transeint network can not be set autostart
        # So confirm persistent is true for test
        default_xml['persistent'] = True
        netname = "default"
        netuuid = default_xml.uuid

        # Set network 'default' to inactive
        # Since we do not reboot host to check(instead of restarting libvirtd)
        # If default network is active, we cann't check "--disable".
        # Because active network will not be inactive after restarting libvirtd
        # even we set autostart to False. While inactive network will be active
        # after restarting libvirtd if we set autostart to True
        default_xml['active'] = False

        currents = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)
        current_state = virsh_instance.net_state_dict()
        logging.debug("Current network(s): %s", current_state)

        # Prepare options and arguments
        if net_ref == "netname":
            net_ref = netname
        elif net_ref == "netuuid":
            net_ref = netuuid

        if disable:
            net_ref += " --disable"

        # Run test case
        # Use function in virsh module directly for both normal and error test
        result = virsh.net_autostart(net_ref, extra, **virsh_dargs)
        logging.debug(result)
        status = result.exit_status

        # Close down persistent virsh session (including for all netxml copies)
        if hasattr(virsh_instance, 'close_session'):
            virsh_instance.close_session()

        # Check if autostart or disable is successful with libvirtd restart.
        # TODO: Since autostart is designed for host reboot,
        #       we'd better check it with host reboot.
        utils_libvirtd.libvirtd_restart()

        # Reopen default_xml
        virsh_instance = virsh.VirshPersistent(**virsh_dargs)
        currents = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)
        current_state = virsh_instance.net_state_dict()
        logging.debug("Current network(s): %s", current_state)
        default_xml = currents['default']
        is_active = default_xml['active']

    finally:
        # Recover environment
        leftovers = network_xml.NetworkXML.new_all_networks_dict(
            virsh_instance)
        for netxml in leftovers.values():
            netxml.orbital_nuclear_strike()

        # Recover from backup
        for netxml in backup.values():
            # If network is transient
            if ((not backup_state[netxml.name]['persistent'])
               and backup_state[netxml.name]['active']):
                netxml.create()
                continue
            # autostart = True requires persistent = True first!
            for state in ['persistent', 'autostart', 'active']:
                try:
                    netxml[state] = backup_state[netxml.name][state]
                except xcepts.LibvirtXMLError:
                    pass

        # Close down persistent virsh session (including for all netxml copies)
        if hasattr(virsh_instance, 'close_session'):
            virsh_instance.close_session()

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
