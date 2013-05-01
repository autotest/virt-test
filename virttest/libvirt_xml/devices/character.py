"""
Generic character device support for serial, parallel, channel, and console

http://libvirt.org/formatdomain.html#elementCharSerial
"""

from virttest.xml_utils import ElementTree
from virttest.libvirt_xml import accessors, xcepts
from virttest.libvirt_xml.devices import base

class CharacterBase(base.TypedDeviceBase):

    __slots__ = base.TypedDeviceBase.__slots__ + ('sources', 'targets')

    # Not overriding __init__ because ABC cannot hide device_tag as expected

    # All accessors here will vary only by sources or targets tag
    def _get_list(self, tag_filter):
        dict_list = []
        elements = self.xmltreefile.findall(tag_filter)
        for element in elements:
            dict_list.append(dict(element.items()))
        return dict_list


    def _set_list(self, tag_name, value):
        xcept = xcepts.LibvirtXMLError("Must set %s child %s elements from"
                                       " a list-like of dict-likes"
                                       % (self.device_tag, tag_name))
        if not isinstance(value, list):
            raise xcept
        # Start with clean slate
        self._del_list(tag_name)
        for dict_item in value:
            if not isinstance(dict_item, dict):
                raise xcept
            ElementTree.SubElement(self.xmltreefile.getroot(),
                                   tag_name, dict_item)
        self.xmltreefile.write()


    def _del_list(self, tag_filter):
        element = self.xmltreefile.find(tag_filter)
        while element is not None:
            self.xmltreefile.getroot().remove(element)
            element = self.xmltreefile.find(tag_filter)
        self.xmltreefile.write()


    def _add_item(self, prop_name, **attributes):
        items = self[prop_name] # sources or targets
        items.append(attributes)
        self[prop_name] = items


    def _update_item(self, prop_name, index, **attributes):
        items = self[prop_name] # sources or targets
        item = items[index]
        item.update(attributes)
        self[prop_name] = items


    # Accessors just wrap private helpers above
    def get_sources(self):
        return self._get_list('source')


    def set_sources(self, value):
        self._set_list('source', value)


    def del_sources(self):
        self._del_list('source')


    def get_targets(self):
        return self._get_list('target')


    def set_targets(self, value):
        self._set_list('target', value)


    def del_targets(self):
        self._del_list('target')


    # Some convenience methods so appending to sources/targets is easier

    def add_source(self, **attributes):
        self._add_item('sources', **attributes)


    def add_target(self, **attributes):
        self._add_item('targets', **attributes)


    def update_source(self, index, **attributes):
        self._update_item('sources', index, **attributes)


    def update_target(self, index, **attributes):
        self._update_item('targets', index, **attributes)
