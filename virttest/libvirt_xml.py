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

import logging
from virttest import xml_utils, virsh, propcan
from autotest.client.shared import error


class LibvirtXMLError(Exception):
    """
    Error originating within libvirt_xml module
    """

    def __init__(self, details=''):
        self.details = details
        Exception.__init__(self)


    def __str__(self):
        return str(self.details)


class LibvirtXMLBase(propcan.PropCanBase):
    """
    Base class for common attributes/methods applying to all sub-classes

    Properties:
        xml: XMLTreeFile instance
            get: xml filename string
            set: create new XMLTreeFile instance from string or filename
            del: deletes property, closes & unlinks any temp. files
        virsh: virsh module or Virsh class instance
            set: validates and sets value
            get: returns value
            del: removes value

    """

    __slots__ = ('xml', 'virsh')


    def __init__(self, virsh_instance=virsh):
        """
        Initialize instance with connection to virsh

        @param: virsh_instance: virsh module or instance to use
        """
        # Don't define any initial property values
        super(LibvirtXMLBase, self).__init__({'virsh':virsh_instance,
                                              'xml':None})


    def __str__(self):
        """
        Returns raw XML as a string
        """
        return str(self.dict_get('xml'))


    def set_virsh(self, value):
        """Accessor method for virsh property, make sure it's right type"""
        value_type = type(value)
        # issubclass can't work for classes using __slots__ (i.e. no __bases__)
        if hasattr(value, 'VIRSH_EXEC') or hasattr(value, 'virsh_exec'):
            self.dict_set('virsh', value)
        else:
            raise LibvirtXMLError("virsh parameter must be a module named virsh"
                                  " or subclass of virsh.VirshBase not a %s" %
                                  str(value_type))


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

    Properties:
        os_arch_machine_map: strores None, virtual, read-only
            get: dict map from os type names to dict map from arch names
    """

    #TODO: Add more __slots__ and accessors to get some useful stats
    # e.g. guest_count, arch, uuid, cpu_count, etc.

    __slots__ = LibvirtXMLBase.__slots__ + ('os_arch_machine_map',)

    def __init__(self, virsh_instance=virsh):
        super(LibvirtXML, self).__init__(virsh_instance)
        # calls set_xml accessor method
        self['xml'] = self.virsh.capabilities()
        # INITIALIZED=true after call to super __init__
        self.dict_set('os_arch_machine_map', None)


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

    Properties:
        hypervisor_type: virtual string, hypervisor type name
            get: return domain's type attribute value
            set: change domain type attribute value
            del: raise LibvirtXMLError
        vm_name: virtual string, name of the vm
            get: return text value of name tag
            set: set text value of name tag
            del: raise LibvirtXMLError
        uuid: virtual string, uuid string for vm
            get: return text value of uuid tag
            set: set text value for (new) uuid tag (unvalidated)
            del: remove uuid tag
        vcpu: virtual integer, number of vcpus
            get: returns integer of vcpu tag text value
            set: set integer of (new) vcpu tag text value
            del: removes vcpu tag
    """

    __slots__ = LibvirtXMLBase.__slots__ + ('hypervisor_type', 'vm_name',
                                            'uuid', 'vcpu')


    def get_hypervisor_type(self):
        """
        Accessor method for 'hypervisor_type' property
        """
        xmltreefile = self.dict_get('xml')
        root = xmltreefile.getroot()
        return root.get('type')


    def set_hypervisor_type(self, value):
        """
        Accessor method for 'hypervisor_type' property
        """
        xmltreefile = self.dict_get('xml')
        root = xmltreefile.getroot()
        root.set('type', '"%s"' % str(value))
        xmltreefile.write()


    def del_hypervisor_type(self):
        """
        Accessor method for 'hypervisor_type' property
        """
        # Raise different exception if xml wasn't loaded
        if self.has_key('xml'):
            pass
        raise LibvirtXMLError("Can't delete required hypervisor"
                              " hypervisor_type property")


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
        xmltreefile = self.dict_get('xml')
        name = xmltreefile.find('name')
        if name is None:
            # Create new name element and append to root element
            name = xml_utils.ElementTree.SubElement(xmltreefile.getroot(),
                                                    'name')
        name.text = str(value)
        xmltreefile.write()


    def del_vm_name(self):
        """
        Raise LibVirtXMLError because name is a required element
        """
        # Raise different exception if xml wasn't loaded
        if self.has_key('xml'):
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
        if value is None:
            del self.uuid
            return

        xmltreefile = self.dict_get('xml')
        uuid = xmltreefile.find('uuid')
        if uuid is None:
            # Create new name element and append to root element
            uuid = xml_utils.ElementTree.SubElement(xmltreefile.getroot(),
                                                    'uuid')
        uuid.text = value
        xmltreefile.write()


    def del_uuid(self):
        """
        Remove the uuid from a VM so libvirt can generate a new one
        """
        xmltreefile = self.dict_get('xml')
        try:
            xmltreefile.remove_by_xpath('uuid')
        except AttributeError:
            pass # element not found, nothing to delete
        xmltreefile.write()


    def get_vcpu(self):
        """
        Return VM's vcpu setting from XML definition, None if not set
        """
        xmltreefile = self.dict_get('xml')
        return int(xmltreefile.find('vcpu').text)


    def set_vcpu(self, value):
        """
        Sets the value of vcpu tag in VM XML definition
        """
        xmltreefile = self.dict_get('xml')
        vcpu = xmltreefile.find('vcpu')
        if vcpu is None:
            # Create new vcpu element and append to root element
            vcpu = xml_utils.ElementTree.SubElement(xmltreefile.getroot(),
                                                    'vcpu')
        vcpu.text = str(int(value))
        xmltreefile.write()


    def del_vcpu(self):
        """
        Remove vcpu tag so libvirt can re-generate
        """
        xmltreefile = self.dict_get('xml')
        try:
            xmltreefile.remove_by_xpath('vcpu')
        except AttributeError:
            pass # Element not found, already removed.
        xmltreefile.write()


