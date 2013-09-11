"""
hub device support class(es)

http://libvirt.org/formatdomain.html#elementsHub
"""

from virttest.libvirt_xml.devices import base


class Hub(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'hub'
    _def_type_name = 'usb'
