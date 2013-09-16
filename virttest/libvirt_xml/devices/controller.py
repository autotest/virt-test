"""
controller device support class(es)

http://libvirt.org/formatdomain.html#elementsControllers
"""

from virttest.libvirt_xml.devices import base


class Controller(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'controller'
    _def_type_name = 'usb'