class VMXML(VMXMLBase):
    """
    Manipulators of a VM through it's XML definition
    """

    __slots__ = VMXMLBase.__slots__


    def __init__(self, virsh_instance=virsh, hypervisor_type='kvm'):
        """
        Create new VM XML instance
        """
        super(VMXML, self).__init__(virsh_instance)
        self.xml = u"<domain type='%s'></domain>" % hypervisor_type


    @staticmethod # static method (no self) needed b/c calls VMXML.__new__
    def new_from_dumpxml(vm_name, virsh_instance=virsh):
        """
        Return new VMXML instance from virsh dumpxml command

        @param: vm_name: Name of VM to dumpxml
        @param: virsh_instance: virsh module or instance to use
        @return: New initialized VMXML instance
        """
        vmxml = VMXML(virsh_instance=virsh_instance)
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


    @staticmethod
    def vm_rename(vm, new_name, uuid=None):
        """
        Rename a vm from its XML.

        @param vm: VM class type instance
        @param new_name: new name of vm
        @param uuid: new_vm's uuid
                     if it is None, libvirt will auto-generate.
        @return: a new VM instance
        """
        if vm.is_alive():
            vm.destroy(gracefully=True)

        vmxml = VMXML.new_from_dumpxml(vm.name)
        backup = vmxml.copy()
        # can't do in-place rename, must operate on XML
        try:
            vmxml.undefine()
            # All failures trip a single exception
        except error.CmdError, detail:
            del vmxml # clean up temporary files
            raise LibvirtXMLError("Error reported while undefining VM:\n%s"
                                   % detail)
        # Alter the XML
        vmxml.vm_name = new_name
        if uuid is None:
            # invalidate uuid so libvirt will regenerate
            del vmxml.uuid
            vm.uuid = None
        else:
            vmxml.uuid = uuid
            vm.uuid = uuid
        # Re-define XML to libvirt
        logging.debug("Rename %s to %s.", vm.name, new_name)
        try:
            vmxml.define()
        except error.CmdError, detail:
            del vmxml # clean up temporary files
            # Allow exceptions thrown here since state will be undefined
            backup.define()
            raise LibvirtXMLError("Error reported while defining VM:\n%s"
                                   % detail)
        # Keep names uniform
        vm.name = new_name
        return vm


    @staticmethod
    def set_vm_vcpus(vm_name, value):
        """
        Convenience method for updating 'vcpu' property of a defined VM

        @param: vm_name: Name of defined vm to change vcpu elemnet data
        @param: value: New data value, None to delete.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        if value is not None:
            vmxml['vcpu'] = value # call accessor method to change XML
        else: # value == None
            del vmxml.vcpu
        vmxml.undefine()
        vmxml.define()
        # Temporary files for vmxml cleaned up automatically
        # when it goes out of scope here.


    def get_disk_all(self):
        """
        Return VM's disk from XML definition, None if not set
        """
        xmltreefile = self.dict_get('xml')
        disk_nodes = xmltreefile.find('devices').findall('disk')
        disks = {}
        for node in disk_nodes:
            dev = node.find('target').get('dev')
            disks[dev] = node
        return disks


    @staticmethod
    def get_disk_blk(vm_name):
        """
        Get block device  of a defined VM's disks.

        @param: vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        disks = vmxml.get_disk_all()
        if disks != None:
            return disks.keys()
        return None


    #TODO: Add function to create from xml_utils.TemplateXML()
    # def new_from_template(...)


