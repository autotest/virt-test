"""
video device support class(es)

http://libvirt.org/formatdomain.html#elementsVideo
"""

from virttest.libvirt_xml.devices import base


class Video(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'video'
    _def_type_name = 'cirrus'
