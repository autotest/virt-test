"""
http://libvirt.org/formatdomain.html#elementsAddress
"""

from virttest.libvirt_xml import accessors, xcepts
from virttest.libvirt_xml.devices import base

# Valid properties/slots for each address sub-type.
# N/B: No value should clash w/ class attributes, inherited or defined here!
ADDR_ATTRS = {
    'pci':('domain', 'bus', 'slot', 'function', 'multifunction',),
    'drive':('controller', 'bus', 'target', 'unit',),
    'virtio-serial':('controller', 'bus', 'slot',),
    'ccid':('bus', 'slot',),
    'usb':('bus', 'port',),
    'spapr-vio':('reg', ),
    'ccw':('cssid', 'ssid', 'devno')
}

class Address(base.TypedDeviceBase):

    # Accessors will limit property access based on type_name
    # but make XML modification easy with private _type_name property
    __slots__ = base.TypedDeviceBase.__slots__ + ('_type_name',) + tuple(
        # unroll all attributes from all tuples in all ADDR_ATTRS
        [attr for tup in ADDR_ATTRS.values() for attr in tup])


    def __init__(self, virsh_instance=base.base.virsh):
        # type_name not known, avoid accessor in base.TypedDeviceBase
        super(base.TypedDeviceBase, self).__init__(device_tag='address',
                                                 virsh_instance=virsh_instance)
        # Private _type_name accessors
        accessors.XMLAttribute('_type_name', self,
                               parent_xpath='/',
                               tag_name='address',
                               attribute='type')


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.base.virsh):
        # instance.set_type_name will validate type_name value
        type_name = element.get('type', None)
        instance = cls(virsh_instance=virsh_instance)
        instance.type_name = type_name
        return instance.from_element(element)


    @classmethod
    def address_slots(cls):
        for slot in cls.__slots__:
            # Not responsible for base-class defined slots
            if slot in base.TypedDeviceBase.__slots__:
                continue
            else:
                yield slot


    @classmethod
    def slot_operations(cls):
        for operation in ('get_', 'set_', 'del_'):
            for slot in cls.address_slots():
                yield (operation, slot)


    @staticmethod
    def type_can_have(type_name, addr_attr):
        return addr_attr in ADDR_ATTRS[type_name]


    def get_type_name(self):
        # Call private accessor to modify XML
        return self._type_name


    def set_type_name(self, value):
        if value not in ADDR_ATTRS.keys():
            raise xcepts.LibvirtXMLError('Address type %s not in %s' % (
                                         value, ADDR_ATTRS.keys()))
        # call del_type_name()
        del self.type_name
        # Re-define accessors for new type_name
        for slot in self.address_slots():
            # Only create accessors valid for this type_name
            if not self.type_can_have(value, slot):
                forbidden=['get', 'set', 'del']
            else:
                forbidden=[]
            # Define get_, set_, del_ accessors based on type_name
            accessors.XMLAttribute(property_name=slot,
                                   libvirtxml=self,
                                   forbidden=forbidden,
                                   parent_xpath='/', # below <devices>
                                   attribute=slot)
        # Modify XML
        self._type_name = value


    def del_type_name(self):
        # Remove all accessors defined here, just to be safe
        for operation, slot in self.slot_operations():
            try:
                # Call del accessor if there is one
                delattr(self, operation + slot)
                # Remove accessor
                self.super_del(operation + slot)
            except (KeyError, AttributeError):
                pass # accessor method wasn't relevant to type_name
        # Modify XML
        del self._type_name

