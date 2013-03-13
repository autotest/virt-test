"""
Classes to support XML for serial devices
http://libvirt.org/formatdomain.html#elementCharSerial
"""

from virttest.libvirt_xml.devices import base


class Serial(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('source_path', 'target_port')

    def __init__(self, virsh_instance=base.virsh):
        base.accessors.XMLAttribute('source_path', self, parent_xpath='/',
                                    tag_name='source', attribute='path')
        base.accessors.XMLAttribute('target_port', self, parent_xpath='/',
                                    tag_name='target', attribute='port')
        #TODO: Support 'target_type' and 'target_address'
        #      These need 'address' device/module added
        super(Serial, self).__init__(device_tag='serial', type_name='pty',
                                    virsh_instance=virsh_instance)
