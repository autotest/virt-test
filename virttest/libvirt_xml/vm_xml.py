"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatdomain.html
"""

import logging
from autotest.client.shared import error
from virttest import xml_utils
from virttest.libvirt_xml import base, accessors, xcepts
from virttest.libvirt_xml.devices import librarian


class VMXMLDevices(list):

    """
    List of device instances from classes handed out by librarian.get()
    """

    @staticmethod
    def __type_check__(other):
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
        return self

    def append(self, value):
        self.__type_check__(value)
        super(VMXMLDevices, self).append(value)
        return self

    def extend(self, iterable):
        # Make sure __type_check__ happens
        for item in iterable:
            self.append(item)
        return self

    def by_device_tag(self, tag):
        result = VMXMLDevices()
        for device in self:
            if device.device_tag == tag:
                result.append(device)
        return result


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
        dumpcore: string,  control guest OS memory dump
            get: return text value
            set: set 'on' or 'off' for guest OS memory dump
            del: removes tag
        numa_memory: dictionary
            get: return dictionary of numatune/memory attributes
            set: set numatune/memory attributes from dictionary
            del: remove numatune/memory tag
        numa_memnode: list dict of memnode attributes cellid, mode and nodeset
            get: return list of dictionary with numatune/memnode attributes
            set: set multiple numatune/memnode attributes from dictionary list
            del: remove numatune/memnode tag
        on_poweroff: string, action to take when the guest requests a poweroff
            get: returns text value of on_poweroff tag
            set: set test of on_poweroff tag
            del: remove on_poweroff tag
        on_reboot: string, action to take when the guest requests a reboot
            get: returns text value of on_reboot tag
            set: set test of on_reboot tag
            del: remove on_reboot tag
        on_crash: string, action to take when the guest crashes
            get: returns text value of on_crash tag
            set: set test of on_crash tag
            del: remove on_crash tag
        devices: VMXMLDevices (list-like)
            get: returns VMXMLDevices instance for all devices
            set: Define all devices from VMXMLDevices instance
            del: remove all devices
        cputune: VMCPUTuneXML
            get: return VMCPUTuneXML instance for the domain.
            set: Define cputune tag from a VMCPUTuneXML instance.
            del: remove cputune tag
        cpu: VMCPUXML
            get: return VMCPUXML instance for the domain.
            set: Define cpu tag from a VMCPUXML instance.
            del: remove cpu tag
        current_vcpu: string, 'current' attribute of vcpu tag
            get: return a string for 'current' attribute of vcpu
            set: change 'current' attribute of vcpu
            del: remove 'current' attribute of vcpu
        placement: string, 'placement' attribute of vcpu tag
            get: return a string for 'placement' attribute of vcpu
            set: change 'placement' attribute of vcpu
            del: remove 'placement' attribute of vcpu
        cpuset: string, 'cpuset' attribute of vcpu tag
            get: return a string for 'cpuset' attribute of vcpu
            set: change 'cpuset' attribute of vcpu
            del: remove 'cpuset' attribute of vcpu
        emulatorpin: string, cpuset value (see man virsh: cpulist)
            get: return text value of cputune/emulatorpin attributes
            set: set cputune/emulatorpin attributes from string
            del: remove cputune/emulatorpin tag
        features: VMFeaturesXML
            get: return VMFeaturesXML instances for the domain.
            set: define features tag from a VMFeaturesXML instances.
            del: remove features tag
        mem_backing: VMMemBackingXML
            get: return VMMemBackingXML instances for the domain.
            set: define memoryBacking tag from a VMMemBackingXML instances.
            del: remove memoryBacking tag
        max_mem_unit: string, 'unit' attribute of memory
            get: return text value of memory unit attribute
            set: set memory unit attribute
            del: remove memory unit attribute
        current_mem_unit: string, 'unit' attribute of memory
            get: return text value of current_memory unit attribute
            set: set current_memory unit attribute
            del: remove current_memory unit attribute
        memtune: VMMemTuneXML
            get: return VMMemTuneXML instance for the domain.
            set: Define memtune tag from a VMCPUTuneXML instance.
            del: remove memtune tag
    """

    # Additional names of attributes and dictionary-keys instances may contain
    __slots__ = ('hypervisor_type', 'vm_name', 'uuid', 'vcpu', 'max_mem',
                 'current_mem', 'dumpcore', 'numa_memory', 'numa_memnode',
                 'devices', 'seclabel', 'cputune', 'placement', 'cpuset',
                 'current_vcpu', 'os', 'cpu', 'pm', 'on_poweroff', 'on_reboot',
                 'on_crash', 'features', 'mb', 'max_mem_unit',
                 'current_mem_unit', 'memtune')

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
        accessors.XMLAttribute(property_name="current_vcpu",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='vcpu',
                               attribute='current')
        accessors.XMLAttribute(property_name="placement",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='vcpu',
                               attribute='placement')
        accessors.XMLAttribute(property_name="cpuset",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='vcpu',
                               attribute='cpuset')
        accessors.XMLElementInt(property_name="max_mem",
                                libvirtxml=self,
                                forbidden=None,
                                parent_xpath='/',
                                tag_name='memory')
        accessors.XMLAttribute(property_name="max_mem_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='memory',
                               attribute='unit')
        accessors.XMLAttribute(property_name="dumpcore",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='memory',
                               attribute='dumpCore')
        accessors.XMLElementInt(property_name="current_mem",
                                libvirtxml=self,
                                forbidden=None,
                                parent_xpath='/',
                                tag_name='currentMemory')
        accessors.XMLAttribute(property_name="current_mem_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='currentMemory',
                               attribute='unit')
        accessors.XMLElementNest(property_name='os',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='os',
                                 subclass=VMOSXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementDict(property_name="numa_memory",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='numatune',
                                 tag_name='memory')
        accessors.XMLElementList(property_name="numa_memnode",
                                 libvirtxml=self,
                                 parent_xpath='numatune',
                                 marshal_from=self.marshal_from_memnode,
                                 marshal_to=self.marshal_to_memnode)
        accessors.XMLElementNest(property_name='cputune',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='cputune',
                                 subclass=VMCPUTuneXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementNest(property_name='cpu',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='cpu',
                                 subclass=VMCPUXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementNest(property_name='pm',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='pm',
                                 subclass=VMPMXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementText(property_name="on_poweroff",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='on_poweroff')
        accessors.XMLElementText(property_name="on_reboot",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='on_reboot')
        accessors.XMLElementText(property_name="on_crash",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='on_crash')
        accessors.XMLElementNest(property_name='features',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='features',
                                 subclass=VMFeaturesXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementNest(property_name='mb',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='memoryBacking',
                                 subclass=VMMemBackingXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementNest(property_name='memtune',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='memtune',
                                 subclass=VMMemTuneXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        super(VMXMLBase, self).__init__(virsh_instance=virsh_instance)

    @staticmethod
    def marshal_from_memnode(item, index, libvirtxml):
        """
        Convert a dict to memnode tag and attributes.
        """
        del index
        del libvirtxml
        if not isinstance(item, dict):
            raise xcepts.LibvirtXMLError("Expected a dictionary of memnode "
                                         "attributes, not a %s"
                                         % str(item))
        return ('memnode', dict(item))

    @staticmethod
    def marshal_to_memnode(tag, attr_dict, index, libvirtxml):
        """
        Convert a memnode tag and attributes to a dict.
        """
        del index
        del libvirtxml
        if tag != 'memnode':
            return None
        return dict(attr_dict)

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
            new_one = device_class.new_from_element(node,
                                                    virsh_instance=self.virsh)
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
        exist_dev = self.xmltreefile.find('devices')
        if exist_dev is not None:
            self.del_devices()
        if len(value) > 0:
            devices_element = xml_utils.ElementTree.SubElement(
                self.xmltreefile.getroot(), 'devices')
            for device in value:
                # Separate the element from the tree
                device_element = device.xmltreefile.getroot()
                devices_element.append(device_element)
        self.xmltreefile.write()

    def del_devices(self):
        """
        Remove all devices
        """
        try:
            self.xmltreefile.remove_by_xpath('/devices', remove_all=True)
        except (AttributeError, TypeError):
            pass  # Element already doesn't exist
        self.xmltreefile.write()

    def get_seclabel(self):
        """
        Return seclabel + child attribute dict list or raise LibvirtXML error

        :return: None if no seclabel in xml,
                 list contains dict of seclabel's attributs and children.
        """
        __children_list__ = ['label', 'baselabel', 'imagelabel']

        seclabel_node = self.xmltreefile.findall("seclabel")
        # no seclabel tag found in xml.
        if seclabel_node == []:
            raise xcepts.LibvirtXMLError("Seclabel for this domain does not "
                                         "exist")
        seclabels = []
        for i in range(len(seclabel_node)):
            seclabel = dict(seclabel_node[i].items())
            for child_name in __children_list__:
                child_node = seclabel_node[i].find(child_name)
                if child_node is not None:
                    seclabel[child_name] = child_node.text
            seclabels.append(seclabel)

        return seclabels

    def set_seclabel(self, seclabel_dict_list):
        """
        Set seclabel of vm. Delete all seclabels if seclabel exists, create
        new seclabels use dict values from given seclabel_dict_list in
        xmltreefile.
        """
        __attributs_list__ = ['type', 'model', 'relabel']
        __children_list__ = ['label', 'baselabel', 'imagelabel']

        # check the type of seclabel_dict_list and value.
        if not isinstance(seclabel_dict_list, list):
            raise xcepts.LibvirtXMLError("seclabel_dict_list should be a "
                                         "instance of list, but not a %s.\n"
                                         % type(seclabel_dict_list))
        for seclabel_dict in seclabel_dict_list:
            if not isinstance(seclabel_dict, dict):
                raise xcepts.LibvirtXMLError("value in seclabel_dict_list"
                                             "should be a instance of dict "
                                             "but not a %s.\n"
                                             % type(seclabel_dict))

        seclabel_nodes = self.xmltreefile.findall("seclabel")
        if seclabel_nodes is not None:
            for i in range(len(seclabel_nodes)):
                self.del_seclabel()
        for i in range(len(seclabel_dict_list)):
            seclabel_node = xml_utils.ElementTree.SubElement(
                self.xmltreefile.getroot(),
                "seclabel")

            for key, value in seclabel_dict_list[i].items():
                if key in __children_list__:
                    child_node = seclabel_node.find(key)
                    if child_node is None:
                        child_node = xml_utils.ElementTree.SubElement(
                            seclabel_node,
                            key)
                    child_node.text = value

                elif key in __attributs_list__:
                    seclabel_node.set(key, value)

                else:
                    continue

            self.xmltreefile.write()

    def del_seclabel(self):
        """
        Remove the seclabel tag from a domain
        """
        try:
            self.xmltreefile.remove_by_xpath("/seclabel", remove_all=True)
        except (AttributeError, TypeError):
            pass  # Element already doesn't exist
        self.xmltreefile.write()

    def set_controller(self, controller_list):
        """
        Set controller of vm. Create new controllers use xmltreefile
        from given controller_list.
        """

        # check the type of controller_list and value.
        if not isinstance(controller_list, list):
            raise xcepts.LibvirtXMLError("controller_element_list should be a"
                                         "instance of list, but not a %s.\n"
                                         % type(controller_list))

        devices_element = self.xmltreefile.find("devices")
        for contl in controller_list:
            element = xml_utils.ElementTree.ElementTree(
                file=contl.xml)
            devices_element.append(element.getroot())
        self.xmltreefile.write()

    def del_controller(self, controller_type=None):
        """
        Delete controllers according controller type

        :return: None if deleting all controllers
        """
        all_controllers = self.xmltreefile.findall("devices/controller")
        del_controllers = []
        for controller in all_controllers:
            if controller.get("type") != controller_type:
                continue
            del_controllers.append(controller)

        # no seclabel tag found in xml.
        if del_controllers == []:
            logging.debug("Controller %s for this domain does not "
                          "exist" % controller_type)

        for controller in del_controllers:
            self.xmltreefile.remove(controller)


class VMXML(VMXMLBase):

    """
    Higher-level manipulations related to VM's XML or guest/host state
    """

    # Must copy these here or there will be descriptor problems
    __slots__ = []

    def __init__(self, hypervisor_type='kvm', virsh_instance=base.virsh):
        """
        Create new VM XML instance
        """
        super(VMXML, self).__init__(virsh_instance=virsh_instance)
        # Setup some bare-bones XML to build upon
        self.xml = u"<domain type='%s'></domain>" % hypervisor_type

    @staticmethod  # static method (no self) needed b/c calls VMXML.__new__
    def new_from_dumpxml(vm_name, options="", virsh_instance=base.virsh):
        """
        Return new VMXML instance from virsh dumpxml command

        :param vm_name: Name of VM to dumpxml
        :param virsh_instance: virsh module or instance to use
        :return: New initialized VMXML instance
        """
        # TODO: Look up hypervisor_type on incoming XML
        vmxml = VMXML(virsh_instance=virsh_instance)
        vmxml['xml'] = virsh_instance.dumpxml(vm_name,
                                              extra=options).stdout.strip()
        return vmxml

    @staticmethod
    def new_from_inactive_dumpxml(vm_name, options="", virsh_instance=base.virsh):
        """
        Return new VMXML instance of inactive domain from virsh dumpxml command

        :param vm_name: Name of VM to dumpxml
        :param options: virsh dumpxml command's options
        :param virsh_instance: virsh module or instance to use
        :return: New initialized VMXML instance
        """
        if options.find("--inactive") == -1:
            options += " --inactive"
        return VMXML.new_from_dumpxml(vm_name, options, virsh_instance)

    @staticmethod
    def get_device_class(type_name):
        """
        Return class that handles type_name devices, or raise exception.
        """
        return librarian.get(type_name)

    def undefine(self, options=None):
        """Undefine this VM with libvirt retaining XML in instance"""
        return self.virsh.remove_domain(self.vm_name, options)

    def define(self):
        """Define VM with virsh from this instance"""
        result = self.virsh.define(self.xml)
        if result.exit_status:
            logging.debug("Define %s failed.\n"
                          "Detail: %s.", self.vm_name, result.stderr)
            return False
        return True

    def sync(self, options=None):
        """Rebuild VM with the config file."""
        # If target vm no longer exist, this will raise an exception.
        try:
            backup = self.new_from_dumpxml(self.vm_name)
        except IOError:
            logging.debug("Failed to backup %s.", self.vm_name)
            backup = None

        if not self.undefine(options):
            raise xcepts.LibvirtXMLError("Failed to undefine %s."
                                         % self.vm_name)
        if not self.define():
            if backup:
                backup.define()
            raise xcepts.LibvirtXMLError("Failed to define %s, from %s."
                                         % (self.vm_name, self.xml))

    @staticmethod
    def vm_rename(vm, new_name, uuid=None, virsh_instance=base.virsh):
        """
        Rename a vm from its XML.

        :param vm: VM class type instance
        :param new_name: new name of vm
        :param uuid: new_vm's uuid, if None libvirt will generate.
        :return: a new VM instance
        """
        if vm.is_alive():
            vm.destroy(gracefully=True)
        vmxml = VMXML.new_from_dumpxml(vm_name=vm.name,
                                       virsh_instance=virsh_instance)
        backup = vmxml.copy()
        # can't do in-place rename, must operate on XML
        if not vmxml.undefine():
            del vmxml  # clean up temporary files
            raise xcepts.LibvirtXMLError("Error reported while undefining VM")
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
        # error message for failed define
        error_msg = "Error reported while defining VM:\n"
        try:
            if not vmxml.define():
                raise xcepts.LibvirtXMLError(error_msg + "%s"
                                             % vmxml.get('xml'))
        except error.CmdError, detail:
            del vmxml  # clean up temporary files
            # Allow exceptions thrown here since state will be undefined
            backup.define()
            raise xcepts.LibvirtXMLError(error_msg + "%s" % detail)
        # Keep names uniform
        vm.name = new_name
        return vm

    @staticmethod
    def set_pm_suspend(vm_name, mem="yes", disk="yes", virsh_instance=base.virsh):
        """
        Add/set pm suspend Support

        :params vm_name: Name of defined vm
        :params mem: Enable suspend to memory
        :params disk: Enable suspend to disk
        """
        # Build a instance of class VMPMXML.
        pm = VMPMXML()
        pm.mem_enabled = mem
        pm.disk_enabled = disk
        # Set pm to the new instance.
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        vmxml.pm = pm
        vmxml.sync()

    @staticmethod
    def set_vm_vcpus(vm_name, value, current=None, virsh_instance=base.virsh):
        """
        Convenience method for updating 'vcpu' and 'current' attribute property
        of a defined VM

        :param vm_name: Name of defined vm to change vcpu elemnet data
        :param value: New data value, None to delete.
        :param current: New current value, None will not change current value
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        if value is not None:
            if current is not None:
                try:
                    current_int = int(current)
                except ValueError:
                    raise xcepts.LibvirtXMLError("Invalid 'current' value '%s'"
                                                 % current)
                if current_int > value:
                    raise xcepts.LibvirtXMLError(
                        "The cpu current value %s is larger than max number %s"
                        % (current, value))
                else:
                    vmxml['current_vcpu'] = current
            vmxml['vcpu'] = value  # call accessor method to change XML
        else:  # value is None
            del vmxml.vcpu
        vmxml.undefine()
        vmxml.define()
        # Temporary files for vmxml cleaned up automatically
        # when it goes out of scope here.

    @staticmethod
    def check_cpu_mode(mode):
        """
        Check input cpu mode invalid or not.

        :param mode: the mode of cpu:'host-model'...
        """
        # Possible values for the mode attribute are:
        # "custom", "host-model", "host-passthrough"
        cpu_mode = ["custom", "host-model", "host-passthrough"]
        if mode.strip() not in cpu_mode:
            raise xcepts.LibvirtXMLError(
                "The cpu mode '%s' is invalid!" % mode)

    def get_disk_all(self):
        """
        Return VM's disk from XML definition, None if not set
        """
        disk_nodes = self.xmltreefile.find('devices').findall('disk')
        disks = {}
        for node in disk_nodes:
            dev = node.find('target').get('dev')
            disks[dev] = node
        return disks

    @staticmethod
    def get_disk_source(vm_name, option="", virsh_instance=base.virsh):
        """
        Get block device  of a defined VM's disks.

        :param vm_name: Name of defined vm.
        :param option: extra option.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, option,
                                       virsh_instance=virsh_instance)
        disks = vmxml.get_disk_all()
        return disks.values()

    @staticmethod
    def get_disk_blk(vm_name, virsh_instance=base.virsh):
        """
        Get block device  of a defined VM's disks.

        :param vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        disks = vmxml.get_disk_all()
        return disks.keys()

    @staticmethod
    def get_disk_count(vm_name, virsh_instance=base.virsh):
        """
        Get count of VM's disks.

        :param vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        disks = vmxml.get_disk_all()
        if disks is not None:
            return len(disks)
        return 0

    @staticmethod
    def get_disk_attr(vm_name, target, tag, attr, virsh_instance=base.virsh):
        """
        Get value of disk tag attribute for a given target dev.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        attr_value = None
        try:
            disk = vmxml.get_disk_all()[target]
            if tag in ["driver", "boot", "address", "alias", "source"]:
                attr_value = disk.find(tag).get(attr)
        except AttributeError:
            logging.error("No %s/%s found.", tag, attr)

        return attr_value

    @staticmethod
    def check_disk_exist(vm_name, disk_src, virsh_instance=base.virsh):
        """
        Check if given disk exist in VM.

        :param vm_name: Domain name.
        :param disk_src: Domian disk source path or darget dev.
        :return: True/False
        """
        found = False
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        if not vmxml.get_disk_count(vm_name, virsh_instance=virsh_instance):
            raise xcepts.LibvirtXMLError("No disk in domain %s." % vm_name)
        blk_list = vmxml.get_disk_blk(vm_name, virsh_instance=virsh_instance)
        disk_list = vmxml.get_disk_source(vm_name, virsh_instance=virsh_instance)
        try:
            file_list = []
            for disk in disk_list:
                file_list.append(disk.find('source').get('file'))
        except AttributeError:
            logging.debug("No 'file' type disk.")
        if disk_src in file_list + blk_list:
            found = True
        return found

    @staticmethod
    def check_disk_type(vm_name, disk_src, disk_type, virsh_instance=base.virsh):
        """
        Check if disk type is correct in VM

        :param vm_name: Domain name.
        :param disk_src: Domain disk source path
        :param disk_type: Domain disk type
        :return: True/False
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        if not vmxml.get_disk_count(vm_name, virsh_instance=virsh_instance):
            raise xcepts.LibvirtXMLError("No disk in domain %s." % vm_name)
        disks = vmxml.get_disk_source(vm_name, virsh_instance=virsh_instance)

        found = False
        try:
            for disk in disks:
                disk_dev = ""
                if disk_type == "file":
                    disk_dev = disk.find('source').get('file')
                elif disk_type == "block":
                    disk_dev = disk.find('source').get('dev')
                if disk_src == disk_dev:
                    found = True
        except AttributeError:
            logging.debug("No '%s' type disk." % disk_type)

        return found

    @staticmethod
    def get_disk_serial(vm_name, disk_target, virsh_instance=base.virsh):
        """
        Get disk serial in VM

        :param vm_name: Domain name.
        :param disk_target: Domain disk target
        :return: disk serial
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        if not vmxml.get_disk_count(vm_name, virsh_instance=virsh_instance):
            raise xcepts.LibvirtXMLError("No disk in domain %s." % vm_name)
        try:
            disk = vmxml.get_disk_all()[disk_target]
        except KeyError:
            raise xcepts.LibvirtXMLError("Wrong disk target:%s." % disk_target)
        serial = ""
        try:
            serial = disk.find("serial").text
        except AttributeError:
            logging.debug("No serial assigned.")

        return serial

    @staticmethod
    def get_disk_address(vm_name, disk_target, virsh_instance=base.virsh):
        """
        Get disk address in VM

        :param vm_name: Domain name.
        :param disk_target: Domain disk target
        :return: disk address
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        if not vmxml.get_disk_count(vm_name, virsh_instance=virsh_instance):
            raise xcepts.LibvirtXMLError("No disk in domain %s." % vm_name)
        try:
            disk = vmxml.get_disk_all()[disk_target]
        except KeyError:
            raise xcepts.LibvirtXMLError("Wrong disk target:%s." % disk_target)
        address_str = ""
        try:
            disk_bus = disk.find("target").get("bus")
            address = disk.find("address")
            if disk_bus == "virtio":
                add_type = address.get("type")
                add_domain = address.get("domain")
                add_bus = address.get("bus")
                add_slot = address.get("slot")
                add_func = address.get("function")
                address_str = ("%s:%s.%s.%s.%s"
                               % (add_type, add_domain, add_bus,
                                  add_slot, add_func))
            elif disk_bus in ["ide", "scsi"]:
                bus = address.get("bus")
                target = address.get("target")
                unit = address.get("unit")
                address_str = "%s:%s.%s.%s" % (disk_bus, bus, target, unit)
        except AttributeError, e:
            raise xcepts.LibvirtXMLError("Get wrong attribute: %s" % str(e))
        return address_str

    @staticmethod
    def get_numa_memory_params(vm_name, virsh_instance=base.virsh):
        """
        Return VM's numa memory setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        return vmxml.numa_memory

    @staticmethod
    def get_numa_memnode_params(vm_name, virsh_instance=base.virsh):
        """
        Return VM's numa memnode setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        return vmxml.numa_memnode

    def get_primary_serial(self):
        """
        Get a dict with primary serial features.
        """
        xmltreefile = self.__dict_get__('xml')
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
    def set_primary_serial(vm_name, dev_type, port, path=None,
                           virsh_instance=base.virsh):
        """
        Set primary serial's features of vm_name.

        :param vm_name: Name of defined vm to set primary serial.
        :param dev_type: the type of ``serial:pty,file...``
        :param port: the port of serial
        :param path: the path of serial, it is not necessary for pty
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        xmltreefile = vmxml.__dict_get__('xml')
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
                pass  # Element not found, already removed.
        xmltreefile.write()
        vmxml.set_xml(xmltreefile.name)
        vmxml.undefine()
        vmxml.define()

    def get_agent_channels(self):
        """
        Get all qemu guest agent channels
        """
        channels = self.xmltreefile.findall("./devices/channel")
        ga_channels = []
        for channel in channels:
            target = channel.find('./target')
            if target is not None:
                name = target.get('name')
                if name and name.startswith("org.qemu.guest_agent"):
                    ga_channels.append(channel)
        return ga_channels

    def set_agent_channel(self, src_path=None,
                          tgt_name='org.qemu.guest_agent.0',
                          ignore_exist=False):
        """
        Add a channel for guest agent if non exists.

        :param src_path: Source path of the channel
        :param tgt_name: Target name of the channel
        :param ignore_exist: Whether add a channel even if another already exists.
        """
        if not ignore_exist and self.get_agent_channels():
            logging.debug("Guest agent channel already exists")
            return

        if not src_path:
            src_path = '/var/lib/libvirt/qemu/%s-guest.agent' % self.vm_name
        channel = self.get_device_class('channel')(type_name='unix')
        channel.add_source(mode='bind', path=src_path)
        channel.add_target(type='virtio', name=tgt_name)
        self.devices = self.devices.append(channel)

    def remove_agent_channels(self):
        """
        Delete all channels for guest agent
        """
        for channel in self.get_agent_channels():
            self.xmltreefile.remove(channel)

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
    def get_iface_by_mac(vm_name, mac, virsh_instance=base.virsh):
        """
        Get the interface if mac is matched.

        :param vm_name: Name of defined vm.
        :param mac: a mac address.
        :return: return a dict include main interface's features
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        interfaces = vmxml.get_iface_all()
        try:
            interface = interfaces[mac]
        except KeyError:
            interface = None
        if interface is not None:  # matched mac exists.
            iface_type = interface.get('type')
            source = interface.find('source').get(iface_type)
            features = {}
            features['type'] = iface_type
            features['mac'] = mac
            features['source'] = source
            return features
        else:
            return None

    @staticmethod
    def get_iface_dev(vm_name, virsh_instance=base.virsh):
        """
        Return VM's interface device from XML definition, None if not set
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        ifaces = vmxml.get_iface_all()
        if ifaces:
            return ifaces.keys()
        return None

    @staticmethod
    def get_first_mac_by_name(vm_name, virsh_instance=base.virsh):
        """
        Convenience method for getting first mac of a defined VM

        :param: vm_name: Name of defined vm to get mac
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        xmltreefile = vmxml.__dict_get__('xml')
        try:
            iface = xmltreefile.find('devices').find('interface')
            return iface.find('mac').get('address')
        except AttributeError:
            return None

    @staticmethod
    def get_iftune_params(vm_name, options="", virsh_instance=base.virsh):
        """
        Return VM's interface tuning setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, options=options,
                                       virsh_instance=virsh_instance)
        xmltreefile = vmxml.__dict_get__('xml')
        iftune_params = {}
        bandwidth = None
        try:
            bandwidth = xmltreefile.find('devices/interface/bandwidth')
            try:
                iftune_params['inbound'] = bandwidth.find(
                    'inbound').get('average')
                iftune_params['outbound'] = bandwidth.find(
                    'outbound').get('average')
            except AttributeError:
                logging.error("Can't find <inbound> or <outbound> element")
        except AttributeError:
            logging.error("Can't find <bandwidth> element")

        return iftune_params

    def get_net_all(self):
        """
        Return VM's net from XML definition, None if not set
        """
        xmltreefile = self.__dict_get__('xml')
        net_nodes = xmltreefile.find('devices').findall('interface')
        nets = {}
        for node in net_nodes:
            dev = node.find('target').get('dev')
            nets[dev] = node
        return nets

    @staticmethod
    def set_multiqueues(vm_name, queues, index=0):
        """
        Set multiqueues for interface.

        :param queues: the count of queues for interface
        :param index: the index of interface
        """
        driver_params = {'name': "vhost", 'queues': queues}
        vmxml = VMXML.new_from_dumpxml(vm_name)
        nets = vmxml.__dict_get__('xml').find('devices').findall('interface')
        if index >= len(nets):
            raise xcepts.LibvirtXMLError("Couldn't find %s-th interface for %s"
                                         % (index, vm_name))
        net = nets[index]
        iface = vmxml.get_device_class('interface').new_from_element(net)
        iface.model = "virtio"
        iface.driver = iface.new_driver(driver_attr=driver_params)
        # Update devices: Remove all interfaces and attach new one
        vmxml.__dict_get__('xml').find('devices').remove(net)
        vmxml.devices = vmxml.devices.append(iface)
        vmxml.sync()

    # TODO re-visit this method after the libvirt_xml.devices.interface module
    #     is implemented
    @staticmethod
    def get_net_dev(vm_name):
        """
        Get net device of a defined VM's nets.

        :param vm_name: Name of defined vm.
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        nets = vmxml.get_net_all()
        if nets is not None:
            return nets.keys()
        return None

    @staticmethod
    def set_cpu_mode(vm_name, mode='host-model'):
        """
        Set cpu's mode of VM.

        :param vm_name: Name of defined vm to set cpu mode.
        :param mode: the mode of cpu:'host-model'...
        """
        vmxml = VMXML.new_from_dumpxml(vm_name)
        vmxml.check_cpu_mode(mode)
        xmltreefile = vmxml.__dict_get__('xml')
        try:
            cpu = xmltreefile.find('/cpu')
            logging.debug("Current cpu mode is '%s'!", cpu.get('mode'))
            cpu.set('mode', mode)
        except AttributeError:
            logging.debug("Can not find any cpu, now create one.")
            cpu = xml_utils.ElementTree.SubElement(xmltreefile.getroot(),
                                                   'cpu', {'mode': mode})
        xmltreefile.write()
        vmxml.undefine()
        vmxml.define()

    def add_device(self, value):
        """
        Add a device into VMXML.

        :param value: instance of device in libvirt_xml/devices/
        """
        devices = self.get_devices()
        for device in devices:
            if device == value:
                logging.debug("Device %s is already in VM %s.", value, self)
                return
        devices.append(value)
        self.set_devices(devices)

    def del_device(self, value, by_tag=False):
        """
        Remove a device from VMXML

        :param value: instance of device in libvirt_xml/devices/ or device tag
        :param by_tag: Boolean value. True for delete device by tag name
        """
        devices = self.get_devices()
        not_found = True
        for device in devices:
            device_value = device
            if by_tag:
                device_value = device.device_tag
            if device_value == value:
                not_found = False
                devices.remove(device)
                break
        if not_found:
            logging.debug("Device %s does not exist in VM %s.", value, self)
            return
        self.set_devices(devices)

    @staticmethod
    def add_security_info(vmxml, passwd):
        """
        Add passwd for graphic

        :param vmxml: instance of VMXML
        :param passwd: Password you want to set
        """
        devices = vmxml.devices
        graphics_index = devices.index(devices.by_device_tag('graphics')[0])
        graphics = devices[graphics_index]
        graphics.passwd = passwd
        vmxml.devices = devices
        vmxml.define()

    def get_graphics_devices(self, type_name=""):
        """
        Get all graphics devices or desired type graphics devices

        :param type_name: graphic type, vnc or spice
        """
        devices = self.get_devices()
        graphics_devices = devices.by_device_tag('graphics')
        graphics_list = []
        for graphics_device in graphics_devices:
            graphics_index = devices.index(graphics_device)
            graphics = devices[graphics_index]
            if not type_name:
                graphics_list.append(graphics)
            elif graphics.type_name == type_name:
                graphics_list.append(graphics)
        return graphics_list

    def remove_all_graphics(self):
        """
        Remove all graphics devices.
        """
        self.remove_all_device_by_type('graphics')

    def remove_all_device_by_type(self, device_type):
        """
        Remove all devices of a given type.

        :param type: Type name for devices should be removed.
        """
        try:
            self.xmltreefile.remove_by_xpath(
                '/devices/%s' % device_type,
                remove_all=True,
            )
        except (AttributeError, TypeError):
            pass  # Element already doesn't exist
        self.xmltreefile.write()

    def add_hostdev(self, source_address, mode='subsystem',
                    hostdev_type='pci',
                    managed='yes'):
        """
        Add a hostdev device to guest.

        :param source_address: A dict include slot, function, bus, domain
        """
        dev = self.get_device_class('hostdev')()
        dev.mode = mode
        dev.hostdev_type = hostdev_type
        dev.managed = managed
        dev.source_address = dev.new_source_address(**source_address)
        self.add_device(dev)

    @staticmethod
    def get_blkio_params(vm_name, options="", virsh_instance=base.virsh):
        """
        Return VM's block I/O setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, options=options,
                                       virsh_instance=virsh_instance)
        xmltreefile = vmxml.__dict_get__('xml')
        blkio_params = {}
        try:
            blkio = xmltreefile.find('blkiotune')
            try:
                blkio_params['weight'] = blkio.find('weight').text
            except AttributeError:
                logging.error("Can't find <weight> element")
        except AttributeError:
            logging.error("Can't find <blkiotune> element")

        if blkio and blkio.find('device'):
            blkio_params['device_weights_path'] = \
                blkio.find('device').find('path').text
            blkio_params['device_weights_weight'] = \
                blkio.find('device').find('weight').text

        return blkio_params

    @staticmethod
    def get_blkdevio_params(vm_name, options="", virsh_instance=base.virsh):
        """
        Return VM's block I/O tuning setting from XML definition
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, options=options,
                                       virsh_instance=virsh_instance)
        xmltreefile = vmxml.__dict_get__('xml')
        blkdevio_params = {}
        iotune = None
        blkdevio_list = ['total_bytes_sec', 'read_bytes_sec',
                         'write_bytes_sec', 'total_iops_sec',
                         'read_iops_sec', 'write_iops_sec']

        # Initialize all of arguments to zero
        for k in blkdevio_list:
            blkdevio_params[k] = 0

        try:
            iotune = xmltreefile.find('/devices/disk/iotune')
            for k in blkdevio_list:
                if iotune.findall(k):
                    blkdevio_params[k] = int(iotune.find(k).text)
        except AttributeError:
            xcepts.LibvirtXMLError("Can't find <iotune> element")

        return blkdevio_params

    @staticmethod
    def set_memoryBacking_tag(vm_name, hpgs=True, nosp=False, locked=False,
                              virsh_instance=base.virsh):
        """
        let the guest using hugepages.
        """
        # Create a new memoryBacking tag
        mb_xml = VMMemBackingXML()
        mb_xml.nosharepages = nosp
        mb_xml.locked = locked
        if hpgs:
            hpgs = VMHugepagesXML()
            mb_xml.hugepages = hpgs
        # Set memoryBacking to the new instance.
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        vmxml.mb = mb_xml
        vmxml.sync()

    @staticmethod
    def del_memoryBacking_tag(vm_name, virsh_instance=base.virsh):
        """
        Remove the memoryBacking tag from a domain
        """
        vmxml = VMXML.new_from_dumpxml(vm_name, virsh_instance=virsh_instance)
        try:
            vmxml.xmltreefile.remove_by_xpath("/memoryBacking", remove_all=True)
            vmxml.sync()
        except (AttributeError, TypeError):
            pass  # Element already doesn't exist


class VMCPUXML(base.LibvirtXMLBase):

    """
    Higher-level manipulations related to VM's XML(CPU)
    """

    # Must copy these here or there will be descriptor problems
    __slots__ = ('model', 'vendor', 'feature_list', 'mode', 'match',
                 'fallback', 'topology', 'numa_cell')

    def __init__(self, virsh_instance=base.virsh):
        """
        Create new VMCPU XML instance
        """
        # The set action is for test.
        accessors.XMLAttribute(property_name="mode",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='cpu',
                               attribute='mode')
        accessors.XMLAttribute(property_name="match",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='cpu',
                               attribute='match')
        accessors.XMLElementText(property_name="model",
                                 libvirtxml=self,
                                 forbidden=[],
                                 parent_xpath='/',
                                 tag_name='model')
        accessors.XMLElementText(property_name="vendor",
                                 libvirtxml=self,
                                 forbidden=[],
                                 parent_xpath='/',
                                 tag_name='vendor')
        accessors.XMLAttribute(property_name="fallback",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='model',
                               attribute='fallback')
        accessors.XMLElementDict(property_name="topology",
                                 libvirtxml=self,
                                 forbidden=[],
                                 parent_xpath='/',
                                 tag_name='topology')
        accessors.XMLElementList(property_name="numa_cell",
                                 libvirtxml=self,
                                 parent_xpath='numa',
                                 marshal_from=self.marshal_from_cell,
                                 marshal_to=self.marshal_to_cell)
        # This will skip self.get_feature_list() defined below
        accessors.AllForbidden(property_name="feature_list",
                               libvirtxml=self)
        super(VMCPUXML, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<cpu/>'

    @staticmethod
    def marshal_from_cell(item, index, libvirtxml):
        """
        Convert a dict to cell tag and attributes.
        """
        del index
        del libvirtxml
        if not isinstance(item, dict):
            raise xcepts.LibvirtXMLError("Expected a dictionary of cell "
                                         "attributes, not a %s"
                                         % str(item))
        return ('cell', dict(item))

    @staticmethod
    def marshal_to_cell(tag, attr_dict, index, libvirtxml):
        """
        Convert a cell tag and attributes to a dict.
        """
        del index
        del libvirtxml
        if tag != 'cell':
            return None
        return dict(attr_dict)

    def get_feature_list(self):
        """
        Accessor method for feature_list property (in __slots__)
        """
        feature_list = []
        xmltreefile = self.__dict_get__('xml')
        for feature_node in xmltreefile.findall('/feature'):
            feature_list.append(feature_node)
        return feature_list

    def get_feature(self, num):
        """
        Get a feature element from feature list by number

        :return: Feature element
        """
        count = len(self.feature_list)
        try:
            num = int(num)
            return self.feature_list[num]
        except (ValueError, TypeError):
            raise xcepts.LibvirtXMLError("Invalid feature number %s" % num)
        except IndexError:
            raise xcepts.LibvirtXMLError("Only %d feature(s)" % count)

    def get_feature_name(self, num):
        """
        Get feature name

        :param num: Number in feature list
        :return: Feature name
        """
        return self.get_feature(num).get('name')

    def get_feature_policy(self, num):
        """
        Get feature policy

        :param num: Number in feature list
        :return: Feature policy
        """
        return self.get_feature(num).get('policy')

    def remove_feature(self, num):
        """
        Remove a feature from xml

        :param num: Number in feature list
        """
        xmltreefile = self.__dict_get__('xml')
        node = xmltreefile.getroot()
        node.remove(self.get_feature(num))

    @staticmethod
    def check_feature_name(value):
        """
        Check feature name valid or not.

        :param value: Feature name
        :return: True if check pass
        """
        sys_feature = []
        cpu_xml_file = open('/proc/cpuinfo', 'r')
        for line in cpu_xml_file.readline():
            if line.find('flags') != -1:
                feature_names = line.split(':')[1].strip()
                sys_sub_feature = feature_names.split(' ')
                sys_feature = list(set(sys_feature + sys_sub_feature))
        cpu_xml_file.close()
        return (value in sys_feature)

    def set_feature(self, num, name='', policy=''):
        """
        Set feature name (and policy) to xml

        :param num: Number in feature list
        :param name: New feature name
        :param policy: New feature policy
        """
        feature_set_node = self.get_feature(num)
        if name:
            feature_set_node.set('name', name)
        if policy:
            feature_set_node.set('policy', policy)

    def add_feature(self, name, policy=''):
        """
        Add a feature element to xml

        :param name: New feature name
        :param policy: New feature policy
        """
        xmltreefile = self.__dict_get__('xml')
        node = xmltreefile.getroot()
        feature_node = {'name': name}
        if policy:
            feature_node.update({'policy': policy})
        xml_utils.ElementTree.SubElement(node, 'feature', feature_node)


class VMClockXML(VMXML):

    """
    Higher-level manipulations related to VM's XML(Clock)
    """

    # Must copy these here or there will be descriptor problems
    __slots__ = ('offset', 'timezone', 'adjustment', 'timers')

    def __init__(self, virsh_instance=base.virsh, offset="utc"):
        """
        Create new VMClock XML instance
        """
        # The set action is for test.
        accessors.XMLAttribute(property_name="offset",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='clock',
                               attribute='offset')
        accessors.XMLAttribute(property_name="timezone",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='clock',
                               attribute='timezone')
        accessors.XMLAttribute(property_name="adjustment",
                               libvirtxml=self,
                               forbidden=[],
                               parent_xpath='/',
                               tag_name='clock',
                               attribute='adjustment')
        accessors.XMLElementList(property_name="timers",
                                 libvirtxml=self,
                                 forbidden=[],
                                 parent_xpath="/clock",
                                 marshal_from=self.marshal_from_timer,
                                 marshal_to=self.marshal_to_timer)
        super(VMClockXML, self).__init__(virsh_instance=virsh_instance)
        # Set default offset for clock
        self.offset = offset

    def from_dumpxml(self, vm_name, virsh_instance=base.virsh):
        """Helper to load xml from domain."""
        self.xml = VMXML.new_from_dumpxml(vm_name,
                                          virsh_instance=virsh_instance).xml

    # Sub-element of clock
    class TimerXML(VMXML):

        """Timer element of clock"""

        __slots__ = ('name', 'present', 'track', 'tickpolicy', 'frequency',
                     'mode', 'catchup_threshold', 'catchup_slew',
                     'catchup_limit')

        def __init__(self, virsh_instance=base.virsh, timer_name="tsc"):
            """
            Create new TimerXML instance
            """
            # The set action is for test.
            accessors.XMLAttribute(property_name="name",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='name')
            accessors.XMLAttribute(property_name="present",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='present')
            accessors.XMLAttribute(property_name="track",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='track')
            accessors.XMLAttribute(property_name="tickpolicy",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='tickpolicy')
            accessors.XMLAttribute(property_name="frequency",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='frequency')
            accessors.XMLAttribute(property_name="mode",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock',
                                   tag_name='timer',
                                   attribute='mode')
            accessors.XMLAttribute(property_name="catchup_threshold",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock/timer',
                                   tag_name='catchup',
                                   attribute='threshold')
            accessors.XMLAttribute(property_name="catchup_slew",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock/timer',
                                   tag_name='catchup',
                                   attribute='slew')
            accessors.XMLAttribute(property_name="catchup_limit",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/clock/timer',
                                   tag_name='catchup',
                                   attribute='limit')
            super(VMClockXML.TimerXML, self).__init__(virsh_instance=virsh_instance)
            # name is mandatory for timer
            self.name = timer_name

        def update(self, attr_dict):
            for attr, value in attr_dict.items():
                setattr(self, attr, value)

    @staticmethod
    def marshal_from_timer(item, index, libvirtxml):
        """Convert a TimerXML instance into tag + attributes"""
        del index
        del libvirtxml
        timer = item.xmltreefile.find("clock/timer")
        try:
            return (timer.tag, dict(timer.items()))
        except AttributeError:  # Didn't find timer
            raise xcepts.LibvirtXMLError("Expected a list of timer "
                                         "instances, not a %s" % str(item))

    @staticmethod
    def marshal_to_timer(tag, attr_dict, index, libvirtxml):
        """Convert a tag + attributes to a TimerXML instance"""
        del index
        if tag == 'timer':
            newone = VMClockXML.TimerXML(virsh_instance=libvirtxml.virsh)
            newone.update(attr_dict)
            return newone
        else:
            return None


class VMCPUTuneXML(base.LibvirtXMLBase):

    """
    CPU tuning tag XML class

    Elements:
        vcpupins:             list of dict - vcpu, cpuset
        emulatorpin:          attribute    - cpuset
        shares:               int
        period:               int
        quota:                int
        emulator_period:      int
        emulator_quota:       int
    """

    __slots__ = ('vcpupins', 'emulatorpin', 'shares', 'period', 'quota',
                 'emulator_period', 'emulator_quota')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementList('vcpupins', self, parent_xpath='/',
                                 marshal_from=self.marshal_from_vcpupins,
                                 marshal_to=self.marshal_to_vcpupins)
        accessors.XMLAttribute('emulatorpin', self, parent_xpath='/',
                               tag_name='emulatorpin', attribute='cpuset')
        for slot in self.__all_slots__:
            if slot in ('shares', 'period', 'quota', 'emulator_period',
                        'emulator_quota'):
                accessors.XMLElementInt(slot, self, parent_xpath='/',
                                        tag_name=slot)
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<cputune/>'

    @staticmethod
    def marshal_from_vcpupins(item, index, libvirtxml):
        """
        Convert a dict to vcpupin tag and attributes.
        """
        del index
        del libvirtxml
        if not isinstance(item, dict):
            raise xcepts.LibvirtXMLError("Expected a dictionary of host "
                                         "attributes, not a %s"
                                         % str(item))
        return ('vcpupin', dict(item))

    @staticmethod
    def marshal_to_vcpupins(tag, attr_dict, index, libvirtxml):
        """
        Convert a vcpupin tag and attributes to a dict.
        """
        del index
        del libvirtxml
        if tag != 'vcpupin':
            return None
        return dict(attr_dict)


class VMOSXML(base.LibvirtXMLBase):

    """
    Class to access <os> tag of domain XML.

    Elements:
        type:         text attributes - arch, machine
        loader:       path
        boots:        list attributes - dev
        bootmenu:          attributes - enable
        smbios:            attributes - mode
        bios:              attributes - useserial, rebootTimeout
        init:         text
        bootloader:   text
        bootloader_args:   text
        kernel:       text
        initrd:       text
        cmdline:      text
        dtb:          text
    TODO:
        initargs:     list
    """

    __slots__ = ('type', 'arch', 'machine', 'loader', 'boots', 'bootmenu_enable',
                 'smbios_mode', 'bios_useserial', 'bios_reboot_timeout', 'init',
                 'bootloader', 'bootloader_args', 'kernel', 'initrd', 'cmdline',
                 'dtb', 'initargs')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementText('type', self, parent_xpath='/',
                                 tag_name='type')
        accessors.XMLElementText('loader', self, parent_xpath='/',
                                 tag_name='loader')
        accessors.XMLAttribute('arch', self, parent_xpath='/',
                               tag_name='type', attribute='arch')
        accessors.XMLAttribute('machine', self, parent_xpath='/',
                               tag_name='type', attribute='machine')
        accessors.XMLElementList('boots', self, parent_xpath='/',
                                 marshal_from=self.marshal_from_boots,
                                 marshal_to=self.marshal_to_boots)
        accessors.XMLAttribute('bootmenu_enable', self, parent_xpath='/',
                               tag_name='bootmenu', attribute='enable')
        accessors.XMLAttribute('smbios_mode', self, parent_xpath='/',
                               tag_name='smbios', attribute='mode')
        accessors.XMLAttribute('bios_useserial', self, parent_xpath='/',
                               tag_name='bios', attribute='useserial')
        accessors.XMLAttribute('bios_reboot_timeout', self, parent_xpath='/',
                               tag_name='bios', attribute='rebootTimeout')
        accessors.XMLElementText('bootloader', self, parent_xpath='/',
                                 tag_name='bootloader')
        accessors.XMLElementText('bootloader_args', self, parent_xpath='/',
                                 tag_name='bootloader_args')
        accessors.XMLElementText('kernel', self, parent_xpath='/',
                                 tag_name='kernel')
        accessors.XMLElementText('initrd', self, parent_xpath='/',
                                 tag_name='initrd')
        accessors.XMLElementText('cmdline', self, parent_xpath='/',
                                 tag_name='cmdline')
        accessors.XMLElementText('dtb', self, parent_xpath='/',
                                 tag_name='dtb')
        accessors.XMLElementText('init', self, parent_xpath='/',
                                 tag_name='init')
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<os/>'

    @staticmethod
    def marshal_from_boots(item, index, libvirtxml):
        """
        Convert a string to boot tag and attributes.
        """
        del index
        del libvirtxml
        return ('boot', {'dev': item})

    @staticmethod
    def marshal_to_boots(tag, attr_dict, index, libvirtxml):
        """
        Convert a boot tag and attributes to a string.
        """
        del index
        del libvirtxml
        if tag != 'boot':
            return None
        return attr_dict['dev']


class VMPMXML(base.LibvirtXMLBase):

    """
    VM power management tag XML class

    Elements:
        suspend-to-disk:        attribute    - enabled
        suspend-to-mem:         attribute    - enabled
    """

    __slots__ = ('disk_enabled', 'mem_enabled')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLAttribute('disk_enabled', self, parent_xpath='/',
                               tag_name='suspend-to-disk', attribute='enabled')
        accessors.XMLAttribute('mem_enabled', self, parent_xpath='/',
                               tag_name='suspend-to-mem', attribute='enabled')
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<pm/>'


class VMFeaturesXML(base.LibvirtXMLBase):

    """
    Class to access <features> tag of domain XML.

    Elements:
        feature_list       list of top level element
        hyperv_relaxed:    attribute - state
        hyperv_vapic:      attribute - state
        hyperv_spinlocks:  attributes - state, retries
        kvm_hidden:        attribute - state
        pvspinlock:        attribute - state
    """

    __slots__ = ('feature_list', 'hyperv_relaxed_state', 'hyperv_vapic_state',
                 'hyperv_spinlocks_state', 'hyperv_spinlocks_retries',
                 'kvm_hidden_state', 'pvspinlock_state')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLAttribute(property_name='hyperv_relaxed_state',
                               libvirtxml=self,
                               parent_xpath='/hyperv',
                               tag_name='relaxed',
                               attribute='state')
        accessors.XMLAttribute(property_name='hyperv_vapic_state',
                               libvirtxml=self,
                               parent_xpath='/hyperv',
                               tag_name='vapic',
                               attribute='state')
        accessors.XMLAttribute(property_name='hyperv_spinlocks_state',
                               libvirtxml=self,
                               parent_xpath='/hyperv',
                               tag_name='spinlocks',
                               attribute='state')
        accessors.XMLAttribute(property_name='hyperv_spinlocks_retries',
                               libvirtxml=self,
                               parent_xpath='/hyperv',
                               tag_name='spinlocks',
                               attribute='retries')
        accessors.XMLAttribute(property_name='kvm_hidden_state',
                               libvirtxml=self,
                               parent_xpath='/kvm',
                               tag_name='hidden',
                               attribute='state')
        accessors.XMLAttribute(property_name='pvspinlock_state',
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='pvspinlock',
                               attribute='state')
        accessors.AllForbidden(property_name="feature_list",
                               libvirtxml=self)
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<features/>'

    def get_feature_list(self):
        """
        Return all features(top level elements) in xml
        """
        feature_list = []
        root = self.__dict_get__('xml').getroot()
        for feature in root:
            feature_list.append(feature.tag)
        return feature_list

    def has_feature(self, name):
        """
        Return true if the given feature exist in xml
        """
        return name in self.get_feature_list()

    def add_feature(self, name, attr_name='', attr_value=''):
        """
        Add a feature element to xml

        :params name: Feature name
        """
        if self.has_feature(name):
            logging.debug("Feature %s already exist, so remove it", name)
            self.remove_feature(name)
        root = self.__dict_get__('xml').getroot()
        new_attr = {}
        if attr_name:
            new_attr = {attr_name: attr_value}
        xml_utils.ElementTree.SubElement(root, name, new_attr)

    def remove_feature(self, name):
        """
        Remove a feature element from xml

        :params name: Feature name
        """
        root = self.__dict_get__('xml').getroot()
        remove_feature = root.find(name)
        if remove_feature is None:
            logging.error("Feature %s doesn't exist", name)
        else:
            root.remove(remove_feature)


# Sub-element of memoryBacking
class VMHugepagesXML(VMXML):

    """hugepages element"""

    __slots__ = ('pages',)

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementList('pages',
                                 libvirtxml=self,
                                 forbidden=[],
                                 parent_xpath="/",
                                 marshal_from=self.marshal_from_page,
                                 marshal_to=self.marshal_to_page)
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<hugepages/>'

    # Sub-element of hugepages
    class PageXML(VMXML):

        """Page element of hugepages"""

        __slots__ = ('size', 'unit', 'nodeset')

        def __init__(self, virsh_instance=base.virsh):
            """
            Create new PageXML instance
            """
            accessors.XMLAttribute(property_name="size",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/hugepages',
                                   tag_name='page',
                                   attribute='size')
            accessors.XMLAttribute(property_name="unit",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/hugepages',
                                   tag_name='page',
                                   attribute='unit')
            accessors.XMLAttribute(property_name="nodeset",
                                   libvirtxml=self,
                                   forbidden=[],
                                   parent_xpath='/hugepages',
                                   tag_name='page',
                                   attribute='nodeset')
            super(VMHugepagesXML.PageXML, self).__init__(virsh_instance=virsh_instance)

        def update(self, attr_dict):
            for attr, value in attr_dict.items():
                setattr(self, attr, value)

    @staticmethod
    def marshal_from_page(item, index, libvirtxml):
        """Convert a PageXML instance into tag + attributes"""
        del index
        del libvirtxml
        page = item.xmltreefile.find("/hugepages/page")
        try:
            return (page.tag, dict(page.items()))
        except AttributeError:  # Didn't find page
            raise xcepts.LibvirtXMLError("Expected a list of page "
                                         "instances, not a %s" % str(item))

    @staticmethod
    def marshal_to_page(tag, attr_dict, index, libvirtxml):
        """Convert a tag + attributes to a PageXML instance"""
        del index
        if tag == 'page':
            newone = VMHugepagesXML.PageXML(virsh_instance=libvirtxml.virsh)
            newone.update(attr_dict)
            return newone
        else:
            return None


class VMMemBackingXML(VMXML):

    """
    memoryBacking tag XML class

    Elements:
        hugepages
        nosharepages
        locked
    """

    __slots__ = ('hugepages', 'nosharepages', 'locked')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementNest(property_name='hugepages',
                                 libvirtxml=self,
                                 parent_xpath='/',
                                 tag_name='hugepages',
                                 subclass=VMHugepagesXML,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        for slot in ('nosharepages', 'locked'):
            accessors.XMLElementBool(slot, self, parent_xpath='/',
                                     tag_name=slot)
        super(self.__class__, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<memoryBacking/>'


class VMMemTuneXML(base.LibvirtXMLBase):

    """
    Memory Tuning tag XML class

    Element:
        hard_limit:            int
        hard_limit_unit:       attribute
        soft_limit:            int
        soft_limit_unit:       attribute
        swap_hard_limit:       int
        swap_limit_unit:       attribute
        min_guarantee:         int
        min_guarantee_unit:    attribute
    """

    __slots__ = ('hard_limit', 'soft_limit', 'swap_hard_limit', 'min_guarantee',
                 'hard_limit_unit', 'soft_limit_unit', 'swap_limit_unit',
                 'min_guarantee_unit')

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementInt(property_name='hard_limit',
                                libvirtxml=self,
                                parent_xpath='/',
                                tag_name='hard_limit')
        accessors.XMLAttribute(property_name="hard_limit_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='hard_limit',
                               attribute='unit')
        accessors.XMLElementInt(property_name='soft_limit',
                                libvirtxml=self,
                                parent_xpath='/',
                                tag_name='soft_limit')
        accessors.XMLAttribute(property_name="soft_limit_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='soft_limit',
                               attribute='unit')
        accessors.XMLElementInt(property_name='swap_hard_limit',
                                libvirtxml=self,
                                parent_xpath='/',
                                tag_name='swap_hard_limit')
        accessors.XMLAttribute(property_name="swap_limit_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='swap_hard_limit',
                               attribute='unit')
        accessors.XMLElementInt(property_name='min_guarantee',
                                libvirtxml=self,
                                parent_xpath='/',
                                tag_name='min_guarantee')
        accessors.XMLAttribute(property_name="min_guarantee_unit",
                               libvirtxml=self,
                               parent_xpath='/',
                               tag_name='min_guarantee',
                               attribute='unit')
        super(VMMemTuneXML, self).__init__(virsh_instance=virsh_instance)
        self.xml = '<memtune/>'