class NetworkXMLBase(LibvirtXMLBase):
    """
    Accessor methods for NetworkXML class.

    Properties:
        name: virtual, operates on XML name tag
        uuid: virtual, operates on uuid tag
        bridge: virtual, operates on bridge attributes
            get: Return dictionary of attributes & values
            set: Set attributes from dictionary of values
            del: Remove bridge element
        defined: virtual, callout to virsh methods
            get: True if libvirt knows network name
            set: True defines network, False undefines to libvirt
            del: Undefines network to libvirt
        active: virtual, callout to virsh methods
            get: True if network is active to libvirt
            set: True activates network, False deactivates to libvirt
            del: Deactivates network to libvirt
        autostart: virtual, callout to virsh methods
            get: True if libvirt autostarts network with same name
            set: True to set autostart, False to unset to libvirt
            del: Unset autostart to libvirt
        persistent: virtual, callout to virsh methods
            get: True if network was defined, False if only created.
            set: Same as defined property
            del: Same as defined property
    """

    __slots__ = LibvirtXMLBase.__slots__ + ('name', 'uuid', 'bridge', 'defined',
                                            'active', 'autostart', 'persistent')

    def get_name(self):
        """
        Accessor method for getting 'name' property.
        """
        xmltreefile = self.dict_get('xml')
        return xmltreefile.find('/name').text


    def set_name(self, value):
        """
        Accessor method for setting 'name' property.
        """
        xmltreefile = self.dict_get('xml')
        name = xmltreefile.find('/name')
        if name is None:
            name = xml_utils.ElementTree.SubElement(
                                    xmltreefile.getroot(), "name")
        name.text = value
        xmltreefile.write()


    def del_name(self):
        """
        Raise LibVirtXMLError because name is a required element
        """
        # Raise different exception if xml wasn't loaded
        if self.haskey('xml'):
            pass
        raise LibvirtXMLError("name can't be deleted, it's a required element")


    def get_uuid(self):
        """
        Return Network's uuid or None if not set
        """
        xmltreefile = self.dict_get('xml')
        return xmltreefile.find('/uuid').text


    def set_uuid(self, value):
        """
        Set or create a new uuid element for a Network
        """
        xmltreefile = self.dict_get('xml')
        if value is None:
            del self.uuid
        else:
            uuid = xmltreefile.find('/uuid')
            if uuid is None:
                uuid = xml_utils.ElementTree.SubElement(
                                    xmltreefile.getroot(), "uuid")
            uuid.text = value
        xmltreefile.write()


    def del_uuid(self):
        """
        Remove the uuid from a Network so libvirt can generate a new one
        """
        xmltreefile = self.dict_get('xml')
        try:
            xmltreefile.remove_by_xpath('/uuid')
        except AttributeError:
            pass # element not found, nothing to delete
        xmltreefile.write()


    def get_bridge(self):
        """Accessor method for 'bridge' property"""
        xmltreefile = self.dict_get('xml')
        element = xmltreefile.find('/bridge')
        if element is not None:
            return dict(element.items())
        else:
            raise LibvirtXMLError('No bridge element found')


    def set_bridge(self, value):
        """Accessor method for 'bridge' property"""
        if not issubclass(value.__class__, dict):
            raise LibvirtXMLError("Bridge property must be set from dictionary"
                                  " value")
        xmltreefile = self.dict_get('xml')
        # Always make new element, so attributes can be removed
        self.del_bridge()
        element = xml_utils.ElementTree.SubElement(
                                     xmltreefile.getroot(), "bridge")
        for attr_key, attr_value in value.items():
            element.set(str(attr_key), str(attr_value))
        xmltreefile.write()


    def del_bridge(self):
        """Accessor method for 'bridge' property"""
        xmltreefile = self.dict_get('xml')
        try:
            xmltreefile.remove_by_xpath('/bridge')
        except AttributeError:
            pass # element not found, nothing to delete
        xmltreefile.write()


    def __check_undefined__(self, errmsg):
        if not self.defined:
            raise LibvirtXMLError(errmsg)


    def get_defined(self):
        """
        Accessor for 'define' property - does this name exist in network list
        """
        return self.name in self.virsh.net_state_dict(only_names=True).keys()


    def set_defined(self, value):
        """Accessor method for 'define' property, set True to define."""
        if not self.super_get('INITIALIZED'):
            pass # do nothing
        value = bool(value)
        if value:
            self.virsh.net_define(self.xml) # send it the filename
        else:
            del self.defined


    def del_defined(self):
        """Accessor method for 'define' property, undefines network"""
        self.__check_undefined__("Cannot undefine non-existant network")
        self.virsh.net_undefine(self.name)


    def get_active(self):
        """Accessor method for 'active' property (True/False)"""
        self.__check_undefined__("Cannot determine activation for undefined "
                                 "network")
        state_dict = self.virsh.net_state_dict()
        return state_dict[self.name]['active']


    def set_active(self, value):
        """Accessor method for 'active' property, sets network active"""
        if not self.super_get('INITIALIZED'):
            pass # do nothing
        self.__check_undefined__("Cannot activate undefined network")
        value = bool(value)
        if value:
            if not self.active:
                self.virsh.net_start(self.name)
            else:
                pass # don't activate twice
        else:
            if self.active:
                del self.active
            else:
                pass # don't deactivate twice


    def del_active(self):
        """Accessor method for 'active' property, stops network"""
        self.__check_undefined__("Cannot deactivate undefined network")
        if self.active:
            self.virsh.net_destroy(self.name)
        else:
            pass # don't destroy twice


    def get_autostart(self):
        """Accessor method for 'autostart' property, True if set"""
        self.__check_undefined__("Cannot determine autostart for undefined "
                                 "network")
        state_dict = self.virsh.net_state_dict()
        return state_dict[self.name]['autostart']


    def set_autostart(self, value):
        """Accessor method for 'autostart' property, sets/unsets autostart"""
        if not self.super_get('INITIALIZED'):
            pass # do nothing
        self.__check_undefined__("Cannot set autostart for undefined network")
        value = bool(value)
        if value:
            if not self.autostart:
                self.virsh.net_autostart(self.name)
            else:
                pass # don't set autostart twice
        else:
            if self.autostart:
                del self.autostart
            else:
                pass # don't unset autostart twice


    def del_autostart(self):
        """Accessor method for 'autostart' property, unsets autostart"""
        if not self.defined:
            raise LibvirtXMLError
        self.virsh.net_autostart(self.name, "--disable")


    def get_persistent(self):
        """Accessor method for 'persistent' property"""
        state_dict = self.virsh.net_state_dict()
        return state_dict[self.name]['persistent']

    # Copy behavior for consistency
    set_persistent = set_defined
    del_persistent = del_defined


