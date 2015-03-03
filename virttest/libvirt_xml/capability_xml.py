"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatcaps.html
"""

from virttest import xml_utils
from virttest.libvirt_xml import base, accessors, xcepts


class CapabilityXML(base.LibvirtXMLBase):

    """
    Handler of libvirt capabilities and nonspecific item operations.

    Properties:
        uuid:
            string of host uuid
        guest_capabilities:
            dict, read-only
        get:
            dict map from os type names to dict map from arch names
    """

    # TODO: Add more __slots__ and accessors to get some useful stats
    # e.g. guest_count etc.

    __slots__ = ('uuid', 'guest_capabilities', 'cpu_count', 'arch', 'model',
                 'vendor', 'feature_list', 'power_management_list',
                 'cpu_topolopy')
    __schema_name__ = "capability"

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementText(property_name="uuid",
                                 libvirtxml=self,
                                 forbidden=['set', 'del'],
                                 parent_xpath='/host',
                                 tag_name='uuid')
        # This will skip self.get_guest_capabilities() defined below
        accessors.AllForbidden(property_name="guest_capabilities",
                               libvirtxml=self)
        # This will skip self.get_cpu_count() defined below
        accessors.AllForbidden(property_name="cpu_count",
                               libvirtxml=self)
        # The set action is for test.
        accessors.XMLElementText(property_name="arch",
                                 libvirtxml=self,
                                 forbidden=['del'],
                                 parent_xpath='/host/cpu',
                                 tag_name='arch')
        accessors.XMLElementText(property_name="model",
                                 libvirtxml=self,
                                 forbidden=['del'],
                                 parent_xpath='/host/cpu',
                                 tag_name='model')
        accessors.XMLElementText(property_name="vendor",
                                 libvirtxml=self,
                                 forbidden=['del'],
                                 parent_xpath='/host/cpu',
                                 tag_name='vendor')
        accessors.XMLElementDict(property_name="cpu_topolopy",
                                 libvirtxml=self,
                                 forbidden=['del'],
                                 parent_xpath='/host/cpu',
                                 tag_name='topology')
        # This will skip self.get_feature_list() defined below
        accessors.AllForbidden(property_name="feature_list",
                               libvirtxml=self)
        # This will skip self.get_power_management_list() defined below
        accessors.AllForbidden(property_name="power_management_list",
                               libvirtxml=self)
        super(CapabilityXML, self).__init__(virsh_instance)
        # calls set_xml accessor method
        self['xml'] = self.__dict_get__('virsh').capabilities()

    def get_guest_capabilities(self):
        """
        Accessor method for guest_capabilities property (in __slots__).
        Return a guest capabilities dict in following schema:
        {<os_type>: {<arch name>: {'wordsize': '', 'emulator': '',
        'machine': [<machine name>, ...], 'domaini_<type>': {'emulator': ''}}}}
        """
        guest_capa = {}
        xmltreefile = self.__dict_get__('xml')
        for guest in xmltreefile.findall('guest'):
            os_type_name = guest.find('os_type').text
            # Multiple guest definitions can share same os_type (e.g. hvm, pvm)
            if os_type_name == 'xen':
                os_type_name = 'pv'
            guest_arch = guest_capa.get(os_type_name, {})
            for arch in guest.findall('arch'):
                arch_name = arch.get('name')
                arch_prop = guest_arch.get(arch_name, {})
                arch_prop['wordsize'] = arch.find('wordsize').text
                arch_prop['emulator'] = arch.find('emulator').text
                m_list = []
                for machine in arch.findall('machine'):
                    machine_text = machine.text
                    # Don't add duplicate entries
                    if not m_list.count(machine_text):
                        m_list.append(machine_text)
                arch_prop['machine'] = m_list
                for domain in arch.findall('domain'):
                    domain_name = "domain_" + domain.get('type')
                    dom_prop = {}
                    if domain.find('emulator') is not None:
                        dom_prop['emulator'] = domain.find('emulator').text
                    arch_prop[domain_name] = dom_prop
                guest_arch[arch_name] = arch_prop
            guest_capa[os_type_name] = guest_arch
        return guest_capa

    def get_power_management_list(self):
        """
        Accessor method for power_management_list property (in __slots__)
        """
        xmltreefile = self.__dict_get__('xml')
        pms = xmltreefile.find('host').find('power_management').getchildren()
        return [pm.tag for pm in pms]

    def get_feature_list(self):
        """
        Accessor method for feature_list property (in __slots__)
        """
        feature_list = []  # [<feature1>, <feature2>, ...]
        xmltreefile = self.__dict_get__('xml')
        for feature_node in xmltreefile.findall('/host/cpu/feature'):
            feature_list.append(feature_node)
        return feature_list

    def get_feature(self, num):
        """
        Get a feature element from feature list by number

        :return: Feature element
        """
        count = len(self.feature_list)
        try:
            num = int(num)
            return self.feature_list[num]
        except (ValueError, TypeError):
            raise xcepts.LibvirtXMLError("Invalid feature number %s" % num)
        except IndexError:
            raise xcepts.LibvirtXMLError("Only %d feature(s)" % count)

    def get_feature_name(self, num):
        """
        Get assigned feature name

        :param num: Assigned feature number
        :return: Assigned feature name
        """
        return self.get_feature(num).get('name')

    def get_cpu_count(self):
        """
        Accessor method for cpu_count property (in __slots__)
        """
        cpu_count = 0
        xmltreefile = self.__dict_get__('xml')
        for cpus in xmltreefile.findall('/host/topology/cells/cell/cpus'):
            cpu_num = cpus.get('num')
            cpu_count += int(cpu_num)
        return cpu_count

    def remove_feature(self, num):
        """
        Remove a assigned feature from xml

        :param num: Assigned feature number
        """
        xmltreefile = self.__dict_get__('xml')
        feature_remove_node = self.get_feature(num)
        cpu_node = xmltreefile.find('/host/cpu')
        cpu_node.remove(feature_remove_node)

    def check_feature_name(self, name):
        """
        Check feature name valid or not.

        :param name: The checked feature name
        :return: True if check pass
        """
        sys_feature = []
        cpu_xml_file = open('/proc/cpuinfo', 'r')
        for line in cpu_xml_file.readlines():
            if line.find('flags') != -1:
                feature_names = line.split(':')[1].strip()
                sys_sub_feature = feature_names.split(' ')
                sys_feature = list(set(sys_feature + sys_sub_feature))
        cpu_xml_file.close()
        return (name in sys_feature)

    def set_feature(self, num, value):
        """
        Set a assigned feature value to xml

        :param num: Assigned feature number
        :param value: The feature name modified to
        """
        feature_set_node = self.get_feature(num)
        feature_set_node.set('name', value)

    def add_feature(self, value):
        """
        Add a feature Element to xml

        :param value: The added feature name
        """
        xmltreefile = self.__dict_get__('xml')
        cpu_node = xmltreefile.find('/host/cpu')
        xml_utils.ElementTree.SubElement(cpu_node, 'feature', {'name': value})
