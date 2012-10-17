"""
Intermediate module for working with XML-related virsh functions/methods.

All classes defined here should inherit from LibvirtXMLBase and utilize
the utils_misc.PropCanBase property-like interface to manipulate XML
directly via the XMLTreeFile exposed from the 'xml' property.

The intention of this module is to hide the details of working with XML
and the virsh module from test code.  All classes defined here should
inherit from LibvirtXMLBase and utilize the property-like interface
provided by utils_misc.PropCanBase to manipulate XML from the
'xml' property.

All properties defined in __slots__ are intended for public manipulation.
External calling of accessor methods isn't forbidden, but discouraged.
Internally, accessor methods should always use dict_get() and dict_set()
to manipulate other properties (otherwise infinite recursion can occur).

Errors originating beneath this module (e.g. w/in virsh or libvirt_vm)
should not be caught (so caller can test for them).  Errors detected
within this module should raise LibvirtXMLError or a subclass.

Please refer to the xml_utils module documentation for more information
on working with XMLTreeFile instances.  Please see the virsh and utils_misc
modules for information on working with Virsh and PropCanBase classes.
"""
from virttest import virsh, utils_misc, xml_utils


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

    __slots__ = ('xml',)

    # Not intended to be accessed outside this module, only from subclasses.
    __virsh__ = None

    def __init__(self, persistent=False, virsh_dargs=None):
        """
        Initialize instance's internal virsh interface from virsh_dargs

        @param: persistent: Use persistent virsh connection for this instance
        @param: virsh_dargs: virsh module Virsh class dargs API keywords
        """

        if virsh_dargs is None:
            virsh_dargs = {} # avoid additional conditionals below
        if persistent:
            self.super_set('__virsh__', virsh.VirshPersistent(**virsh_dargs))
        else:
            self.super_set('__virsh__', virsh.Virsh(**virsh_dargs))
        # Don't define any initial property values
        super(LibvirtXMLBase, self).__init__()


    def set_xml(self, value):
        """
        Accessor method for 'xml' property to load using xml_utils.XMLTreeFile
        """
        # Always check to see if a "set" accessor is being called from __init__
        if not self.super_get('INITIALIZED'):
            self.dict_set('xml', value)
        else:
            try:
                if self.dict_get('xml') is not None:
                    del self['xml'] # clean up old temporary files
            except KeyError:
                pass # Allow other exceptions through
            # value could be filename or a string full of XML
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
        # help keep line length short, __virsh__ is not a property
        virsh_instance = self.super_get('__virsh__')
        virsh_class = type(virsh_instance)
        # Copy should reuse session_id for VirshPersistant
        virsh_dargs = virsh_instance.copy()
        if issubclass(virsh_class, virsh.VirshPersistent):
            the_copy = self.__class__(True, virsh_dargs)
        else:
            the_copy = self.__class__(False, virsh_dargs)
        # call accessor methods and keep pylint happy
        the_copy.__setitem__('xml', self.xml)
        return the_copy


class LibvirtXML(LibvirtXMLBase):
    """
    Handler of libvirt capabilities and nonspecific item operations.
    """


    #TODO: Add more __slots__ and accessors to get some useful stats
    # e.g. guest_count, arch, uuid, cpu_count, etc.
    __slots__ = LibvirtXMLBase.__slots__ + ('os_arch_machine_map',)

    def __init__(self, persistent=False, **virsh_dargs):
        super(LibvirtXML, self).__init__(persistent=False, **virsh_dargs)
        # calls set_xml accessor method
        self.__setitem__('xml', self.__virsh__.capabilities())
        # Don't call set_os_arch_machine_map()
        self.dict_set('os_arch_machine_map', None)


    @staticmethod
    def __readonly__(name):
        raise LibvirtXMLError('LibvirtXML instances property %s is read-only'
                              % name)


    def get_os_arch_machine_map(self):
        """
        Accessor method for os_arch_machine_dict property
        """
        oamm = {} #Schema {<os_type>:{<arch name>:[<machine>, ...]}}
        xmltreefile = self.dict_get('xml')
        for guest in xmltreefile.findall('guest'):
            os_type_name = guest.find('os_type').text
            # Multiple guest definitions can share same os_type (e.g. hvm, pvm)
            amm = oamm.get(os_type_name, {})
            for arch in guest.findall('arch'):
                arch_name = arch.get('name')
                mm = amm.get(arch_name, [])
                for machine in arch.findall('machine'):
                    machine_text = machine.text
                    # Don't add duplicate entries
                    if not mm.count(machine_text):
                        mm.append(machine_text)
                amm[arch_name] = mm
            oamm[os_type_name] = amm
        return oamm


    def set_os_arch_machine_dict(self, value):
        self.__readonly__('os_arch_machine_dict')


    def del_os_arch_machine_dict(self):
        self.__readonly__('os_arch_machine_dict')


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
        # Always check to see if accessor is being called from __init__
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
        # Always check to see if accessor is being called from __init__
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
                                        xmltreefile.get_root(), "uuid")
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
        # Allow any exceptions to propigate up
        self.__virsh__.remove_domain(self.vm_name)


    def define(self):
        """Define VM with virsh from this instance"""
        # Allow any exceptions to propigate up
        self.__virsh__.define(self.xml)


    def new_from_dumpxml(self, vm_name):
        """
        Load XML info from virsh dumpxml vm_name command
        """
        # Calls set_xml accessor method and keeps pylint happy
        self.__setitem__('xml', self.__virsh__.dumpxml(vm_name))


    #TODO: Add function to create from xml_utils.TemplateXML()
    # def new_from_template(...)
