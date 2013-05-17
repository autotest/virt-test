"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatdomain.html
"""

import logging
from autotest.client.shared import error
from virttest import virsh, xml_utils
from virttest.libvirt_xml import base, accessors, xcepts
from virttest.libvirt_xml.devices import librarian


class VMXMLDevices(list):
    """
    List of device instances from classes handed out by librarian.get()
    """

    def __type_check__(self, other):
        try:
            # Raise error if object isn't dict-like or doesn't have key
            device_tag = other['device_tag']
            # Check that we have support for this type
            librarian.get(device_tag)
        except (AttributeError, TypeError, xcepts.LibvirtXMLError):
            # Required to always raise TypeError for list API in VMXML class
            raise TypeError("Unsupported item type: %s" % str(type(other)))


    def __setitem__(self, key, value):
        self.__type_check__(value)
        super(VMXMLDevices, self).__setitem__(key, value)


    def append(self, value):
        self.__type_check__(value)
        super(VMXMLDevices, self).append(value)


    def extend(self, iterable):
        # Make sure __type_check__ happens
        for item in iterable:
            self.append(item)


class VMXMLBase(base.LibvirtXMLBase):
    """
    Accessor methods for VMXML class properties (items in __slots__)

    Properties:
        hypervisor_type: string, hypervisor type name
            get: return domain's type attribute value
            set: change domain type attribute value
            del: raise xcepts.LibvirtXMLError
        vm_name: string, name of the vm
            get: return text value of name tag
            set: set text value of name tag
            del: raise xcepts.LibvirtXMLError
        uuid: string, uuid string for vm
            get: return text value of uuid tag
            set: set text value for (new) uuid tag (unvalidated)
            del: remove uuid tag
        vcpu, max_mem, current_mem: integers
            get: returns integer
            set: set integer
            del: removes tag
        numa: dictionary
            get: return dictionary of numatune/memory attributes
            set: set numatune/memory attributes from dictionary
            del: remove numatune/memory tag
        devices: VMXMLDevices (list-like)
            get: returns VMXMLDevices instance for all devices
            set: Define all devices from VMXMLDevices instance
            del: remove all devices
    """

    # Additional names of attributes and dictionary-keys instances may contain
    __slots__ = base.LibvirtXMLBase.__slots__ + ('hypervisor_type', 'vm_name',
                                                 'uuid', 'vcpu', 'max_mem',
                                                 'current_mem', 'devices')

    __uncompareable__ = base.LibvirtXMLBase.__uncompareable__

    __schema_name__ = "domain"

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLAttribute(property_name="hypervisor_type",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='domain',
                               attribute='type')
        accessors.XMLElementText(property_name="vm_name",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='name')
        accessors.XMLElementText(property_name="uuid",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='uuid')
        accessors.XMLElementInt(property_name="vcpu",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='vcpu')
        accessors.XMLElementInt(property_name="max_mem",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='memory')
        accessors.XMLElementInt(property_name="current_mem",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='currentMemory')
        super(VMXMLBase, self).__init__(virsh_instance=virsh_instance)


    def get_devices(self, device_type=None):
        """
        Put all nodes of devices into a VMXMLDevices instance.
        """
        devices = VMXMLDevices()
        all_devices = self.xmltreefile.find('devices')
        if device_type is not None:
            device_nodes = all_devices.findall(device_type)
        else:
            device_nodes = all_devices
        for node in device_nodes:
            device_tag = node.tag
            device_class = librarian.get(device_tag)
            new_one = device_class.new_from_element(node)
            devices.append(new_one)
        return devices


    def set_devices(self, value):
        """
        Define devices based on contents of VMXMLDevices instance
        """
        value_type = type(value)
        if not issubclass(value_type, VMXMLDevices):
            raise xcepts.LibvirtXMLError("Value %s Must be a VMXMLDevices or "
                                         "subclass not a %s"
                                         % (str(value), str(value_type)))
        # Start with clean slate
        self.del_devices()
        if len(value) > 0:
            devices_element = xml_utils.ElementTree.SubElement(
                                    self.xmltreefile.getroot(), 'devices')
            for device in value:
                # Separate the element from the tree
                device_element = device.getroot()
                devices_element.append(device_element)
        self.xmltreefile.write()


    def del_devices(self):
        """
        Remove all devices
        """
        self.xmltreefile.remove_by_xpath('/devices')
        self.xmltreefile.write()


class VMXML(VMXMLBase):
    """
    Higher-level manipulations related to VM's XML or guest/host state
    """

    # Must copy these here or there will be descriptor problems
    __slots__ = VMXMLBase.__slots__


    def __init__(self, hypervisor_type='kvm', virsh_instance=base.virsh):
        """
        Create new VM XML instance
        """
        super(VMXML, self).__init__(virsh_instance=virsh_instance)
        # Setup some bare-bones XML to build upon
        self.xml = u"<domain type='%s'></domain>" % hypervisor_type


    @staticmethod # static method (no self) needed b/c calls VMXML.__new__
    def new_from_dumpxml(vm_name, virsh_instance=virsh):
        """
        Return new VMXML instance from virsh dumpxml command

        @param: vm_name: Name of VM to dumpxml
        @param: virsh_instance: virsh module or instance to use
        @return: New initialized VMXML instance
        """
        # TODO: Look up hypervisor_type on incoming XML
        vmxml = VMXML(virsh_instance=virsh_instance)
        vmxml['xml'] = virsh_instance.dumpxml(vm_name)
        return vmxml


    @staticmethod
    def get_device_class(type_name):
        """
        Return class that handles type_name devices, or raise exception.
        """
        return librarian.get(type_name)


    def undefine(self):
        """Undefine this VM with libvirt retaining XML in instance"""
        # Allow any exceptions to propigate up
        self.virsh.remove_domain(self.vm_name)


    def define(self):
        """Define VM with virsh from this instance"""
        # Allow any exceptions to propigate up
        self.virsh.define(self.xml)


    @staticmethod
    def vm_rename(vm, new_name, uuid=None, virsh_instance=base.virsh):
        """
        Rename a vm from its XML.

        @param vm: VM class type instance
        @param new_name: new name of vm
        @param uuid: new_vm's uuid, if None libvirt will generate.
        @return: a new VM instance
        """
        if vm.is_alive():
            vm.destroy(gracefully=True)
        vmxml = VMXML.new_from_dumpxml(vm_name=vm.name, virsh_instance=virsh_instance)
        backup = vmxml.copy()
        # can't do in-place rename, must operate on XML
        try:
            vmxml.undefine()
            # All failures trip a single exception
        except error.CmdError, detail:
            del vmxml # clean up temporary files
            raise xcepts.LibvirtXMLError("Error reported while undefining VM:\n"
                                         "%s" % detail)
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
            raise xcepts.LibvirtXMLError("Error reported while defining VM:\n%s"
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
    def get_disk_source(vm_name):
        """
        Get block device  of a defined VM's disks.

        @param: vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        disks = vmxml.get_disk_all()
        return disks.values()


    @staticmethod
    def get_disk_blk(vm_name):
        """
        Get block device  of a defined VM's disks.

        @param: vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        disks = vmxml.get_disk_all()
        return disks.keys()


    @staticmethod
    def get_disk_count(vm_name):
        """
        Get count of VM's disks.

        @param: vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        disks = vmxml.get_disk_all()
        if disks != None:
            return len(disks)
        return 0


    # ToDo: Convert into numa property (needs nested-dict accessorgenerator)
    def get_numa_params(self, vm_name):
        """
        Return VM's numa setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        xmltreefile = vmxml.dict_get('xml')
        numa_params = {}
        try:
            numa = xmltreefile.find('numatune')
            try:
                numa_params['mode'] = numa.find('memory').get('mode')
                numa_params['nodeset'] = numa.find('memory').get('nodeset')
            except TypeError:
                logging.error("Can't find <memory> element")
        except TypeError:
            logging.error("Can't find <numatune> element")
        return numa_params


    def get_primary_serial(self):
        """
        Get a dict with primary serial features.
        """
        xmltreefile = self.dict_get('xml')
        primary_serial = xmltreefile.find('devices').find('serial')
        serial_features = {}
        serial_type = primary_serial.get('type')
        serial_port = primary_serial.find('target').get('port')
        # Support node here for more features
        serial_features['serial'] = primary_serial
        # Necessary features
        serial_features['type'] = serial_type
        serial_features['port'] = serial_port
        return serial_features


    @staticmethod
    def set_primary_serial(vm_name, dev_type, port, path=None):
        """
        Set primary serial's features of vm_name.

        @param vm_name: Name of defined vm to set primary serial.
        @param dev_type: the type of serial:pty,file...
        @param port: the port of serial
        @param path: the path of serial, it is not necessary for pty
        # TODO: More features
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        xmltreefile = vmxml.dict_get('xml')
        try:
            serial = vmxml.get_primary_serial()['serial']
        except AttributeError:
            logging.debug("Can not find any serial, now create one.")
            # Create serial tree, default is pty
            serial = xml_utils.ElementTree.SubElement(
                                xmltreefile.find('devices'),
                                'serial', {'type': 'pty'})
            # Create elements of serial target, default port is 0
            xml_utils.ElementTree.SubElement(serial, 'target', {'port': '0'})

        serial.set('type', dev_type)
        serial.find('target').set('port', port)
        # path may not be exist.
        if path is not None:
            serial.find('source').set('path', path)
        else:
            try:
                source = serial.find('source')
                serial.remove(source)
            except AssertionError:
                pass # Element not found, already removed.
        xmltreefile.write()
        vmxml.set_xml(xmltreefile.name)
        vmxml.undefine()
        vmxml.define()


    def get_iface_all(self):
        """
        Get a dict with interface's mac and node.
        """
        iface_nodes = self.xmltreefile.find('devices').findall('interface')
        interfaces = {}
        for node in iface_nodes:
            mac_addr = node.find('mac').get('address')
            interfaces[mac_addr] = node
        return interfaces


    @staticmethod
    def get_iface_by_mac(vm_name, mac):
        """
        Get the interface if mac is matched.

        @param vm_name: Name of defined vm.
        @param mac: a mac address.
        @return: return a dict include main interface's features
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        interfaces = vmxml.get_iface_all()
        try:
            interface = interfaces[mac]
        except KeyError:
            interface = None
        if interface is not None: # matched mac exists.
            iface_type = interface.get('type')
            source = interface.find('source').get(iface_type)
            features = {}
            features['type'] = iface_type
            features['mac'] = mac
            features['source'] = source
            return features
        else:
            return None
