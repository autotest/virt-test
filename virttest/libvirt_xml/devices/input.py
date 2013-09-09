"""
input device support class(es)

http://libvirt.org/formatdomain.html#elementsInput
"""

from virttest.libvirt_xml.devices import base


class Input(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'input'
    _def_type_name = 'mouse'
