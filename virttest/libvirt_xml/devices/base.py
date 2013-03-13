"""
Common base classes for devices
"""

from StringIO import StringIO
from virttest import xml_utils
from virttest.libvirt_xml import base, xcepts, accessors

class UntypedDeviceBase(base.LibvirtXMLBase):

    __slots__ = base.LibvirtXMLBase.__slots__ + ('device_tag',)

    # Subclasses are expected to hide device_tag
    def __init__(self, device_tag, virsh_instance=base.virsh):
        super(UntypedDeviceBase, self).__init__(virsh_instance)
        # Just a regular dictionary value
        self['device_tag'] = device_tag
        # setup bare-bones XML
        self.xml = u"<%s/>" % device_tag


    def valid_element(self, element):
        element_type = type(element)
        # element class is protected by generator
        element_class = type(xml_utils.ElementTree.Element('foobar'))
        correct_class = issubclass(element_type, element_class)
        correct_tag = self.device_tag == element.tag
        is_element = xml_utils.ElementTree.iselement(element)
        for is_true in (correct_class, correct_tag, is_element):
            if not is_true:
                return False
        return True


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.virsh):
        instance = cls(virsh_instance=virsh_instance)
        if instance.valid_element(element):
            # XMLTreeFile only supports element trees
            et = xml_utils.ElementTree.ElementTree(element)
            # ET only writes to open file-like objects
            xmlstr = StringIO()
            # Need element tree string value to initialize LibvirtXMLBase.xml
            et.write(xmlstr, xml_utils.ENCODING)
            instance.xml = xmlstr.getvalue()
            return instance
        else:
            raise xcepts.LibvirtXMLError("Invalid element '%s' for device "
                                         "class '%s'"
                                         % (str(element), # don't presume type
                                            str(cls)))


class TypedDeviceBase(UntypedDeviceBase):

    __slots__ = UntypedDeviceBase.__slots__ + ('type_name',)

    # Subclasses are expected to hide device_tag and type_name
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
