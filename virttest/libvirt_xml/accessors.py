"""
Specializations of base.AccessorBase for particular XML manipulation types
"""

import logging
from virttest import xml_utils
from virttest.propcan import PropCanBase
from virttest.libvirt_xml import xcepts, base


def type_check(name, thing, expected):
    """
    Check that thing is expected subclass or instance, raise ValueError if not
    """
    is_a = type(thing)
    is_a_name = str(is_a)
    expected_string = str(expected)
    try:
        it_is = issubclass(thing, expected)
    except TypeError:
        it_is = isinstance(thing, expected)
    if not it_is:
        raise ValueError("%s is not a %s, it is a %s"
                         % (name, expected_string, is_a_name))


def add_to_slots(*args):
    """
    Return list of AccessorBase.__slots__ + args
    """
    for slot in args:
        type_check('slot name', slot, str)
    return AccessorBase.__slots__ + args


class AccessorBase(PropCanBase):
    """
    Base class for a callable operating on a LibvirtXMLBase subclass instance
    """

    # Gets AccessorGeneratorBase subclass's required_accessor_data_keys added
    __slots__ = ('operation', 'property_name', 'libvirtxml')

    def __init__(self, operation, property_name, libvirtxml, **dargs):
        """
        Initialize accessor to operate on lvxml with accessor_data for property

        @param: operation: Debug String for 'Getter', 'Setter', or 'Delter'
        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        @param: **dargs: Additional __slots__ values to set
        """
        type_check('Parameter property_name', property_name, str)
        type_check('Operation attribute', operation, str)
        type_check('__slots__ attribute', self.__slots__, tuple)
        type_check('Parameter libvirtxml', libvirtxml, base.LibvirtXMLBase)

        super(AccessorBase, self).__init__()

        self.dict_set('operation', operation)
        self.dict_set('property_name', property_name)
        self.dict_set('libvirtxml', libvirtxml)
        for slot in self.__slots__:
            if slot in AccessorBase.__slots__:
                continue # already checked these
            type_check('slot', slot, str)
            value = dargs.get(slot, None)
            type_check('value', value, str)
            self.dict_set(slot, value)


    # Subclass expected to override this and specify parameters
    __call__ = NotImplementedError


    def __repr__(self):
        return ("%s's %s for %s with %s"
                % (self.libvirtxml.__class__.__name__, self.operation,
                   self.property_name, str(dict(self))) )


    def xmltreefile(self):
        """
        Retrieve xmltreefile instance from libvirtxml instance
        """
        return self.libvirtxml.dict_get('xml')


    def element_by_parent(self, parent_xpath, tag_name, create=True):
        """
        Retrieve/create an element instance at parent_xpath/tag_name
        """
        type_check('parent_xpath', parent_xpath, str)
        type_check('tag_name', tag_name, str)
        parent_element = self.xmltreefile().find(parent_xpath)
        if (parent_element == self.xmltreefile().getroot() and
                                    parent_element.tag == tag_name):
            return parent_element
        excpt_str = ('Exception thrown from %s for property "%s" while'
                     ' looking for element tag "%s", on parent at xpath'
                     ' "%s", in XML\n%s\n' % ( self.operation,
                     self.property_name, tag_name, parent_xpath,
                     str(self.xmltreefile())))
        if parent_element is None:
            raise xcepts.LibvirtXMLAccessorError(excpt_str)
        try:
            element = parent_element.find(tag_name)
        except:
            logging.error(excpt_str)
            raise
        if element is None:
            if create: # Create the element
                element = xml_utils.ElementTree.SubElement(parent_element,
                                                           tag_name)
            else: # create == False
                raise xcepts.LibvirtXMLNotFoundError('Error in %s for property '
                                                 '"%s", element tag "%s" not '
                                                 'found on parent at xpath "%s"'
                                                 ' in XML\n%s\n'
                                                 % (self.operation,
                                                    self.property_name,
                                                    tag_name, parent_xpath,
                                                    str(self.xmltreefile())))
        return element



class ForbiddenBase(AccessorBase):
    """
    Raise LibvirtXMLAccessorError when called w/ or w/o a value arg.
    """

    __slots__ = AccessorBase.__slots__

    def __call__(self, value=None):
        if value:
            raise xcepts.LibvirtXMLForbiddenError("%s %s to '%s' on %s "
                                                  "forbidden"
                                                  % (self.operation,
                                                     self.property_name,
                                                     str(value),
                                                     str(self)))
        else:
            raise xcepts.LibvirtXMLForbiddenError("%s %s on %s "
                                                  "forbidden"
                                                  % (self.operation,
                                                     self.property_name,
                                                     str(self)))


