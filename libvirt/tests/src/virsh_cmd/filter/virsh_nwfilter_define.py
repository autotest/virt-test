import os
import logging
from autotest.client.shared import error
from virttest import virsh, xml_utils, libvirt_xml


NWFILTER_ETC_DIR = "/etc/libvirt/nwfilter"
RULE_ATTR = ('rule_action', 'rule_direction', 'rule_priority',
             'rule_statematch')
PROTOCOL_TYPES = ['mac', 'vlan', 'stp', 'arp', 'rarp', 'ip', 'ipv6',
                  'tcp', 'udp', 'sctp', 'icmp', 'igmp', 'esp', 'ah',
                  'udplite', 'all', 'tcp-ipv6', 'udp-ipv6', 'sctp-ipv6',
                  'icmpv6', 'esp-ipv6', 'ah-ipv6', 'udplite-ipv6',
                  'all-ipv6']


def check_list(uuid, name):
    """
    Return True if filter found in nwfilter-list

    :param uuid: filter uuid
    :param name: filter name
    :return: True if found, False if not found
    """
    cmd_result = virsh.nwfilter_list(options="",
                                     ignore_status=True, debug=True)
    output = cmd_result.stdout.strip().split('\n')
    for i in range(2, len(output)):
        if output[i].split() == [uuid, name]:
            return True
    return False


def run(test, params, env):
    """
    Test command: virsh nwfilter-define.

    1) Prepare parameters.
    2) Set options of virsh define.
    3) Run define command.
    4) Check result.
    5) Clean env
    """
    # Prepare parameters
    filter_name = params.get("filter_name", "testcase")
    filter_chain = params.get("filter_chain", "root")
    filter_priority = params.get("filter_priority", "")
    filter_uuid = params.get("filter_uuid",
                      "5c6d49af-b071-6127-b4ec-6f8ed4b55335")
    filterref = params.get("filterref")
    filterref_name = params.get("filterref_name")
    exist_filter = params.get("exist_filter", "no-mac-spoofing")
    filter_xml = params.get("filter_create_xml_file")
    options_ref = params.get("options_ref", "")
    status_error = params.get("status_error", "no")

    # prepare rule and protocol attributes
    protocol = {}
    rule_dict = {}
    rule_dict_tmp = {}
    # rule string should end with EOL as separator, multiple rules is supported
    rule = params.get("rule",
                      "rule_action=accept rule_direction=out protocol=mac EOL")
    rule_list = rule.split('EOL')

    for i in range(len(rule_list)):
        if rule_list[i]:
            attr = rule_list[i].split()
            for j in range(len(attr)):
                attr_list = attr[j].split('=')
                rule_dict_tmp[attr_list[0]] = attr_list[1]
            rule_dict[i] = rule_dict_tmp
            rule_dict_tmp = {}

    # process protocol parameter
    for i in rule_dict.keys():
        if 'protocol' not in rule_dict[i]:
            # Set protocol as string 'None' as parse from cfg is
            # string 'None'
            protocol[i] = 'None'
        else:
            protocol[i] = rule_dict[i]['protocol']
            rule_dict[i].pop('protocol')

            if protocol[i] in PROTOCOL_TYPES:
                # replace '-' with '_' in ipv6 types as '-' is not
                # supposed to be in class name
                if '-' in protocol[i]:
                    protocol[i] = protocol[i].replace('-', '_')
            else:
                raise error.TestFail("Given protocol type %s" % protocol[i]
                                     + " is not in supported list %s" %
                                     PROTOCOL_TYPES)

    if filter_xml == "invalid-filter-xml":
        tmp_xml = xml_utils.TempXMLFile()
        tmp_xml.write('"<filter><<<BAD>>><\'XML</name\>'
                      '!@#$%^&*)>(}>}{CORRUPTE|>!</filter>')
        tmp_xml.flush()
        filter_xml = tmp_xml.name
        logging.info("Test invalid xml is: %s" % filter_xml)
    elif filter_xml != " ":
        # Use exist xml as template with new attributes
        new_filter = libvirt_xml.NwfilterXML()
        filterxml = new_filter.new_from_filter_dumpxml(exist_filter)
        logging.debug("the exist xml is:\n%s" % filterxml.xmltreefile)

        # Backup xml if only update exist filter
        if exist_filter == filter_name:
            backup_xml = filterxml.xmltreefile.backup_copy()

        # Set filter attribute
        filterxml.filter_name = filter_name
        filterxml.filter_chain = filter_chain
        filterxml.filter_priority = filter_priority
        filterxml.uuid = filter_uuid
        if filterref:
            filterxml.filterref = filterref
            filterxml.filterref_name = filterref_name

        # Set rule attribute
        index_total = filterxml.get_rule_index()
        rule = filterxml.get_rule(0)
        rulexml = rule.backup_rule()
        for i in range(len(rule_dict.keys())):
            rulexml.rule_action = rule_dict[i].get('rule_action')
            rulexml.rule_direction = rule_dict[i].get('rule_direction')
            rulexml.rule_priority = rule_dict[i].get('rule_priority')
            rulexml.rule_statematch = rule_dict[i].get('rule_statematch')
            for j in RULE_ATTR:
                if j in rule_dict[i].keys():
                    rule_dict[i].pop(j)

            # set protocol attribute
            if protocol[i] != 'None':
                protocolxml = rulexml.get_protocol(protocol[i])
                new_one = protocolxml.new_attr(**rule_dict[i])
                protocolxml.attrs = new_one
                rulexml.xmltreefile = protocolxml.xmltreefile
            else:
                rulexml.del_protocol()

            if i <= len(index_total) - 1:
                filterxml.set_rule(rulexml, i)
            else:
                filterxml.add_rule(rulexml)

            # Reset rulexml
            rulexml = rule.backup_rule()

        logging.info("The xml for define is:\n%s" % filterxml.xmltreefile)
        filterxml.xmltreefile.write(filter_xml)

    # Run command
    cmd_result = virsh.nwfilter_define(filter_xml, options=options_ref,
                                        ignore_status=True, debug=True)
    status = cmd_result.exit_status

    # Check result
    chk_result = check_list(filter_uuid, filter_name)
    xml_path = "%s/%s.xml" % (NWFILTER_ETC_DIR, filter_name)
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command.")
    elif status_error == "no":
        if status:
            raise error.TestFail("Run failed with right command.")
        if not chk_result:
            raise error.TestFail("Can't find filter in nwfilter-list output")
        if not os.path.exists(xml_path):
            raise error.TestFail("Can't find filter xml under %s" %
                                 NWFILTER_ETC_DIR)
        logging.info("Dump the xml after define:")
        virsh.nwfilter_dumpxml(filter_name,
                               ignore_status=True,
                               debug=True)

    # Clean env
    if exist_filter == filter_name:
        logging.info("Restore exist filter: %s" % exist_filter)
        backup_xml.write(filter_xml)
        virsh.nwfilter_define(filter_xml,
                              options="",
                              ignore_status=True,
                              debug=True)
    else:
        if chk_result:
            virsh.nwfilter_undefine(filter_name,
                                    options="",
                                    ignore_status=True,
                                    debug=True)
    if os.path.exists(filter_xml):
        os.remove(filter_xml)
