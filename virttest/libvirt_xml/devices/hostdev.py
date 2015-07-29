"""
hostdev device support class(es)

http://libvirt.org/formatdomain.html#elementsHostDev
"""
import logging
from virttest.libvirt_xml.devices import base
from virttest.libvirt_xml import accessors


class Hostdev(base.TypedDeviceBase):

    __slots__ = ('mode', 'hostdev_type', 'source_address',
                 'managed', 'boot_order')

    def __init__(self, type_name="hostdev", virsh_instance=base.base.virsh):
        accessors.XMLAttribute('hostdev_type', self, parent_xpath='/',
                               tag_name='hostdev', attribute='type')
        accessors.XMLAttribute('mode', self, parent_xpath='/',
                               tag_name='hostdev', attribute='mode')
        accessors.XMLAttribute('managed', self, parent_xpath='/',
                               tag_name='hostdev', attribute='managed')
        accessors.XMLElementNest('source_address', self, parent_xpath='/',
                                 tag_name='source', subclass=self.SourceAddress,
                                 subclass_dargs={
                                     'virsh_instance': virsh_instance})
        accessors.XMLAttribute('boot_order', self, parent_xpath='/',
                               tag_name='boot', attribute='order')
        super(self.__class__, self).__init__(device_tag='hostdev',
                                             type_name=type_name,
                                             virsh_instance=virsh_instance)

    def new_source_address(self, **dargs):
        new_one = self.SourceAddress(virsh_instance=self.virsh)
        new_address = new_one.new_untyped_address(**dargs)
        new_one.untyped_address = new_address
        return new_one

    def new_sourceusb_address(self, **dargs):
        new_one = self.SourceAddress(virsh_instance=self.virsh)
        new_vendoraddress = new_one.new_untyped_vendor(**dargs)
        new_productaddress = new_one.new_untyped_product(**dargs)
	new_usbaddress = new_one.new_untyped_usbaddress(**dargs)
        new_one.untyped_vendor = new_vendoraddress
	new_one.untyped_product = new_productaddress
	new_one.untyped_usbaddress = new_usbaddress
        return new_one 

    class SourceAddress(base.base.LibvirtXMLBase):

        __slots__ = ('untyped_address','untyped_vendor','untyped_product','untyped_usbaddress',)

        def __init__(self, virsh_instance=base.base.virsh):
            accessors.XMLElementNest('untyped_address', self, parent_xpath='/',
                                     tag_name='address', subclass=self.UntypedAddress,
                                     subclass_dargs={
                                         'virsh_instance': virsh_instance})
            accessors.XMLElementNest('untyped_vendor', self, parent_xpath='/',
                                     tag_name='vendor', subclass=self.UntypedVendor,
                                     subclass_dargs={
                                         'virsh_instance': virsh_instance})
            accessors.XMLElementNest('untyped_product', self, parent_xpath='/',
                                     tag_name='product', subclass=self.UntypedProduct,
                                     subclass_dargs={
                                         'virsh_instance': virsh_instance})
            accessors.XMLElementNest('untyped_usbaddress', self, parent_xpath='/',
                                     tag_name='address', subclass=self.UntypedusbAddress,
                                     subclass_dargs={
                                         'virsh_instance': virsh_instance})
            super(self.__class__, self).__init__(virsh_instance=virsh_instance)
            self.xml = '<source/>'

        def new_untyped_address(self, **dargs):
            new_one = self.UntypedAddress(virsh_instance=self.virsh)
            for key, value in dargs.items():
                setattr(new_one, key, value)
            return new_one

        class UntypedAddress(base.UntypedDeviceBase):

            __slots__ = ('domain', 'bus', 'slot', 'function',)

            def __init__(self, virsh_instance=base.base.virsh):
                accessors.XMLAttribute('domain', self, parent_xpath='/',
                                       tag_name='address', attribute='domain')
                accessors.XMLAttribute('slot', self, parent_xpath='/',
                                       tag_name='address', attribute='slot')
                accessors.XMLAttribute('bus', self, parent_xpath='/',
                                       tag_name='address', attribute='bus')
                accessors.XMLAttribute('function', self, parent_xpath='/',
                                       tag_name='address', attribute='function')
                super(self.__class__, self).__init__("address", virsh_instance=virsh_instance)
                self.xml = "<address/>"

        def new_untyped_usbaddress(self, **dargs):
            new_one = self.UntypedusbAddress(virsh_instance=self.virsh)
	    keys = dargs.keys()
            setattr(new_one, keys[1], dargs.get('bus'))
	    setattr(new_one, keys[0],dargs.get('device'))
            return new_one

        class UntypedusbAddress(base.UntypedDeviceBase):

            __slots__ = ('bus', 'device')

            def __init__(self, virsh_instance=base.base.virsh):
                accessors.XMLAttribute('bus', self, parent_xpath='/',
                                       tag_name='address', attribute='bus')
                accessors.XMLAttribute('device', self, parent_xpath='/',
                                       tag_name='address', attribute='device')

                super(self.__class__, self).__init__("address", virsh_instance=virsh_instance)
                self.xml = "<address/>"

        def new_untyped_vendor(self, **dargs):
            new_one = self.UntypedVendor(virsh_instance=self.virsh)
	    keys = dargs.keys()
            setattr(new_one,keys[2], dargs.get('vendor_id'))
            return new_one

        class UntypedVendor(base.UntypedDeviceBase):

            __slots__ = ('id','vendor_id')

            def __init__(self, virsh_instance=base.base.virsh):
                accessors.XMLAttribute('vendor_id', self, parent_xpath='/',
                                       tag_name='vendor', attribute='id')

                super(self.__class__, self).__init__("vendor", virsh_instance=virsh_instance)
                self.xml = "<vendor/>"


        def new_untyped_product(self, **dargs):
            new_one = self.UntypedProduct(virsh_instance=self.virsh)
	    keys = dargs.keys()
            setattr(new_one, keys[3], dargs.get('product_id'))
            return new_one

        class UntypedProduct(base.UntypedDeviceBase):

            __slots__ = ('id','product_id')

            def __init__(self, virsh_instance=base.base.virsh):
                accessors.XMLAttribute('product_id', self, parent_xpath='/',
                                       tag_name='product', attribute='id')

                super(self.__class__, self).__init__("product", virsh_instance=virsh_instance)
                self.xml = "<product/>"