class AccessorGeneratorBase(object):
    """
    Accessor method/class generator for specific property name
    """

    def __init__(self, property_name, libvirtxml, forbidden=None, **dargs):
        """
        Initialize accessor methods, marking operations in forbidden as such

        @param: property_name: Name of the property
        @param: libvirtxml: Instance reference to LibvirtXMLBase subclass
        @param: forbidden: Optional string list of 'get', 'set', and/or 'del'
        @param: **dargs: Specific AccessorGeneratorBase subclass info.
        """
        if forbidden == None:
            forbidden = []
        type_check('forbidden', forbidden, list)
        self.forbidden = forbidden

        type_check('libvirtxml', libvirtxml, base.LibvirtXMLBase)
        self.libvirtxml = libvirtxml

        type_check('property_name', property_name, str)
        self.property_name = property_name

        self.dargs = dargs

        # Lookup all property names possibly needing accessors
        for operation in ('get', 'set', 'del'):
            self.set_if_not_defined(operation)


    def set_if_not_defined(self, operation):
        """
        Setup a callable instance for operation only if not already defined
        """
        # Don't overwrite methods in libvirtxml instance
        if not hasattr(self.libvirtxml, self.accessor_name(operation)):
            if operation not in self.forbidden:
                self.assign_callable(operation, self.make_callable(operation))
            else: # operation is forbidden
                self.assign_callable(operation, self.make_forbidden(operation))


    def accessor_name(self, operation):
        """
        Return instance name for operation, defined by subclass (i.e. 'get_foo')
        """
        return "%s_%s" % (operation, self.property_name)



    @staticmethod
    def callable_name(operation):
        """
        Return class name for operation (i.e. 'Getter'), defined by subclass.
        """
        return operation.capitalize() + 'ter'


    def make_callable(self, operation):
        """
        Return an callable instance for operation
        """
        callable_class = getattr(self, self.callable_name(operation))
        return callable_class(self.callable_name(operation), self.property_name,
                              self.libvirtxml, **self.dargs)


    def make_forbidden(self, operation):
        """
        Return a forbidden callable instance for operation
        """
        return ForbiddenBase(operation, self.property_name, self.libvirtxml)


    def assign_callable(self, operation, callable_inst):
        """
        Set reference on objectified libvirtxml instance to callable_inst
        """
        self.libvirtxml.super_set(self.accessor_name(operation),
                                  callable_inst)


# Implementation of specific accessor generator subclasses follows


class AllForbidden(AccessorGeneratorBase):
    """
    Class of forbidden accessor classes for those undefined on libvirtxml
    """

    def __init__(self, property_name, libvirtxml):
        """
        Create exception raising accessors for those undefined on libvirtxml

        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        """
        super(AllForbidden, self).__init__(property_name=property_name,
                                           libvirtxml=libvirtxml,
                                           forbidden=['get', 'set', 'del'])


