"""
graphics framebuffer device support class(es)

http://libvirt.org/formatdomain.html#elementsGraphics
"""

from virttest.libvirt_xml.devices import base


class Graphics(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'graphics'
    _def_type_name = 'vnc'
