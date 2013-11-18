"""
Module simplifying manipulation of XML described at
http://libvirt.org/
"""

from virttest.libvirt_xml import base, accessors


class VolXMLBase(base.LibvirtXMLBase):

    """
    Accessor methods for VolXML class.

    Properties:
        name: string, operates on XML name tag
        uuid: string, operates on uuid tag
        type: string, operates on type tag
        capacity: integer, operates on capacity attribute of capacity tag
        allocation: integer, operates on allocation attribute of allocation
        available: integer, operates on available attribute of available
        source: nothing
    """

    __slots__ = ('name', 'key', 'capacity', 'allocation', 'format', 'path')

    __uncompareable__ = base.LibvirtXMLBase.__uncompareable__

    __schema_name__ = "storagevol"

    def __init__(self, virsh_instance=base.virsh):
        accessors.XMLElementText('name', self, parent_xpath='/',
                                 tag_name='name')
        accessors.XMLElementText('key', self, parent_xpath='/',
                                 tag_name='key')
        accessors.XMLElementInt('capacity', self, parent_xpath='/',
                                tag_name='capacity')
        accessors.XMLElementInt('allocation', self, parent_xpath='/',
                                tag_name='allocation')
        accessors.XMLAttribute('format', self, parent_xpath='/target',
                               tag_name='format', attribute='type')
        accessors.XMLElementText('path', self, parent_xpath='/target',
                                 tag_name='path')
        super(VolXMLBase, self).__init__(virsh_instance=virsh_instance)


class VolXML(VolXMLBase):

    """
    Manipulators of a Virtual Vol through it's XML definition.
    """

    __slots__ = []

    def __init__(self, vol_name='default', virsh_instance=base.virsh):
        """
        Initialize new instance with empty XML
        """
        super(VolXML, self).__init__(virsh_instance=virsh_instance)
        self.xml = u"<volume><name>%s</name></volume>" % vol_name

    @staticmethod
    def new_from_vol_dumpxml(vol_name, pool_name, virsh_instance=base.virsh):
        """
        Return new VolXML instance from virsh vol-dumpxml command

        :param vol_name: Name of vol to vol-dumpxml
        :param virsh_instance: virsh module or instance to use
        :return: New initialized VolXML instance
        """
        volxml = VolXML(virsh_instance=virsh_instance)
        volxml['xml'] = virsh_instance.vol_dumpxml(vol_name, pool_name)\
                                      .stdout.strip()
        return volxml

    @staticmethod
    def get_vol_details_by_name(vol_name, pool_name, virsh_instance=base.virsh):
        """
        Return Vol's uuid by Vol's name.

        :param vol_name: Vol's name
        :return: Vol's uuid
        """
        volume_xml = {}
        vol_xml = VolXML.new_from_vol_dumpxml(vol_name, pool_name,
                                              virsh_instance)
        volume_xml['key'] = vol_xml.key
        volume_xml['path'] = vol_xml.path
        volume_xml['format'] = vol_xml.format
        volume_xml['capacity'] = vol_xml.capacity
        volume_xml['allocation'] = vol_xml.allocation
        return volume_xml