class XMLElementText(AccessorGeneratorBase):
    """
    Class of accessor classes operating on element.text
    """

    required_dargs = ('parent_xpath', 'tag_name')

    def __init__(self, property_name, libvirtxml, forbidden=None,
                 parent_xpath=None, tag_name=None):
        """
        Create undefined accessors on libvirt instance

        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        @param: forbidden: Optional list of 'Getter', 'Setter', 'Delter'
        @param: parent_xpath: XPath string of parent element
        @param: tag_name: element tag name to manipulate text attribute on.
        """
        super(XMLElementText, self).__init__(property_name, libvirtxml,
                                             forbidden,
                                             parent_xpath=parent_xpath,
                                             tag_name=tag_name)


    class Getter(AccessorBase):
        """
        Retrieve text on element
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self):
            return self.element_by_parent(self.parent_xpath,
                                          self.tag_name, create=False).text


    class Setter(AccessorBase):
        """
        Set text to value on element
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self, value):
            element = self.element_by_parent(self.parent_xpath,
                                             self.tag_name, create=True)
            element.text = str(value)
            self.xmltreefile().write()


    class Delter(AccessorBase):
        """
        Remove element & text
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self):
            try:
                element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=False)
            except xcepts.LibvirtXMLNotFoundError:
                element = None
            if element:
                self.xmltreefile().remove(element)
                self.xmltreefile().write()


class XMLElementInt(AccessorGeneratorBase):
    """
    Class of accessor classes operating on element.text as an integer
    """

    required_dargs = ('parent_xpath', 'tag_name')

    def __init__(self, property_name, libvirtxml, forbidden=None,
                 parent_xpath=None, tag_name=None):
        """
        Create undefined accessors on libvirt instance

        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        @param: forbidden: Optional list of 'Getter', 'Setter', 'Delter'
        @param: parent_xpath: XPath string of parent element
        @param: tag_name: element tag name to manipulate text attribute on.
        """
        super(XMLElementInt, self).__init__(property_name, libvirtxml,
                                            forbidden,
                                            parent_xpath=parent_xpath,
                                           tag_name=tag_name)


    class Getter(AccessorBase):
        """
        Retrieve text on element and convert to int
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self):
            element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=False)
            return int(element.text)


    class Setter(AccessorBase):
        """
        Set text on element after converting to int then to str
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self, value):
            element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=True)
            value = str(int(value)) # Validates value
            element.text = value
            self.xmltreefile().write()


    Delter = XMLElementText.Delter


class XMLAttribute(AccessorGeneratorBase):
    """
    Class of accessor classes operating on an attribute of an element
    """

    def __init__(self, property_name, libvirtxml, forbidden=None,
                 parent_xpath=None, tag_name=None, attribute=None):
        """
        Create undefined accessors on libvirt instance

        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        @param: forbidden: Optional list of 'Getter', 'Setter', 'Delter'
        @param: parent_xpath: XPath string of parent element
        @param: tag_name: element tag name to manipulate text attribute on.
        @param: attribute: Attribute name to manupulate
        """
        super(XMLAttribute, self).__init__(property_name, libvirtxml,
                                       forbidden, parent_xpath=parent_xpath,
                                       tag_name=tag_name, attribute=attribute)


    class Getter(AccessorBase):
        """
        Get attribute value
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name', 'attribute')

        def __call__(self):
            element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=False)
            return element.get(self.attribute, None)


    class Setter(AccessorBase):
        """
        Set attribute value
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name', 'attribute')

        def __call__(self, value):
            element = self.element_by_parent(self.parent_xpath,
                                             self.tag_name, create=True)
            element.set(self.attribute, str(value))
            self.xmltreefile().write()


    class Delter(AccessorBase):
        """
        Remove attribute
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name', 'attribute')

        def __call__(self):
            element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=False)
            try:
                del element.attrib[self.attribute]
            except KeyError:
                pass # already doesn't exist
            self.xmltreefile().write()


class XMLElementDict(AccessorGeneratorBase):
    """
    Class of accessor classes operating as a dictionary of attributes
    """

    def __init__(self, property_name, libvirtxml, forbidden=None,
                 parent_xpath=None, tag_name=None):
        """
        Create undefined accessors on libvirt instance

        @param: property_name: String name of property (for exception detail)
        @param: libvirtxml: An instance of a LibvirtXMLBase subclass
        @param: forbidden: Optional list of 'Getter', 'Setter', 'Delter'
        @param: parent_xpath: XPath string of parent element
        @param: tag_name: element tag name to manipulate text attribute on.
        """
        super(XMLElementDict, self).__init__(property_name, libvirtxml,
                                              forbidden,
                                              parent_xpath=parent_xpath,
                                              tag_name=tag_name)


    class Getter(AccessorBase):
        """
        Retrieve attributes on element
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self):
            element = self.element_by_parent(self.parent_xpath,
                                                 self.tag_name, create=False)
            return dict(element.items())


    class Setter(AccessorBase):
        """
        Set attributes to value on element
        """

        __slots__ = add_to_slots('parent_xpath', 'tag_name')

        def __call__(self, value):
            type_check(self.property_name + ' value', value, dict)
            element = self.element_by_parent(self.parent_xpath,
                                             self.tag_name, create=True)
            for attr_key, attr_value in value.items():
                element.set(str(attr_key), str(attr_value))
            self.xmltreefile().write()

    # Inheriting from XMLElementText not work right
    Delter = XMLElementText.Delter
