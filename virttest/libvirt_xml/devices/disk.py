"""
disk device support class(es)

http://libvirt.org/formatdomain.html#elementsDisks
"""

from virttest.libvirt_xml import accessors, xcepts
from virttest.libvirt_xml.devices import base, address


class Disk(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('device_type', 'source_file',
                                                  'target_dev', 'target_bus')

    def __init__(self, type_name, virsh_instance=base.base.virsh):
        super(Disk, self).__init__(device_tag='disk',
                                   type_name=type_name,
                                   virsh_instance=virsh_instance)
        # Generate getter, setter, deleter for some necessary properties
        accessors.XMLAttribute('device_type', self,
                               parent_xpath='/',
                               tag_name='disk',
                               attribute='device')
        accessors.XMLAttribute('source_file', self,
                               parent_xpath='/',
                               tag_name='source',
                               attribute='file')
        accessors.XMLAttribute('target_dev', self,
                               parent_xpath='/',
                               tag_name='target',
                               attribute='dev')
        accessors.XMLAttribute('target_bus', self,
                               parent_xpath='/',
                               tag_name='target',
                               attribute='bus')

    def get_address(self):
        address_node = self.xmltreefile.find('address')
        if address_node is None:
            raise xcepts.LibvirtXMLError("Do not find address tag.")
        # Return an Address object
        return address.Address.new_from_element(address_node)

    def reset_address(self, attributes):
        """
        Remove old address element if it is exists.
        Then Create a new one with attributes dictionary.
        """
        try:
            addr_type = attributes.pop('type')
        except (KeyError, AttributeError):
            raise xcepts.LibvirtXMLError("type attribute is manditory for "
                                         "Address class.")
        addr = address.Address(addr_type)
        xtfroot = addr.xmltreefile.getroot()
        for key, value in attributes.items():
            xtfroot.set(key, value)
        # Create node according attributes successfully.Deleting old one...
        self.del_address()
        # Update address to disk element
        droot = self.xmltreefile.getroot()
        droot.append(xtfroot)
        self.xmltreefile.write()

    def update_address(self, attributes):
        """Update address attributes according provided attributes dict"""
        try:
            addr = self.get_address()
        except xcepts.LibvirtXMLError:
            try:
                addr_type = attributes.pop('type')
            except (KeyError, AttributeError):
                # Not provided, use "pci"
                addr_type = "pci"
            addr = address.Address(addr_type)
        xtfroot = addr.xmltreefile.getroot()
        for key, value in attributes.items():
            xtfroot.set(key, value)
        # Create node according attributes successfully.Deleting old one...
        self.del_address()
        # Update address to disk element
        droot = self.xmltreefile.getroot()
        droot.append(xtfroot)
        self.xmltreefile.write()

    def del_address(self):
        self.xmltreefile.remove_by_xpath("/address")
        self.xmltreefile.write()
