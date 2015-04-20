"""
interface device support class(es)

http://libvirt.org/formatdomain.html#elementsNICS
http://libvirt.org/formatnwfilter.html#nwfconceptsvars
"""

from virttest.libvirt_xml import accessors, xcepts
from virttest.libvirt_xml.devices import base, librarian


class Interface(base.TypedDeviceBase):

    __slots__ = ('source', 'mac_address', 'bandwidth',
                 'model', 'link_state', 'target',
                 'driver', 'address', 'boot_order',
                 'filterref', 'backend')

    def __init__(self, type_name, virsh_instance=base.base.virsh):
        super(Interface, self).__init__(device_tag='interface',
                                        type_name=type_name,
                                        virsh_instance=virsh_instance)
        accessors.XMLElementDict(property_name="source",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='source')
        accessors.XMLElementDict(property_name="target",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='target')
        accessors.XMLElementDict(property_name="backend",
                                 libvirtxml=self,
                                 forbidden=None,
                                 parent_xpath='/',
                                 tag_name='backend')
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
        accessors.XMLAttribute(property_name="boot_order",
                               libvirtxml=self,
                               forbidden=None,
                               parent_xpath='/',
                               tag_name='boot',
                               attribute='order')
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
        accessors.XMLElementNest("filterref", self,
                                 parent_xpath='/',
                                 tag_name='filterref',
                                 subclass=self.Filterref,
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

    def new_filterref(self, **dargs):
        """
        Return a new interafce filterref instance from dargs
        """
        new_one = self.Filterref(virsh_instance=self.virsh)
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

    class Filterref(base.base.LibvirtXMLBase):

        """
        Interface filterref xml class.

        Properties:

        name:
            string. filter name
        parameters:
            list. parameters element dict list
        """
        __slots__ = ("name", "parameters")

        def __init__(self, virsh_instance=base.base.virsh):
            accessors.XMLAttribute(property_name="name",
                                   libvirtxml=self,
                                   forbidden=None,
                                   parent_xpath='/',
                                   tag_name='filterref',
                                   attribute='filter')
            accessors.XMLElementList(property_name='parameters',
                                     libvirtxml=self,
                                     parent_xpath='/',
                                     marshal_from=self.marshal_from_parameter,
                                     marshal_to=self.marshal_to_parameter)
            super(self.__class__, self).__init__(virsh_instance=virsh_instance)
            self.xml = '<filterref/>'

        @staticmethod
        def marshal_from_parameter(item, index, libvirtxml):
            """Convert a dictionary into a tag + attributes"""
            del index           # not used
            del libvirtxml      # not used
            if not isinstance(item, dict):
                raise xcepts.LibvirtXMLError("Expected a dictionary of parameter "
                                             "attributes, not a %s"
                                             % str(item))
            return ('parameter', dict(item))  # return copy of dict, not reference

        @staticmethod
        def marshal_to_parameter(tag, attr_dict, index, libvirtxml):
            """Convert a tag + attributes into a dictionary"""
            del index                    # not used
            del libvirtxml               # not used
            if tag != 'parameter':
                return None              # skip this one
            return dict(attr_dict)       # return copy of dict, not reference
