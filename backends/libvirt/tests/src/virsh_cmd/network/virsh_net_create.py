import logging
from autotest.client.shared import error
from virttest import libvirt_vm, libvirt_xml, virsh, xml_utils


def do_low_level_test(virsh_dargs, test_xml, options_ref, extra):

    # Process command-line argument/option parameters
    if options_ref == "file_arg":
        alt_file = "--file %s" % test_xml.name  # returns filename
    elif options_ref == "no_file":
        alt_file = "''"  # empty string will be passed
    elif options_ref == "extra_file":
        alt_file = "%s %s" % (test_xml.name, test_xml.name)
    elif options_ref == "no_exist_file":
        alt_file = "foobar" + test_xml.name
    else:
        alt_file = test_xml.name

    logging.debug("Calling virsh net-create with alt_file '%s' and "
                  "extra '%s'", alt_file, extra)

    try:
        # ignore_status==False
        virsh.net_create(alt_file, extra, **virsh_dargs)
        return True
    except (error.CmdError), cmd_excpt:
        # CmdError catches failing virsh commands
        logging.debug("Exception-thrown: " + str(cmd_excpt))
        return False


def do_high_level_test(virsh_dargs, test_xml, net_name, net_uuid, bridge):

    test_netxml = libvirt_xml.NetworkXML(virsh.Virsh(**virsh_dargs))
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

    # Network XML is not big, just print out.
    logging.debug("Modified XML:")
    test_netxml.debug_xml()

    try:
        test_netxml.create()
        return test_netxml.defined
    except (IOError, error.CmdError), cmd_excpt:
        # CmdError catches failing virsh commands
        # IOError catches corrupt XML data
        logging.debug("Exception-thrown: " + str(cmd_excpt))
        return False


def run(test, params, env):
    """
    Test command: virsh net-create.

    1) Gather test parameters
    2) Store current libvirt host network state
    3) Call virsh net create on possibly modified network XML
    4) Recover original network.
    5) Check result.
    """

    # Gather test parameters
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    status_error = "yes" == params.get("status_error", "no")
    net_name = params.get("net_create_net_name", "")  # default is tested
    net_uuid = params.get("net_create_net_uuid", "")  # default is tested
    options_ref = params.get("net_create_options_ref", "")  # default is tested
    # extra cmd-line params.
    extra = params.get("net_create_options_extra", "")
    corrupt = "yes" == params.get("net_create_corrupt_xml", "no")
    remove_existing = "yes" == params.get("net_create_remove_existing", "yes")
    # Dictionary or None value
    bridge = eval(params.get("net_create_bridge", "None"),
                  {'__builtins__': None}, {})
    # make easy to maintain
    virsh_dargs = {'uri': uri, 'debug': False, 'ignore_status': False}
    vrsh = virsh.VirshPersistent(**virsh_dargs)

    # Prepare environment and record current net_state_dict
    backup = libvirt_xml.NetworkXML.new_all_networks_dict(vrsh)
    backup_state = vrsh.net_state_dict()
    logging.debug("Backed up network(s): %s", backup_state)

    # Make some XML to use for testing, for now we just copy 'default'
    test_xml = xml_utils.TempXMLFile()  # temporary file
    try:
        # LibvirtXMLBase.__str__ returns XML content
        test_xml.write(str(backup['default']))
        test_xml.flush()
    except (KeyError, AttributeError):
        raise error.TestNAError("Test requires default network to exist")
    if corrupt:
        # find file size
        test_xml.seek(0, 2)  # end
        # write garbage at middle of file
        test_xml.seek(test_xml.tell() / 2)
        test_xml.write('"<network><<<BAD>>><\'XML</network\>'
                       '!@#$%^&*)>(}>}{CORRUPTE|>!')
        test_xml.flush()
        # Assume next user might want to read
        test_xml.seek(0)

    if remove_existing:
        for netxml in backup.values():
            netxml.orbital_nuclear_strike()

    # Run test case

    # Be nice to user
    if status_error:
        logging.info("The following is expected to fail...")

    try:
        # Determine depth of test - if low-level calls are needed
        if (options_ref or extra or corrupt):
            logging.debug("Performing low-level net-create test")
            # vrsh will act like it's own virsh-dargs, i.e. it is dict-like
            test_passed = do_low_level_test(vrsh, test_xml, options_ref, extra)
        else:  # high-level test
            logging.debug("Performing high-level net-create test")
            # vrsh will act like it's own virsh-dargs, i.e. it is dict-like
            test_passed = do_high_level_test(vrsh, test_xml, net_name,
                                             net_uuid, bridge)
    finally:
        # Be nice to user
        if status_error:
            # In case test itself has errors, warn they are real.
            logging.info("The following is NOT expected to fail...")

        # Done with file, cleanup
        del test_xml

        # Recover environment
        leftovers = libvirt_xml.NetworkXML.new_all_networks_dict(vrsh)
        for netxml in leftovers.values():
            netxml.orbital_nuclear_strike()

        # Recover from backup
        for netxml in backup.values():
            netxml.create()
            # autostart = True requires persistent = True first!
            for state in ['active', 'persistent', 'autostart']:
                netxml[state] = backup_state[netxml.name][state]

        # Close down persistent virsh session (including for all netxml copies)
        vrsh.close_session()

    # Check Result
    if status_error:  # An error was expected
        if test_passed:  # Error was not produced
            raise error.TestFail("Error test did not fail!")
    else:  # no error expected
        if not test_passed:
            raise error.TestFail("Normal test returned failure")
