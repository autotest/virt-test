"""
Intermediate module for working with XML-related virsh functions/methods.

The intention of this module is to hide the details of working with XML
from test module code.  Helper methods are all high-level and not
condusive to direct use in error-testing.  However, access to a virsh
instance is available.

All classes defined here should inherit from LibvirtXMLBase and
utilize the property-like interface provided by utils_misc.PropCanBase
to manipulate XML from the 'xml' property. Please refer to the xml_utils
module documentation for more information on working with XMLTreeFile
instances.  Please see the virsh and utils_misc modules for information
on working with Virsh and PropCanBase classes.

All properties defined in __slots__ are intended for test-module
manipulation.  External calling of accessor methods isn't forbidden,
but discouraged. Instead, test modules should use normal reference,
assignment, and delete operations on instance properties as if they
were attributes.  It's up to the test if it uses the dict-like or
instance-attribute interface.

Internally, accessor methods (get_*(), set_*(), & del_*()) should always
use dict_get(), dict_set(), and/or dict_del() to manipulate properties
(otherwise infinite recursion can occur).  In some cases, where class
or instance attributes are needed (ousdie of __slots__) they must
be accessed via the super_set(), super_get(), and/or super_del() methods.
None of the super_*() or the dict_*() methods are intended for use
by test-modules.

Errors originating beneath this module (e.g. w/in virsh or libvirt_vm)
should not be caught (so caller can test for them).  Errors detected
within this module should raise LibvirtXMLError or a subclass.
"""

from virttest import utils_misc, xml_utils, virsh


class LibvirtXMLError(Exception):
    """
    Error originating within libvirt_xml module
    """

    def __init__(self, details=''):
        self.details = details
        Exception.__init__(self)


    def __str__(self):
        return str(self.details)


class LibvirtXMLBase(utils_misc.PropCanBase):
    """
    Base class for common attributes/methods applying to all sub-classes
    """

    __slots__ = ('xml', 'virsh')


    def __init__(self, virsh_instance):
        """
        Initialize instance with connection to virsh

        @param: virsh_instance: virsh module or instance to use
        """
        # Don't define any initial property values
        super(LibvirtXMLBase, self).__init__({'virsh':virsh_instance, 'xml':None})


    def set_virsh(self, value):
        """Accessor method for virsh property, make sure it's right type"""
        value_type = type(value)
        if (value.__name__ == "virsh" and hasattr(value, "command")
             or
             issubclass(value_type, virsh.VirshBase) ):
            self.dict_set('virsh', value)
        else:
            raise LibvirtXMLError("virsh parameter must be a module named virsh"
                                  " or subclass of virsh.VirshBase")


    @staticmethod
    def __readonly__(name):
        raise LibvirtXMLError('Instances property %s is read-only'
                              % name)

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
        # help keep line length short, virsh is not a property
        the_copy = self.__class__(self.virsh)
        try:
            # file may not be accessable, obtain XML string value
            xmlstr = str(self.dict_get('xml'))
            the_copy.dict_set('xml', xml_utils.XMLTreeFile(xmlstr))
        except LibvirtXMLError: # Allow other exceptions through
            pass # no XML was loaded yet
        return the_copy


class LibvirtXML(LibvirtXMLBase):
    """
    Handler of libvirt capabilities and nonspecific item operations.
    """


    #TODO: Add more __slots__ and accessors to get some useful stats
    # e.g. guest_count, arch, uuid, cpu_count, etc.
    __slots__ = LibvirtXMLBase.__slots__ + ('os_arch_machine_map',)

    def __init__(self, virsh_instance):
        super(LibvirtXML, self).__init__(virsh_instance)
        # calls set_xml accessor method
        self['xml'] = self.virsh.capabilities()
        self['os_arch_machine_map'] = None


    def get_os_arch_machine_map(self):
        """
        Accessor method for os_arch_machine_map property
        """
        oamm = {} #Schema {<os_type>:{<arch name>:[<machine>, ...]}}
        xmltreefile = self.dict_get('xml')
        for guest in xmltreefile.findall('guest'):
            os_type_name = guest.find('os_type').text
            # Multiple guest definitions can share same os_type (e.g. hvm, pvm)
            if os_type_name == 'xen':
                os_type_name = 'pv'
            amm = oamm.get(os_type_name, {})
            for arch in guest.findall('arch'):
                arch_name = arch.get('name')
                mmap = amm.get(arch_name, [])
                for machine in arch.findall('machine'):
                    machine_text = machine.text
                    # Don't add duplicate entries
                    if not mmap.count(machine_text):
                        mmap.append(machine_text)
                amm[arch_name] = mmap
            oamm[os_type_name] = amm
        return oamm


    def set_os_arch_machine_map(self, value):
        """Disallow changing of os_arch_machine_dict property"""
        if not self.super_get('INITIALIZED'):
            self.dict_set('os_arch_machine_dict', value)
        else:
            self.__readonly__('os_arch_machine_dict')


    def del_os_arch_machine_map(self):
        """Disallow changing of os_arch_machine_dict property"""
        self.__readonly__('os_arch_machine_dict')


class VMXMLBase(LibvirtXMLBase):
    """
    Accessor methods for VMXML class
    """

    __slots__ = LibvirtXMLBase.__slots__ + ('vm_name', 'uuid', 'vcpu')


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


    def get_vcpu(self):
        """
        Return VM's vcpu setting from XML definition
        """
        xmltreefile = self.dict_get('xml')
        return xmltreefile.find('vcpu').text


    def set_vcpu(self, value):
        """
        Sets the value of vcpu tag in VM XML definition
        """
        xmltreefile = self.dict_get('xml')
        vcpu = xmltreefile.find('vcpu')
        vcpu.text = str(value)
        xmltreefile.write()


    def del_vcpu(self):
        """
        Remove vcpu tag so libvirt can re-generate
        """
        xmltreefile = self.dict_get('xml')
        xmltreefile.remove_by_xpath('vcpu')
        xmltreefile.write()


class VMXML(VMXMLBase):
    """
    Manipulators of a VM through it's XML definition
    """

    __slots__ = VMXMLBase.__slots__


    @staticmethod # static method (no self) needed b/c calls VMXML.__new__
    def new_from_dumpxml(vm_name, virsh_instance):
        """
        Return new VMXML instance from virsh dumpxml command

        @param: vm_name: Name of VM to dumpxml
        @param: virsh_instance: virsh module or instance to use
        @return: New initialized VMXML instance
        """
        vmxml = VMXML(virsh_instance)
        vmxml['xml'] = virsh_instance.dumpxml(vm_name)
        return vmxml


    def undefine(self):
        """Undefine this VM with libvirt retaining XML in instance"""
        # Allow any exceptions to propigate up
        self.virsh.remove_domain(self.vm_name)


    def define(self):
        """Define VM with virsh from this instance"""
        # Allow any exceptions to propigate up
        self.virsh.define(self.xml)


    #TODO: Add function to create from xml_utils.TemplateXML()
    # def new_from_template(...)
