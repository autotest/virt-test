"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatcaps.html
"""

from virttest.libvirt_xml import base, accessors

class LibvirtXML(base.LibvirtXMLBase):
    """
    Handler of libvirt capabilities and nonspecific item operations.

    Properties:
        os_arch_machine_map: virtual, read-only
            get: dict map from os type names to dict map from arch names
    """

    #TODO: Add more __slots__ and accessors to get some useful stats
    # e.g. guest_count, arch, uuid, cpu_count, etc.

    __slots__ = base.LibvirtXMLBase.__slots__ + ('uuid',
                                                 'os_arch_machine_map',)

    __schema_name__ = "capability"

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementText(property_name="uuid",
                                 libvirtxml=self,
                                 forbidden=['set', 'del'],
                                 parent_xpath='/host',
                                 tag_name='uuid')
        # This will skip self.get_os_arch_machine_map() defined below
        accessors.AllForbidden(property_name="os_arch_machine_map",
                               libvirtxml=self)
        super(LibvirtXML, self).__init__(virsh_instance=virsh_instance)
        # calls set_xml accessor method
        self['xml'] = self.dict_get('virsh').capabilities()


    def get_os_arch_machine_map(self):
        """
        Accessor method for os_arch_machine_map property (in __slots__)
        """
        oamm = {} #Schema {<os_type>:{<arch name>:[<machine>, ...]}}
        xmltreefile = self.dict_get('xml')
        for guest in xmltreefile.findall('guest'):
            os_type_name = guest.find('os_type').text
            # Multiple guest definitions can share same os_type (e.g. hvm, pvm)
            if os_type_name == 'xen':
                os_type_name = 'pv'
            amm = oamm.get(os_type_name, {})
            for arch in guest.findall('arch'):
                arch_name = arch.get('name')
                mmap = amm.get(arch_name, [])
                for machine in arch.findall('machine'):
                    machine_text = machine.text
                    # Don't add duplicate entries
                    if not mmap.count(machine_text):
                        mmap.append(machine_text)
                amm[arch_name] = mmap
            oamm[os_type_name] = amm
        return oamm
