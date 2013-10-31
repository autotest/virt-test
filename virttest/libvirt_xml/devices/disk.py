"""
disk device support class(es)

http://libvirt.org/formatdomain.html#elementsDisks
"""

from virttest.libvirt_xml import accessors, xcepts
from virttest.libvirt_xml.devices import base


class Disk(base.TypedDeviceBase):
    """
    Class for device of disk in VMXML.
    """
    # B/c the attribute name of path in source tag is
    # related with device type. We need a dict to store
    # the map from device type to source name.
    _device_type_2_source_tag = {'file':"file",
                                 'block':"dev",
                                 'dir':"dir",
                                 'network':"protocol"}

    __slots__ = base.TypedDeviceBase.__slots__ + ('type', 'device', 'source',
                                                  'target_dev', 'target_bus',)

    def __init__(self, type_name, virsh_instance=base.base.virsh):
        """
        Add some accessors for slot in __slots__.

        But we can not use the accessors tool for 'source' slot in __init__
        method. Beacause the xml file is not already loaded currently, then we
        can not get the 'type' of it. And the attribute name of source differs
        in different types. So we can not add a accessor for 'source' here.
        """
        super(Disk, self).__init__(device_tag='disk',
                                   type_name=type_name,
                                   virsh_instance=virsh_instance)
        accessors.XMLAttribute('type', self, parent_xpath='/',
                               tag_name='disk', attribute='type')
        accessors.XMLAttribute('device', self, parent_xpath='/',
                               tag_name='disk', attribute='device')
        accessors.XMLAttribute('target_dev', self, parent_xpath='/',
                               tag_name='target', attribute='dev')
        accessors.XMLAttribute('target_bus', self, parent_xpath='/',
                               tag_name='target', attribute='bus')
        # Init three super attribute to access source slot.
        self.super_set("source_getter", None)
        self.super_set("source_setter", None)
        self.super_set("source_delter", None)

    # Implement the accessor methods for source.
    def get_source(self):
        """
        Getter for source.
        """
        accessor = self.super_get("source_getter")
        if accessor is None:
            # First time to get source. Init a Getter for it.
            accessor = accessors.AccessorBase(operation="get",
                                              property_name="source",
                                              libvirtxml=self)
            self.super_set("source_getter", accessor)
        # Get the attribute name of source.
        source_tag = self._device_type_2_source_tag[self.type]
        element = accessor.element_by_parent(parent_xpath="/",
                                             tag_name=accessor.property_name,
                                             create=False)
        return element.get(source_tag, None)

    def set_source(self, value):
        """
        Setter for source.
        """
        accessor = self.super_get("source_setter")
        if accessor is None:
            # First time to set source.
            accessor = accessors.AccessorBase(operation="set",
                                              property_name="source",
                                              libvirtxml=self)
            self.super_set("source_setter", accessor)
        # Get the attribute name of source.
        source_tag = self._device_type_2_source_tag[self.type]
        element = accessor.element_by_parent(parent_xpath="/",
                                             tag_name=accessor.property_name,
                                             create=True)
        element.set(source_tag, str(value))
        accessor.xmltreefile().write()

    def del_source(self):
        """
        Delter for source.
        """
        accessor = self.super_get("source_delter")
        if accessor is None:
            accessor = accessors.AccessorBase(operation="del",
                                              property_name="source",
                                              libvirtxml=self)
            self.super_set("source_delter", accessor)
        # Get the attribute name of source.
        source_tag = self._device_type_2_source_tag[self.type]
        element = accessor.element_by_parent(parent_xpath="/",
                                         tag_name=accessor.property_name,
                                         create=False)
        try:
            del element.attrib[source_tag]
        except KeyError:
            pass  # already doesn't exist
        accessor.xmltreefile().write()
