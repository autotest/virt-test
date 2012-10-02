"""
Intermediate module for working with XML-related virsh functions/methods.

All classes defined here should inherrit from LibvirtXMLBase and utilize
the XMLTreeFile interface to recover external source XML in case internal
errors are detected.  Errors originating within this module should raise
LibvirtXMLError or a subclass of this exception.  Pleae refer to the
xml_utils module documentation for more information on working with
XMLTreeFile instances.  Please see the virsh and utils_misc modules for
information on working with Virsh and especially PropCanBase classes.
"""

import uuid
from autotest.client.shared import xml_utils
import utils_misc, virsh


class LibvirtXMLError(Exception):
    """
    Error originating within libvirt_xml module
    """

    def __init__(self, details=''):
        self.details = details
        super(LibvirtXMLError, self).__init__()


    def __str__(self):
        return str(self.details)


class LibvirtXMLBase(utils_misc.PropCanBase):
    """
    Base class for common attributes/methods applying to all sub-classes
    """

    __slots__ = ('xml', 'virsh')

    def __init__(self, persistent=False, virsh_dargs=None):
        """
        Initialize instance's internal virsh interface from virsh_dargs

        @param: persistent: Use persistent virsh connection for this instance
        @param: virsh_dargs: virsh module Virsh class dargs API keywords
        """

        if virsh_dargs is None:
            virsh_dargs = {} # avoid additional conditionals below
        # Assume special-handling of all slots, initialize to None
        init_dict = dict([(key, None) for key in self.__slots__])
        if persistent:
            init_dict['virsh'] = virsh.VirshPersistent(**virsh_dargs)
        else:
            init_dict['virsh'] = virsh.Virsh(**virsh_dargs)
        super(LibvirtXMLBase, self).__init__(**init_dict)


    def set_xml(self, value):
        """
        Accessor method for 'xml' property to load using xml_utils.XMLTreeFile
        """
        # Allways check to see if a "set" accessor is being called from __init__
        if not self.super_get('INITIALIZED'):
            self.dict_set('xml', value)
        else:
            if self.dict_get('xml') is not None:
                del self['xml'] # clean up old temporary files
            # value could be filename or a string full of XML
            self.dict_set('xml', xml_utils.XMLTreeFile(value))


    def get_xml(self):
        """
        Accessor method for 'xml' property returns xmlTreeFile backup filename
        """

        if persistent:
            super(LibvirtXMLBase, self).__init__(
                    virsh=virsh.VirshPersistent(**virsh_dargs))
        else:
            super(LibvirtXMLBase, self).__init__(
                    virsh=virsh.Virsh(**virsh_dargs))
        self.dict_set('xml', None)


    def set_xml(self, value):
        """
        Accessor method for 'xml' property to load using xml_utils.XMLTreeFile
        """
        if self.dict_get('xml') is not None:
            del self['xml'] # clean up old temporary files
        self.dict_set('xml', xml_utils.XMLTreeFile(value))


    def get_xml(self):
        """
        Accessor method for 'xml' property returns xmlTreeFile backup filename
        """
        try:
            # don't call get_xml() recursivly
            xml = self.dict_get('xml')
            if xml == None:
                raise KeyError
        except (KeyError, AttributeError):
            raise LibvirtXMLError("No xml data has been loaded")
        return xml.name # The filename


    def copy(self):
        """
        Returns a copy of instance not sharing any references or modifications
        """
        if issubclass(type(self.virsh), virsh.VirshPersistent):
            the_copy = LibvirtXMLBase(persistent=True, virsh_dargs=self.virsh.PROPERTIES)
        else:
            the_copy = LibvirtXMLBase(persistent=False, virsh_dargs=self.virsh.PROPERTIES)
        # get_xml returns filename, the_copy creates backup
        the_copy.set_xml(self.xml)
        return the_copy


