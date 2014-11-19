"""
interface device support class(es)

http://libvirt.org/formatdomain.html#elementsNICS
"""

from virttest.libvirt_xml import accessors
from virttest.libvirt_xml.devices import base, librarian


class Interface(base.TypedDeviceBase):

    __slots__ = ('source', 'mac_address', 'bandwidth',
                 'model', 'link_state',
                 'driver', 'address')

    def __init__(self, type_name, virsh_instance=base.base.virsh):
        super(Interface, self).__init__(device_tag='interface',
                                        type_name=type_name,
                                        virsh_instance=virsh_instance)
        accessors.XMLElementDict(property_name="source",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='source')
        accessors.XMLAttribute(property_name="mac_address",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='mac',
                               attribute='address')
        accessors.XMLAttribute(property_name="link_state",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='link',
                               attribute='state')
        accessors.XMLElementNest("bandwidth", self,
                                 parent_xpath='/',
                                 tag_name='bandwidth',
                                 subclass=self.Bandwidth,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLElementNest("driver", self,
                                 parent_xpath='/',
                                 tag_name='driver',
                                 subclass=self.Driver,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLAttribute(property_name="model",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='model',
                               attribute='type')
        accessors.XMLElementNest('address', self, parent_xpath='/',
                                 tag_name='address', subclass=self.Address,
                                 subclass_dargs={'type_name': 'drive',
                                                 'virsh_instance': virsh_instance})
    # For convenience
    Address = librarian.get('address')

    def new_bandwidth(self, **dargs):
        """
        Return a new interafce banwidth instance from dargs
        """
        new_one = self.Bandwidth(virsh_instance=self.virsh)
        for key, value in dargs.items():
            setattr(new_one, key, value)
        return new_one

    def new_driver(self, **dargs):
        """
        Return a new interafce driver instance from dargs
        """
        new_one = self.Driver(virsh_instance=self.virsh)
        for key, value in dargs.items():
            setattr(new_one, key, value)
        return new_one

    class Bandwidth(base.base.LibvirtXMLBase):

        """
        Interface bandwidth xml class.

        Properties:

        inbound:
            dict. Keys: average, peak, floor, burst
        outbound:
            dict. Keys: average, peak, floor, burst
        """
        __slots__ = ("inbound", "outbound")

        def __init__(self, virsh_instance=base.base.virsh):
            accessors.XMLElementDict("inbound", self, parent_xpath="/",
                                     tag_name="inbound")
            accessors.XMLElementDict("outbound", self, parent_xpath="/",
                                     tag_name="outbound")
            super(self.__class__, self).__init__(virsh_instance=virsh_instance)
            self.xml = '<bandwidth/>'

    class Driver(base.base.LibvirtXMLBase):

        """
        Interface Driver xml class.

        Properties:

        driver:
            dict.
        host:
            dict. Keys: csum, gso, tso4, tso6, ecn, ufo
        guest:
            dict. Keys: csum, gso, tso4, tso6, ecn, ufo
        """
        __slots__ = ("driver_attr", "driver_host", "driver_guest")

        def __init__(self, virsh_instance=base.base.virsh):
            accessors.XMLElementDict("driver_attr", self, parent_xpath="/",
                                     tag_name="driver")
            accessors.XMLElementDict("driver_host", self, parent_xpath="/",
                                     tag_name="host")
            accessors.XMLElementDict("driver_guest", self, parent_xpath="/",
                                     tag_name="guest")
            super(self.__class__, self).__init__(virsh_instance=virsh_instance)
            self.xml = '<driver/>'
