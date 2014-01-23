import logging
from autotest.client.shared import error
from virttest import virsh, libvirt_vm, xml_utils
from virttest.libvirt_xml import network_xml, xcepts


def get_network_xml_instance(virsh_dargs, test_xml, net_name,
                             net_uuid, bridge):
    test_netxml = network_xml.NetworkXML(
        virsh_instance=virsh.Virsh(**virsh_dargs))
    test_netxml.xml = test_xml.name

    # modify XML if called for
    if net_name is not "":
        test_netxml.name = net_name
    else:
        test_netxml.name = "default"
    if net_uuid is not "":
        test_netxml.uuid = net_uuid
    else:
        del test_netxml.uuid  # let libvirt auto-generate
    if bridge is not None:
        test_netxml.bridge = bridge

    # TODO: Test other network parameters

    logging.debug("Modified XML:")
    test_netxml.debug_xml()
    return test_netxml


def run(test, params, env):
    """
    Test command: virsh net-define/net-undefine.

    1) Collect parameters&environment info before test
    2) Prepare options for command
    3) Execute command for test
    4) Check state of defined network
    5) Recover environment
    6) Check result
    """
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    net_name = params.get("net_define_undefine_net_name", "default")
    net_uuid = params.get("net_define_undefine_net_uuid", "")
    options_ref = params.get("net_define_undefine_options_ref", "default")
    trans_ref = params.get("net_define_undefine_trans_ref", "trans")
    extra_args = params.get("net_define_undefine_extra", "")
    remove_existing = params.get("net_define_undefine_remove_existing", "yes")
    status_error = "yes" == params.get("status_error", "no")

    virsh_dargs = {'uri': uri, 'debug': False, 'ignore_status': True}
    virsh_instance = virsh.VirshPersistent(**virsh_dargs)

    # Prepare environment and record current net_state_dict
    backup = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)
    backup_state = virsh_instance.net_state_dict()
    logging.debug("Backed up network(s): %s", backup_state)

    # Make some XML to use for testing, for now we just copy 'default'
    test_xml = xml_utils.TempXMLFile()  # temporary file
    try:
        # LibvirtXMLBase.__str__ returns XML content
        test_xml.write(str(backup['default']))
        test_xml.flush()
    except (KeyError, AttributeError):
        raise error.TestNAError("Test requires default network to exist")

    testnet_xml = get_network_xml_instance(virsh_dargs, test_xml, net_name,
                                           net_uuid, bridge=None)

    if remove_existing:
        for netxml in backup.values():
            netxml.orbital_nuclear_strike()

    # Test both define and undefine, So collect info
    # both of them for result check.
    # When something wrong with network, set it to 1
    fail_flag = 0
    result_info = []

    if options_ref == "correct_arg":
        define_options = testnet_xml.xml
        undefine_options = net_name
    elif options_ref == "no_option":
        define_options = ""
        undefine_options = ""
    elif options_ref == "not_exist_option":
        define_options = "/not/exist/file"
        undefine_options = "NOT_EXIST_NETWORK"

    define_extra = undefine_extra = extra_args
    if trans_ref != "define":
        define_extra = ""

    try:
        # Run test case
        define_result = virsh.net_define(define_options, define_extra,
                                         **virsh_dargs)
        logging.debug(define_result)
        define_status = define_result.exit_status

        # If defining network succeed, then trying to start it.
        if define_status == 0:
            start_result = virsh.net_start(net_name, extra="", **virsh_dargs)
            logging.debug(start_result)
            start_status = start_result.exit_status

        if trans_ref == "trans":
            if define_status:
                fail_flag = 1
                result_info.append("Define network with right command failed.")
            else:
                if start_status:
                    fail_flag = 1
                    result_info.append("Network is defined as expected, "
                                       "but failed to start it.")

        # Stop network for undefine test anyway
        destroy_result = virsh.net_destroy(net_name, extra="", **virsh_dargs)
        logging.debug(destroy_result)

        # Undefine network
        undefine_result = virsh.net_undefine(undefine_options, undefine_extra,
                                             **virsh_dargs)
        if trans_ref != "define":
            logging.debug(undefine_result)
        undefine_status = undefine_result.exit_status

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
                except xcepts.LibvirtXMLError, detail:
                    fail_flag = 1
                    result_info.append(str(detail))

        # Close down persistent virsh session (including for all netxml copies)
        if hasattr(virsh_instance, 'close_session'):
            virsh_instance.close_session()

        # Done with file, cleanup
        del test_xml
        del testnet_xml

    # Check status_error
    # If fail_flag is set, it must be transaction test.
    if fail_flag:
        raise error.TestFail("Define network for transaction test "
                             "failed:%s", result_info)

    # The logic to check result:
    # status_error&only undefine:it is negative undefine test only
    # status_error&(no undefine):it is negative define test only
    # (not status_error)&(only undefine):it is positive transaction test.
    # (not status_error)&(no undefine):it is positive define test only
    if status_error:
        if trans_ref == "undefine":
            if undefine_status == 0:
                raise error.TestFail("Run successfully with wrong command.")
        else:
            if define_status == 0:
                if start_status == 0:
                    raise error.TestFail("Define an unexpected network, "
                                         "and start it successfully.")
                else:
                    raise error.TestFail("Define an unexpected network, "
                                         "but start it failed.")
    else:
        if trans_ref == "undefine":
            if undefine_status:
                raise error.TestFail("Define network for transaction "
                                     "successfully, but undefine failed.")
        else:
            if define_status != 0:
                raise error.TestFail("Run failed with right command")
            else:
                if start_status != 0:
                    raise error.TestFail("Network is defined as expected, "
                                         "but start it failed.")
