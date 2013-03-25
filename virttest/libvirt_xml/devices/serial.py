"""
Classes to support XML for serial devices
http://libvirt.org/formatdomain.html#elementCharSerial
"""

from virttest.libvirt_xml import xcepts
from virttest.libvirt_xml.devices import base, librarian


class Serial(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('source_path',
                                                  'target_port',
                                                  'target_type',
                                                  'target_address',
                                                  'protocol_type',
                                                  'source_connect',
                                                  'source_bind',
                                                  'source_seclabel', )

    def __init__(self, type_name='pty', virsh_instance=base.base.virsh):
        # host side
        base.accessors.XMLAttribute('source_path', self, parent_xpath='/',
                                    tag_name='source', attribute='path')
        # guest side
        base.accessors.XMLAttribute('target_port', self, parent_xpath='/',
                                    tag_name='target', attribute='port')
        # isa-serial (default) or usb-serial (w/ optional address sub-element)
        base.accessors.XMLAttribute('target_type', self, parent_xpath='/',
                                    tag_name='target', attribute='type')
        # network-based
        base.accessors.XMLAttribute('protocol_type', self, parent_xpath='/',
                                    tag_name='protocol', attribute='type')
        # SELinux (FIXME: do we need 'baselabel' or 'label' sub-element?)
        base.accessors.XMLAttribute('source_seclabel', self, parent_xpath='/',
                                    tag_name='source', attribute='seclabel')

        super(Serial, self).__init__(device_tag='serial', type_name=type_name,
                                     virsh_instance=virsh_instance)


    # Helper for removing any/all 'source path' elements
    def nuke_source_paths(self):
        # Don't assume there's only one
        del_list = []
        for source in self.xmltreefile.getiterator('source'):
            if source.get('path') is not None:
                # Avoid deleting elements while iterating
                del_list.append(source)
        for source in del_list:
            self.xmltreefile.remove(source)


    # Helper for locating source tags w/ particular mode attribute
    def source_mode_element(self, mode):
        for source in self.xmltreefile.getiterator('source'):
            if source.get('mode') == mode:
                return source
        raise xcepts.LibvirtXMLError("No connect-%s source element found"
                                     % mode)


    def get_target_address(self):
        target_address = self.xmltreefile.find('target/address')
        if target_address is not None:
            address_class = librarian.get('address')
            return address_class.new_from_element(target_address)
        else:
            return None


    def set_target_address(self, value):
        address_class = librarian.get('address')
        value_type = type(value)
        if not issubclass(value_type, address_class):
            raise xcepts.LibvirtXMLError("Target address must be "
                                         "Address class instance");
        target = self.xmltreefile.find('target')
        if target is not None:
            target.append(value.getroot())
        else:
            raise xcepts.LibvirtXMLError("No target element found for serial "
                                         "device: %s" % str(self))


    def del_target_address(self):
        try:
            self.xmltreefile.remove_by_xpath('target/address')
        except AttributeError:
            pass # already doesn't exist


    def get_source_connect(self):
        try:
            source_connect = self.source_mode_element('connect')
            return dict(source_connect.items())
        except xcepts.LibvirtXMLError:
            return None


    def set_source_connect(self, value):
        # Don't let these interfear
        nuke_source_paths()
        del self.source_connect # call del accessor
        base.base.xml_utils.ElementTree.SubElement(self.xmltreefile.getroot(),
                                                   'source', {'mode':'connct'},
                                                   **values)

    def del_source_connect(self):
        try:
            source_connect = self.source_mode_element('connect')
            self.xmltreefile.remove(source_connect)
        except xcepts.LibvirtXMLError:
            pass # already doesn't exist


    def get_source_bind(self):
        try:
            source_connect = self.source_mode_element('bind')
            return dict(source_connect.items())
        except xcepts.LibvirtXMLError:
            return None


    def set_source_bind(self, value):
        # Don't let these interfear
        nuke_source_paths()
        del self.source_bind # call del accessor
        base.base.xml_utils.ElementTree.SubElement(self.xmltreefile.getroot(),
                                                   'source', {'mode':'bind'},
                                                   **values)


    def del_source_bind(self):
        try:
            source_connect = self.source_mode_element('bind')
            self.xmltreefile.remove(source_connect)
        except xcepts.LibvirtXMLError:
            pass # already doesn't exist
