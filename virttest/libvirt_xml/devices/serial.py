"""
Classes to support XML for serial devices
http://libvirt.org/formatdomain.html#elementCharSerial
"""

from virttest.libvirt_xml.devices import base
from virttest import element_tree


class SerialBase(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('source_path', 'target_port')

    def __init__(self, virsh_instance=base.virsh):
        base.accessors.XMLAttribute('source_path', self, parent_xpath='/',
                                    tag_name='source', attribute='path')
        base.accessors.XMLAttribute('target_port', self, parent_xpath='/',
                                    tag_name='target', attribute='port')
        #TODO: Support 'target_type' and 'target_address'
        #      These need 'address' device/module added
        super(SerialBase, self).__init__(virsh_instance, 'serial', 'pty')


class Serial(SerialBase):

    __slots__ = SerialBase.__slots__

    def __init__(self, virsh_instance=base.virsh, serial_type='pty'):
        super(Serial, self).__init__(virsh_instance)
        self.xml = u"<serial type='%s'></serial>" % serial_type


    @staticmethod
    def new_from_element(element, virsh_instance=base.virsh):
        # Typed device
        serial_xml = Serial(virsh_instance=virsh_instance)
        serial_xml['xml'] = str(element) # retrieve XML string
        return serial_xml