class NetworkXML(NetworkXMLBase):
    """
    Manipulators of a Virtual Network through it's XML definition.
    """

    __slots__ = NetworkXMLBase.__slots__


    def __init__(self, network_name, virsh_instance=virsh):
        """
        Initialize new instance with empty XML
        """
        super(NetworkXML, self).__init__(virsh_instance)
        self.xml = u"<network><name>%s</name></network>" % network_name


    @staticmethod # wraps __new__
    def new_all_networks_dict(virsh_instance=virsh):
        """
        Return a dictionary of names to NetworkXML instances for all networks

        @param: virsh: virsh module or instance to use
        @return: Dictionary of network name to NetworkXML instance
        """
        result = {}
        # Values should all share virsh property
        new_netxml = NetworkXML("NoName", virsh_instance)
        networks = new_netxml.virsh.net_state_dict(only_names=True).keys()
        for net_name in networks:
            new_copy = new_netxml.copy()
            new_copy.xml = virsh.net_dumpxml(net_name).stdout.strip()
            result[net_name] = new_copy
        return result


    def debug_xml(self):
        """
        Dump contents of XML file for debugging
        """
        xml = str(self) # LibvirtXMLBase.__str__ returns XML content
        for debug_line in str(xml).splitlines():
            logging.debug("Network XML: %s", debug_line)


    def create(self):
        """
        Adds non-persistant / transient network to libvirt with net-create
        """
        self.virsh.net_create(self.xml)


    def orbital_nuclear_strike(self):
        """It's the only way to really be sure.  Remove all libvirt state"""
        try:
            self['active'] = False # deactivate (stop) network if active
        except LibvirtXMLError, detail:
            # inconsequential, network will be removed
            logging.warning(detail)
        try:
            self['defined'] = False # undefine (delete) network if persistent
        except LibvirtXMLError, detail:
            # network already gone
            logging.warning(detail)


    # TODO: Add functions for Network's Operation.
    # TODO: Add new_from_template method
