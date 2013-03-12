"""
Common base classes for devices
"""

from virttest import virsh
from virttest.libvirt_xml import base, xcepts, accessors

class UntypedDeviceBase(base.LibvirtXMLBase):

    __slots__ = base.LibvirtXMLBase.__slots__ + ('device_tag',)

    def __init__(self, device_tag, virsh_instance=base.virsh):
        super(UntypedDeviceBase, self).__init__(virsh_instance)
        # Just a regular dictionary value
        self['device_tag'] = device_tag
        # setup bare-bones XML
        self.xml = u"<%s/>" % device_tag


    @staticmethod
    def new_from_element(element):
        # Subclasses required to override this
        raise NotImplimentedError


class TypedDeviceBase(UntypedDeviceBase):

    __slots__ = UntypedDeviceBase.__slots__ + ('type_name',)

    def __init__(self, device_tag, type_name, virsh_instance=base.virsh):
        # generate getter, setter, deleter for 'type_name' property
        accessors.XMLAttribute('type_name', self,
                               # each device is it's own XML "document"
                               # because python 2.6 ElementPath is broken
                               parent_xpath='/',
                               tag_name=device_tag,
                               attribute='type')
        super(TypedDeviceBase, self).__init__(device_tag, virsh_instance)
        self.type_name = type_name
