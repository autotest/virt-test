"""
Common base classes for devices
"""

import warnings
from StringIO import StringIO
from virttest import xml_utils
from virttest.libvirt_xml import base, xcepts, accessors

class UntypedDeviceBase(base.LibvirtXMLBase):
    """
    Base class implementing common functions for all device XML w/o a type attr.
    """

    __slots__ = base.LibvirtXMLBase.__slots__ + ('device_tag',)

    # Subclasses are expected to hide device_tag
    def __init__(self, device_tag, virsh_instance=base.virsh):
        """
        Initialize untyped device instance's basic XML with device_tag
        """
        super(UntypedDeviceBase, self).__init__(virsh_instance=virsh_instance)
        # Just a regular dictionary value
        # (Using a property to change element tag won't work)
        self['device_tag'] = device_tag
        # setup bare-bones XML
        self.xml = u"<%s/>" % device_tag


    def from_element(self, element):
        """
        Stateful component to helper method for new_from_element.
        """
        class_name = self.__class__.__name__
        if element.tag != class_name.lower():
            raise xcepts.LibvirtXMLError('Refusing to create %s instance'
                                         'from %s tagged element'
                                         % (class_name, element.tag))
        # XMLTreeFile only supports element trees
        etree = xml_utils.ElementTree.ElementTree(element)
        # ET only writes to open file-like objects
        xmlstr = StringIO()
        # Need element tree string value to initialize LibvirtXMLBase.xml
        etree.write(xmlstr, xml_utils.ENCODING)
        # Create a new XMLTreeFile object based on string input
        self.xml = xmlstr.getvalue()


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.virsh):
        """
        Create a new device XML instance from an single ElementTree element
        """
        # subclasses __init__ only takes virsh_instance parameter
        instance = cls(virsh_instance=virsh_instance)
        instance.from_element(element)
        return instance


    @classmethod
    def new_from_dict(cls, properties, virsh_instance=base.virsh):
        """
        Create a new device XML instance from a dict-like object
        """
        instance = cls(virsh_instance=virsh_instance)
        for key, value in properties.items():
            setattr(instance, key, value)
        return instance


class TypedDeviceBase(UntypedDeviceBase):
    """
    Base class implementing common functions for all device XML w/o a type attr.
    """

    __slots__ = UntypedDeviceBase.__slots__ + ('type_name',)

    # Subclasses are expected to hide device_tag
    def __init__(self, device_tag, type_name, virsh_instance=base.virsh):
        """
        Initialize Typed device instance's basic XML with type_name & device_tag
        """
        # generate getter, setter, deleter for 'type_name' property
        accessors.XMLAttribute('type_name', self,
                               # each device is it's own XML "document"
                               # because python 2.6 ElementPath is broken
                               parent_xpath='/',
                               tag_name=device_tag,
                               attribute='type')
        super(TypedDeviceBase, self).__init__(device_tag=device_tag,
                                              virsh_instance=virsh_instance)
        # Calls accessor to modify xml
        self.type_name = type_name


    @classmethod
    def new_from_element(cls, element, virsh_instance=base.virsh):
        """
        Hides type_name from superclass new_from_element().
        """
        type_name = element.get('type', None)
        # subclasses must hide device_tag parameter
        instance = cls(type_name=type_name,
                       virsh_instance=virsh_instance)
        instance.from_element(element)
        return instance



class StubDeviceMeta(type):
    """
    Metaclass for generating stub Device classes where not fully implemented yet
    """

    def __init__(cls, name, bases, dct):
        """
        Configuration for new class
        """

        # Keep pylint happy
        dct = dict(dct)

        # Call type() to setup new class
        super(StubDeviceMeta, cls).__init__(name, bases, dct)

        # Needed for __init__'s default argument value
        if not hasattr(cls, '_device_tag'):
            raise ValueError("Class %s requires a _device_tag attribute" % name)

        # Same message for both TypedDeviceBase & UntypedDeviceBase subclasses
        message = ("Stub device XML for %s class. Only implements "
                   "minimal interface and is likely to change in "
                   "future versions.  This warning will only be issued "
                   "once." % name)

        # Create the proper init function for subclass type
        if TypedDeviceBase in bases:
            if not hasattr(cls, '_def_type_name'):
                raise ValueError("TypedDevice sub-Class %s must define a "
                                 "_def_type_name attribute" % name)
            # __init__ for typed devices
            def stub_init(self, type_name=getattr(cls, '_def_type_name'),
                          virsh_instance=base.virsh):
                """
                Initialize stub typed device instance
                """
                if not cls.__warning_issued__:
                    # The instances created class variable
                    setattr(cls, '__warning_issued__', True) # make pylint happy
                    warnings.warn(message, FutureWarning, stacklevel=2)
                # Call created class "cls" base class's __init__ method
                # Pylint E1003 warning on this is _wrong_
                super(cls, self).__init__(device_tag=getattr(cls,
                                                             '_device_tag'),
                                          type_name=type_name,
                                          virsh_instance=virsh_instance)
        elif UntypedDeviceBase in bases:
            # __init__ for untyped devices
            def stub_init(self, virsh_instance=base.virsh):
                """
                Initialize stub un-typed device instance
                """
                if not cls.__warning_issued__:
                    setattr(cls, '__warning_issued__', True) # make pylint happy
                    warnings.warn(message, FutureWarning, stacklevel=2)
                # Call created class "cls" base class's __init__ method
                # Pylint E1003 warning on this is _wrong_
                super(cls, self).__init__(device_tag=getattr(cls,
                                                             '_device_tag'),
                                          virsh_instance=virsh_instance)
        else:
            # unexpected usage
            raise TypeError("Class %s is not a subclass of TypedDeviceBase or "
                            "UntypedDeviceBase")

        setattr(cls, '__warning_issued__', False)
        setattr(cls, '__init__', stub_init)
