"""
disk device support class(es)

http://libvirt.org/formatdomain.html#elementsDisks
"""

from virttest.libvirt_xml.devices import base


class Disk(base.TypedDeviceBase):
    # TODO: Write this class
    __metaclass__ = base.StubDeviceMeta
    _device_tag = 'disk'
    _def_type_name = 'block'
