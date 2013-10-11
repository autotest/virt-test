"""
interface device support class(es)

http://libvirt.org/formatdomain.html#elementsNICS
"""

from virttest.libvirt_xml import accessors
from virttest.libvirt_xml.devices import base


class Interface(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('type', 'source',
                                                  'mac_address',
                                                  'bandwidth_inbound',
                                                  'bandwidth_outbound',
                                                  'portgroup')

    def __init__(self, type_name, virsh_instance=base.base.virsh):
        super(Interface, self).__init__(device_tag='interface',
                                        type_name=type_name,
                                        virsh_instance=virsh_instance)
        accessors.XMLAttribute(property_name="type",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='interface',
                               attribute='type')
        accessors.XMLElementDict(property_name="source",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='source')
        accessors.XMLAttribute(property_name="mac_address",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='mac',
                               attribute='address')
        accessors.XMLElementDict(property_name="bandwidth_inbound",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/bandwidth',
                                 tag_name='inbound')
        accessors.XMLElementDict(property_name="bandwidth_outbound",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/bandwidth',
                                 tag_name='outbound')
        accessors.XMLAttribute(property_name="portgroup",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='source',
                               attribute='portgroup')
