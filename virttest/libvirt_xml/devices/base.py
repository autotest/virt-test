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


    def from_element(self, element):
        class_name = self.__class__.__name__
        if element.tag != class_name.lower():
            raise xcepts.LibvirtXMLError('Refusing to create %s instance'
                                         'from %s tagged element'
                                         % (class_name, element.tag))
        # XMLTreeFile only supports element trees
        et = xml_utils.ElementTree.ElementTree(element)
        # ET only writes to open file-like objects
        xmlstr = StringIO()
        # Need element tree string value to initialize LibvirtXMLBase.xml
        et.write(xmlstr, xml_utils.ENCODING)
        self.xml = xmlstr.getvalue()


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.virsh):
        # subclasses __init__ only takes virsh_instance parameter
        instance = cls(virsh_instance=virsh_instance)
        instance.from_element(element)
        return instance


class TypedDeviceBase(UntypedDeviceBase):

    __slots__ = UntypedDeviceBase.__slots__ + ('type_name',)

    # Subclasses are expected to hide device_tag
    def __init__(self, device_tag, type_name, virsh_instance=base.virsh):
        # generate getter, setter, deleter for 'type_name' property
        accessors.XMLAttribute('type_name', self,
                               # each device is it's own XML "document"
                               # because python 2.6 ElementPath is broken
                               parent_xpath='/',
                               tag_name=device_tag,
                               attribute='type')
        super(TypedDeviceBase, self).__init__(device_tag, virsh_instance)
        # Calls accessor to modify xml
        self.type_name = type_name


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.virsh):
        device_tag = element.tag
        type_name = element.get('type', None)
        instance = cls(type_name=type_name,
                       virsh_instance=virsh_instance)
        instance.from_element(element)
        return instance
