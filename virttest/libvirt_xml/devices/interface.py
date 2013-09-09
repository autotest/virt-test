"""
interface device support class(es)

http://libvirt.org/formatdomain.html#elementsNICS
"""

from virttest.libvirt_xml.devices import base


class Interface(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'interface'
    _def_type_name = 'bridge'
