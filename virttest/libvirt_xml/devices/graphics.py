"""
graphics framebuffer device support class(es)

http://libvirt.org/formatdomain.html#elementsGraphics
"""

from virttest.libvirt_xml import accessors
from virttest.libvirt_xml.devices import base


class Graphics(base.TypedDeviceBase):

    __slots__ = ('passwd',)

    def __init__(self, type_name='vnc', virsh_instance=base.base.virsh):
        # Add additional attribute 'passwd' for security
        accessors.XMLAttribute('passwd', self, parent_xpath='/',
                               tag_name='graphics', attribute='passwd')
        super(Graphics, self).__init__(device_tag='graphics',
                                       type_name=type_name,
                                       virsh_instance=virsh_instance)