class LibvirtXML(LibvirtXMLBase):
    """
    Handler of libvirt capabilities and nonspecific item operations.
    """

    #TODO: Add __slots__ and accessors to get some useful stats
    __slots__ = LibvirtXMLBase.__slots__ + tuple()

    def __init__(self, persistent=False, **virsh_dargs):
        super(LibvirtXML, self).__init__(persistent=False, **virsh_dargs)
        # calls set_xml accessor method
        self.xml = self.virsh.capabilities()


class VMXMLBase(LibvirtXMLBase):
    """
    Accessor methods for VMXML class
    """

    __slots__ = LibvirtXMLBase.__slots__ + ('vm_name', 'uuid',)


    def get_vm_name(self):
        """
        Accessor method for 'name' property to lookup w/in XML
        """
        # Let get_xml raise a LibvirtXMLError as needed
        xmltreefile = self.dict_get('xml')
        return xmltreefile.find('name').text


    def set_vm_name(self, value):
        """
        Accessor method for 'name' property
        """
        # Allways check to see if accessor is being called from __init__
        if not self.super_get('INITIALIZED'):
            self.dict_set('name', value) # Assuming value is None
        else:
            try:
                xmltreefile = self.dict_get('xml')
                xmltreefile.find('name').text = value
            except AttributeError: # None.text
                raise LibvirtXMLError("Invalid XML: Contain no <name> element")
            xmltreefile.write()


    def del_vm_name(self):
        """
        Raise LibVirtXMLError because name is a required element
        """
        # Raise different exception if xml wasn't loaded
        if self.haskey('xml'):
            pass
        raise LibvirtXMLError("name can't be deleted, it's a required element")


    def get_uuid(self):
        """
        Return VM's uuid or None if not set
        """
        xmltreefile = self.dict_get('xml')
        return xmltreefile.find('uuid').text


    def set_uuid(self, value):
        """
        Set or create a new uuid element for a VM
        """
        # Allways check to see if accessor is being called from __init__
        if not self.super_get('INITIALIZED'):
            self.dict_set('name', value) # Assuming value is None
        else:
            xmltreefile = self.dict_get('xml')
            if value is None:
                xmltreefile.remove_by_xpath('uuid')
            else:
                # uuid module added in python 2.5, no easy way to validate value
                try:
                    xmltreefile.find('uuid').text = value
                except AttributeError: # uuid element not found
                    # Documented preferred way to insert a new element
                    newone = xml_utils.ElementTree.SubElement(
                                        xmltreefile.getroot(), "uuid")
                    newone.text = value
            xmltreefile.write()


    def del_uuid(self):
        """
        Remove the uuid from a VM so libvirt can generate a new one
        """
        xmltreefile = self.dict_get('xml')
        try:
            xmltreefile.remove_by_xpath('uuid')
            xmltreefile.write()
        except AssertionError:
            pass # element not found, nothing to delete


class VMXML(VMXMLBase):
    """
    Manipulators of a VM through it's XML definition
    """

    __slots__ = VMXMLBase.__slots__


    def undefine(self):
        """Undefine this VM with libvirt retaining XML in instance"""
        if not self.virsh.remove_domain(self.vm_name):
            raise LibvirtXMLError("Virsh reported unsuccessful domain remove")


    def define(self):
        """Define VM with virsh from this instance"""
        if not self.virsh.define(self.xml):
            raise LibvirtXMLError("Virsh reported unsuccessful domain define")


    def new_from_dumpxml(self, vm_name):
        """
        Load XML info from virsh dumpxml vm_name command
        """
        # Calls set_XML accessor method
        self.set_xml(self.virsh.dumpxml(vm_name))


    def define(self):
        """Define VM with virsh from this instance"""
        self.virsh.define(self.xml)


    def new_from_dumpxml(self, vm_name):
        """
        Load XML info from virsh dumpxml vm_name command
        """
        # Calls set_XML accessor method
        self.set_xml(self.virsh.dumpxml(vm_name))


    #TODO: Add function to create from xml_utils.TemplateXML()
    # def new_from_template(...)

