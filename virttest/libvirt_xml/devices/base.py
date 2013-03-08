"""
Common base classes for devices
"""

from virttest import virsh
from libvirt_xml import base, xcepts, accessors

class UntypedDeviceBase(base.LibvirtXMLBase):

    __slots__ = base.LibvirtXMLBase.__slots__

    def __init__(self, virsh_instance=virsh, device_tag):
        super(UntypedDeviceBase, self).__init__(virsh_instance)
        self.xml = u"<%s/>" % device_tag


class TypedDeviceBase(UntypedDeviceBase):

    __slots__ = UntypedDeviceBase.__slots__ + ('type_name')

    def __init__(self, virsh_instance=virsh, device_tag, type_name):
        # generate getter, setter, deleter for 'type_name' property
        accessors.XMLAttribute('type_name', self,
                               # each device is it's own XML "document"
                               # because python 2.6 ElementPath is broken
                               parent_xpath='/',
                               tag_name=device_tag,
                               attribute='type')
        super(TypedDeviceBase, self).__init__(virsh_instance, device_tag)
