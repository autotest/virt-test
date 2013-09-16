"""
hostdev device support class(es)

http://libvirt.org/formatdomain.html#elementsHostDev
"""

from virttest.libvirt_xml.devices import base


class Hostdev(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'hostdev'
    _def_type_name = 'pci'
