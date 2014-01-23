import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_vm
from virttest.libvirt_xml import network_xml


def run(test, params, env):
    """
    Test command: virsh net-start.
    """
    # Gather test parameters
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    status_error = "yes" == params.get("status_error", "no")
    inactive_default = "yes" == params.get("net_start_inactive_default", "yes")
    net_ref = params.get("net_start_net_ref", "netname")  # default is tested
    extra = params.get("net_start_options_extra", "")  # extra cmd-line params.

    # make easy to maintain
    virsh_dargs = {'uri': uri, 'debug': False, 'ignore_status': True}
    virsh_instance = virsh.VirshPersistent(**virsh_dargs)

    # Get all network instance
    origin_nets = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)

    # Prepare default network for following test.
    try:
        default_netxml = origin_nets['default']
    except KeyError:
        virsh_instance.close_session()
        raise error.TestNAError("Test requires default network to exist")
    # To confirm default network is active
    if not default_netxml.active:
        default_netxml.active = True

    # inactive default according test's need
    if inactive_default:
        logging.info("Stopped default network")
        default_netxml.active = False

    # State before run command
    origin_state = virsh_instance.net_state_dict()
    logging.debug("Origin network(s) state: %s", origin_state)

    if net_ref == "netname":
        net_ref = default_netxml.name
    elif net_ref == "netuuid":
        net_ref = default_netxml.uuid

    # Run test case
    result = virsh.net_start(net_ref, extra, **virsh_dargs)
    logging.debug(result)
    status = result.exit_status

    # Get current net_stat_dict
    current_state = virsh_instance.net_state_dict()
    logging.debug("Current network(s) state: %s", current_state)
    is_default_active = current_state['default']['active']

    # Recover default state to active
    if not is_default_active:
        default_netxml.active = True

    virsh_instance.close_session()

    # Check status_error
    if status_error:
        if not status:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if status:
            raise error.TestFail("Run failed with right command")
        else:
            if not is_default_active:
                raise error.TestFail("Execute cmd successfully but "
                                     "default is inactive actually.")
