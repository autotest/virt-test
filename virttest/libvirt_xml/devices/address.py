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

    _address_slots = tuple(
        # unroll all attributes from all tuples in all ADDR_ATTRS
        set([attr for tup in ADDR_ATTRS.values() for attr in tup])
    )

    # Accessors will limit property access based on type_name
    # but make XML modification easy with private _type_name property
    __slots__ = base.TypedDeviceBase.__slots__ + ('_type_name',
                                                 ) + _address_slots


    def __init__(self, virsh_instance=base.base.virsh):
        # type_name not known, avoid accessor in base.TypedDeviceBase
        super(base.TypedDeviceBase, self).__init__(device_tag='address',
                                                 virsh_instance=virsh_instance)
        # Private _type_name accessors do the actual XML modification
        accessors.XMLAttribute('_type_name', self,
                               parent_xpath='/',
                               tag_name='address',
                               attribute='type')
        # Super-class 'type_name' property overridden to handle dynamic
        # accessor methods


    @classmethod
    def new_from_dict(cls, properties, virsh_instance=base.base.virsh):
        instance = cls(virsh_instance=virsh_instance)
        # self.type defines other valid properties
        setattr(self, 'type_name', properties['type_name'])
        # There is no harm in setting type twice
        for key, value in properties.items():
            setattr(instance, key, value)
        return instance


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.base.virsh):
        # instance.set_type_name will validate type_name value
        type_name = element.get('type', None)
        instance = cls(virsh_instance=virsh_instance)
        instance.type_name = type_name
        return instance.from_element(element)


    @classmethod
    def slot_operations(cls):
        for operation in ('get_', 'set_', 'del_'):
            for slot in cls._address_slots:
                    yield (operation, slot)


    @staticmethod
    def type_can_have(type_name, addr_attr):
        return addr_attr in ADDR_ATTRS[type_name]


    def get_type_name(self):
        # Call private accessor to retrieve value from XML
        return self._type_name


    def set_type_name(self, value):
        # Only operate if type is set and is different from value
        if self.has_key('_type_name') and self._type_name == value:
            return # No action needed
        if value not in ADDR_ATTRS.keys():
            raise xcepts.LibvirtXMLError('Address type %s not in %s' % (
                                         value, ADDR_ATTRS.keys()))
        # call del_type_name() accessor to clear dynamic property accessors
        del self.type_name
        # accessors won't overwrite existing, must delete manually
        for operation, slot in self.slot_operations():
            self.super_del(operation + slot)
        # Re-define type-specific property accessors for new type_name
        for slot in self._address_slots:
            # Only create accessors valid for this type_name
            if not self.type_can_have(value, slot):
                # Any access will raise LibvirtXMLError
                forbidden=['get', 'set', 'del']
            else:
                # Any access will modify XML
                forbidden=[]
            # Define get_, set_, del_ accessors based on type_name
            accessors.XMLAttribute(property_name=slot,
                                   libvirtxml=self,
                                   forbidden=forbidden,
                                   parent_xpath='/',
                                   tag_name = 'address',
                                   attribute=slot)
        # Modify XML
        self._type_name = value


    def del_type_name(self):
        # Make all accessors raise LibvirtXMLError
        for operation, slot in self.slot_operations():
            try:
                # Call del accessor if there is one to modify XML
                delattr(self, slot)
            except (KeyError, AttributeError):
                pass # accessor method wasn't relevant to type_name
            # Remove existing accessor method
            try:
                self.super_del(operation + slot)
            except (KeyError, AttributeError):
                pass # type_name was never set
        # Modify type_name XML
        del self._type_name
        # Define forbidden accessors for all properties
        for slot in self._address_slots:
            accessors.XMLAttribute(property_name=slot,
                                   libvirtxml=self,
                                   forbidden=['get', 'set', 'del'],
                                   parent_xpath='/', # below <devices>
                                   attribute=slot)

