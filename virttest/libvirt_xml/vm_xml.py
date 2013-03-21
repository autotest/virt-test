"""
Module simplifying manipulation of XML described at
http://libvirt.org/formatdomain.html
"""

import logging
from autotest.client.shared import error
from virttest import virsh
from virttest.libvirt_xml import base, accessors, xcepts

class VMXMLBase(base.LibvirtXMLBase):
    """
    Accessor methods for VMXML class properties (items in __slots__)

    Properties:
        hypervisor_type: virtual string, hypervisor type name
            get: return domain's type attribute value
            set: change domain type attribute value
            del: raise xcepts.LibvirtXMLError
        vm_name: virtual string, name of the vm
            get: return text value of name tag
            set: set text value of name tag
            del: raise xcepts.LibvirtXMLError
        uuid: virtual string, uuid string for vm
            get: return text value of uuid tag
            set: set text value for (new) uuid tag (unvalidated)
            del: remove uuid tag
        vcpu: virtual integer, number of vcpus
            get: returns integer of vcpu tag text value
            set: set integer of (new) vcpu tag text value
            del: removes vcpu tag
    """

    # Additional names of attributes and dictionary-keys instances may contain
    __slots__ = base.LibvirtXMLBase.__slots__ + ('hypervisor_type', 'vm_name',
                                                 'uuid', 'vcpu', 'max_mem',
                                                 'current_mem')


    def __init__(self, virsh_instance=virsh):
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
        super(VMXMLBase, self).__init__(virsh_instance)


class VMXML(VMXMLBase):
    """
    Higher-level manipulations related to VM's XML or guest/host state
    """

    # Must copy these here or there will be descriptor problems
    __slots__ = VMXMLBase.__slots__


    def __init__(self, virsh_instance=virsh, hypervisor_type='kvm'):
        """
        Create new VM XML instance
        """
        super(VMXML, self).__init__(virsh_instance)
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
    def vm_rename(vm, new_name, uuid=None, virsh_instance=virsh):
        """
        Rename a vm from its XML.

        @param vm: VM class type instance
        @param new_name: new name of vm
        @param uuid: new_vm's uuid, if None libvirt will generate.
        @return: a new VM instance
        """
        if vm.is_alive():
            vm.destroy(gracefully=True)
        vmxml = VMXML.new_from_dumpxml(vm.name, virsh_instance=virsh_instance)
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
            except:
                logging.error("Can't find <memory> element")
        except:
            logging.error("Can't find <numatune> element")

        return numa_params


    #TODO: Add function to create from xml_utils.TemplateXML()
    # def new_from_template(...)
