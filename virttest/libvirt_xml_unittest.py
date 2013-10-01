#!/usr/bin/python

import unittest
import os
import shutil
import logging
import common
from virttest import xml_utils, virsh, utils_misc, data_dir
from autotest.client import utils
from autotest.client.shared import error
from virttest.libvirt_xml import accessors, vm_xml, xcepts, network_xml, base
from virttest.libvirt_xml import nodedev_xml
from virttest.libvirt_xml.devices import librarian
from virttest.libvirt_xml.devices import base as devices_base
from virttest.libvirt_xml import capability_xml

# save a copy
ORIGINAL_DEVICE_TYPES = list(librarian.DEVICE_TYPES)
UUID = "8109c109-1551-cb11-8e2c-bc43745252ef"
_CAPABILITIES = """<capabilities><host>
<uuid>%s</uuid><cpu><arch>x86_64</arch><model>
SandyBridge</model><vendor>Intel</vendor><topology sockets='1' cores='1'
threads='1'/><feature name='vme'/></cpu><power_management><suspend_mem/>
<suspend_disk/></power_management><migration_features><live/><uri_transports>
<uri_transport>tcp</uri_transport></uri_transports></migration_features>
<topology><cells num='1'><cell id='0'><cpus num='1'><cpu id='0'/></cpus></cell>
</cells></topology><secmodel><model>selinux</model><doi>0</doi></secmodel>
</host><guest><os_type>hvm</os_type><arch name='x86_64'><wordsize>64</wordsize>
<emulator>/usr/libexec/qemu-kvm</emulator><machine>rhel6.3.0</machine><machine
canonical='rhel6.3.0'>pc</machine><domain type='qemu'></domain><domain
type='kvm'><emulator>/usr/libexec/qemu-kvm</emulator></domain></arch><features>
<cpuselection/><deviceboot/><acpi default='on' toggle='yes'/><apic default='on'
toggle='no'/></features></guest></capabilities>"""
CAPABILITIES = _CAPABILITIES % UUID


class LibvirtXMLTestBase(unittest.TestCase):

    # Override instance methods needed for testing

    # domain_xml
    # usage:
    #    xml = __domain_xml__ % (name, uuid)
    __domain_xml__ = ('<domain type="kvm">'
                      '    <name>%s</name>'
                      '    <uuid>%s</uuid>'
                      '    <devices>'  # Tests below depend on device order
                      '       <serial type="pty">'
                      '           <target port="0"/>'
                      '       </serial>'
                      '       <serial type="pty">'
                      '           <target port="1"/>'
                      '           <source path="/dev/null"/>'
                      '       </serial>'
                      '       <serial type="tcp">'
                      '         <source mode="connect" host="1.2.3.4"\
                                                        service="2445"/>'
                      '         <protocol type="raw"/>'
                      '         <target port="2"/>'
                      '       </serial>'
                      '       <serial type="udp">'
                      '         <source mode="bind" host="1.2.3.4"\
                                                        service="2445"/>'
                      '         <source mode="connect" host="4.3.2.1"\
                                                        service="5442"/>'
                      '         <target port="3"/>'
                      '       </serial>'
                      '       <channel type="foo1">'
                      '         <source mode="foo2" path="foo3" />'
                      '         <target name="foo4" type="foo5" />'
                      '       </channel>'
                      '       <channel type="bar1">'
                      '         <source mode="bar2" path="bar3" />'
                      '         <target name="bar4" type="bar5" />'
                      '       </channel>'
                      '       <graphics type="vnc" port="-1" autoport="yes"/>'
                      '    </devices>'
                      '    <seclabel type="sec_type" model="sec_model"\
                                                    relabel="sec_relabel">'
                      '       <label>sec_label</label>'
                      '       <baselabel>sec_baselabel</baselabel>'
                      '       <imagelabel>sec_imagelabel</imagelabel>'
                      '    </seclabel>'
                      '</domain>')

    __doms_dir__ = None

    @staticmethod
    def _capabilities(option='', **dargs):
        # Compacted to save space
        return CAPABILITIES

    @staticmethod
    def _domuuid(name, **dargs):
        return "ddb0cf86-5ba8-4f83-480a-d96f54339219"

    @staticmethod
    def _define(file_path, **dargs):
        vmxml = xml_utils.XMLTreeFile(file_path)
        dom_name = vmxml.find('name').text
        xml_path = os.path.join(LibvirtXMLTestBase.__doms_dir__,
                                '%s.xml' % dom_name)
        shutil.copy(file_path, xml_path)

    @staticmethod
    def _dumpxml(name, to_file="", **dargs):
        """
        Get a xml from name.
        """
        if not name:
            cmd = "virsh dumpxml %s" % name
            stdout = "error: command 'dumpxml' requires <domain> option"
            stderr = stdout
            exit_status = 1
            result = utils.CmdResult(cmd, stdout, stderr, exit_status)
            raise error.CmdError(cmd, result,
                                 "Virsh Command returned non-zero exit status")

        file_path = os.path.join(LibvirtXMLTestBase.__doms_dir__,
                                 '%s.xml' % name)
        if os.path.exists(file_path):
            xml_file = open(file_path, 'r')
            domain_xml = xml_file.read()
        else:
            xml_file = open(file_path, 'w')
            domain_xml = LibvirtXMLTestBase.__domain_xml__ % (name,
                                                              LibvirtXMLTestBase._domuuid(None))
            xml_file.write(domain_xml)
        xml_file.close()
        return domain_xml


    @staticmethod
    def _nodedev_dumpxml(name, options="", to_file=None, **dargs):
        # Must mirror virsh.nodedev_dumpxml() API but can't test this option
        if options != "":
            raise ValueError('Dummy virsh for testing does not support options'
                             ' parameter')
        if to_file is not None:
            raise ValueError('Dummy virsh for testing does not support to_file'
                             ' parameter')
        if name is not 'pci_0000_00_00_0':
            raise ValueError('Dummy virsh for testing only support '
                             ' device name pci_0000_00_00_0')
        xml =   ("<device>"
                  "<name>pci_0000_00_00_0</name>"
                  "<path>/sys/devices/pci0000:00/0000:00:00.0</path>"
                  "<parent>computer</parent>"
                  "<capability type='pci'>"
                    "<domain>0</domain>"
                    "<bus>0</bus>"
                    "<slot>0</slot>"
                    "<function>0</function>"
                    "<product id='0x25c0'>5000X Chipset Memory Controller Hub</product>"
                    "<vendor id='0x8086'>Intel Corporation</vendor>"
                  "</capability>"
                "</device>")
        return utils.CmdResult('virsh nodedev-dumpxml pci_0000_00_00_0',
                               xml, '', 0)


    def setUp(self):
        # cause any called virsh commands to fail testing unless a mock declared
        # necessary so virsh module doesn't complain about missing virsh command
        # and to catch any libvirt_xml interface which calls virsh functions
        # unexpectidly.
        self.dummy_virsh = virsh.Virsh(virsh_exec='/bin/false',
                                       uri='qemu:///system',
                                       debug=True,
                                       ignore_status=True)

        # make a tmp_dir to store informations.
        LibvirtXMLTestBase.__doms_dir__ = os.path.join(data_dir.get_tmp_dir(),
                                                       'domains')
        if not os.path.isdir(LibvirtXMLTestBase.__doms_dir__):
            os.makedirs(LibvirtXMLTestBase.__doms_dir__)
        # Normally not kosher to call __super_set__, but required here for testing
        self.dummy_virsh.__super_set__('capabilities', self._capabilities)
        self.dummy_virsh.__super_set__('dumpxml', self._dumpxml)
        self.dummy_virsh.__super_set__('domuuid', self._domuuid)
        self.dummy_virsh.__super_set__('define', self._define)
        self.dummy_virsh.__super_set__('nodedev_dumpxml', self._nodedev_dumpxml)


    def tearDown(self):
        librarian.DEVICE_TYPES = list(ORIGINAL_DEVICE_TYPES)
        if os.path.isdir(self.__doms_dir__):
            shutil.rmtree(self.__doms_dir__)


class AccessorsTest(LibvirtXMLTestBase):

    def test_type_check(self):
        class bar(object):
            pass

        class foo(bar):
            pass
        # Save some typing
        type_check = accessors.type_check
        foobar = foo()
        self.assertEqual(type_check("foobar", foobar, bar), None)
        self.assertEqual(type_check("foobar", foobar, object), None)
        self.assertRaises(ValueError, type_check, "foobar", foobar, list)
        self.assertRaises(TypeError, type_check, "foobar", foobar, None)
        self.assertRaises(TypeError, type_check, "foobar", None, foobar)
        self.assertRaises(TypeError, type_check, None, "foobar", foobar)

    def test_required_slots(self):
        class Foo(accessors.AccessorGeneratorBase):

            class Getter(accessors.AccessorBase):
                __slots__ = accessors.add_to_slots('foo', 'bar')
                pass
        lvx = base.LibvirtXMLBase(self.dummy_virsh)
        forbidden = ['set', 'del']
        self.assertRaises(ValueError, Foo, 'foobar', lvx, forbidden)
        self.assertRaises(ValueError, Foo, 'foobar', lvx, forbidden, foo='')
        self.assertRaises(ValueError, Foo, 'foobar', lvx, forbidden, bar='')

    def test_accessor_base(self):
        class ABSubclass(accessors.AccessorBase):
            pass
        lvx = base.LibvirtXMLBase(self.dummy_virsh)
        # operation attribute check should fail
        self.assertRaises(ValueError, accessors.AccessorBase,
                          'foobar', lvx, lvx)
        abinst = ABSubclass('Getter', 'foobar', lvx)
        self.assertEqual(abinst.property_name, 'foobar')
        # test call to get_libvirtxml() accessor
        self.assertEqual(abinst.libvirtxml, lvx)

    def test_XMLElementInt(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = ('auto_test',
                         'bin_test',
                         'oct_test',
                         'dec_test',
                         'hex_test')
        lvx = FooBar(self.dummy_virsh)
        lvx.xml = ('<integer>'
                   ' <auto>00</auto>'
                   ' <bin>10</bin>'
                   ' <oct>10</oct>'
                   ' <dec>10</dec>'
                   ' <hex>10</hex>'
                   '</integer>')

        name_radix = {'auto': 0, 'bin': 2, 'oct': 8, 'dec': 10, 'hex': 16}
        for name, radix in name_radix.items():
            accessors.XMLElementInt(name + '_test', lvx,
                                    parent_xpath='/',
                                    tag_name=name,
                                    radix=radix)
            self.assertEqual(lvx[name + '_test'], radix)

        self.assertRaises(ValueError,
                          lvx.__setitem__, 'bin_test', 'text')

    def test_AllForbidden(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = ('test',)
        lvx = FooBar(self.dummy_virsh)
        accessors.AllForbidden('test', lvx)
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvx.__getitem__, 'test')
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvx.__setitem__, 'test', 'foobar')
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvx.__delitem__, 'test')

    def test_not_enuf_dargs(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = ('test',)
        foobar = FooBar(self.dummy_virsh)
        self.assertRaises(ValueError,
                          accessors.XMLElementText, 'test',
                          foobar, '/')
        self.assertRaises(TypeError,
                          accessors.XMLElementText)
        self.assertRaises(TypeError,
                          accessors.XMLElementText, 'test')

    def test_too_many_dargs(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = ('test',)
        foobar = FooBar(self.dummy_virsh)
        self.assertRaises(ValueError,
                          accessors.XMLElementText, 'test',
                          foobar, '/', 'foobar')
        self.assertRaises(ValueError,
                          accessors.XMLElementText, 'test',
                          None, None, None, None)

    def test_create_by_xpath(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = ('test',)
            def __init__(self, virsh_instance):
                super(FooBar, self).__init__(virsh_instance)
                accessors.XMLElementDict('test', self, None, 'foo/bar', 'baz')
        foobar = FooBar(self.dummy_virsh)
        foobar.xml = '<test></test>'
        test_dict = {'test1': '1', 'test2': '2'}
        foobar.test = test_dict
        self.assertEqual(foobar.test, test_dict)
        element = foobar.xmltreefile.find('foo/bar/baz')
        self.assertTrue(element is not None)
        element_dict = dict(element.items())
        self.assertEqual(test_dict, element_dict)


class TestLibvirtXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        return capability_xml.CapabilityXML(self.dummy_virsh)

    def test_uuid(self):
        lvxml = self._from_scratch()
        test_uuid = lvxml.uuid
        self.assertEqual(test_uuid, UUID)
        test_uuid = lvxml['uuid']
        self.assertEqual(test_uuid, UUID)
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvxml.__setattr__,
                          'uuid', 'foobar')
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvxml.__delitem__,
                          'uuid')

    def test_os_arch_machine_map(self):
        lvxml = self._from_scratch()
        expected = {'hvm': {'x86_64': ['rhel6.3.0', 'pc']}}
        test_oamm = lvxml.os_arch_machine_map
        self.assertEqual(test_oamm, expected)
        test_oamm = lvxml['os_arch_machine_map']
        self.assertEqual(test_oamm, expected)
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvxml.__setattr__,
                          'os_arch_machine_map', 'foobar')
        self.assertRaises(xcepts.LibvirtXMLForbiddenError,
                          lvxml.__delitem__,
                          'os_arch_machine_map')


class TestVMXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        vmxml = vm_xml.VMXML('test1', self.dummy_virsh)
        vmxml.vm_name = 'test2'
        vmxml.uuid = 'test3'
        vmxml.vcpu = 4
        return vmxml

    def test_getters(self):
        vmxml = self._from_scratch()
        self.assertEqual(vmxml.hypervisor_type, 'test1')
        self.assertEqual(vmxml.vm_name, 'test2')
        self.assertEqual(vmxml.uuid, 'test3')
        self.assertEqual(vmxml.vcpu, 4)

    def test_valid_xml(self):
        vmxml = self._from_scratch()
        test_xtf = xml_utils.XMLTreeFile(vmxml.xml)  # re-parse from filename
        self.assertEqual(test_xtf.getroot().get('type'), 'test1')
        self.assertEqual(test_xtf.find('name').text, 'test2')
        self.assertEqual(test_xtf.find('uuid').text, 'test3')
        self.assertEqual(test_xtf.find('vcpu').text, '4')

    def test_new_from_dumpxml(self):
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar',
                                              virsh_instance=self.dummy_virsh)
        self.assertEqual(vmxml.vm_name, 'foobar')
        self.assertEqual(vmxml.uuid, self._domuuid(None))
        self.assertEqual(vmxml.hypervisor_type, 'kvm')

    def test_seclabel(self):
        vmxml = self._from_scratch()

        # should not raise an exception
        del vmxml.seclabel

        self.assertRaises(xcepts.LibvirtXMLError,
                          getattr, vmxml, 'seclabel')

        vmxml.set_seclabel({'type': "dynamic"})
        self.assertEqual(vmxml.seclabel['type'], 'dynamic')
        self.assertEqual(len(vmxml.seclabel), 1)

        seclabel_dict = {'type': 'test_type', 'model': 'test_model',
                         'relabel': 'test_relabel', 'label': 'test_label',
                         'baselabel': 'test_baselabel',
                         'imagelabel': 'test_imagelabel'}
        vmxml.set_seclabel(seclabel_dict)

        seclabel = vmxml.get_seclabel()

        for key, value in seclabel_dict.items():
            self.assertEqual(seclabel[key], value)

        # test attribute-like access also
        for key, value in vmxml.seclabel.items():
            self.assertEqual(seclabel_dict[key], value)


class testNetworkXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        netxml = network_xml.NetworkXML(network_name='test0',
                                        virsh_instance=self.dummy_virsh)
        self.assertEqual(netxml.name, 'test0')
        netxml.name = 'test1'
        netxml.uuid = 'test2'
        netxml.bridge = {'test3': 'test4'}

        ipxml = network_xml.IPXML()
        ipxml.address = ('address_test')
        ipxml.netmask = ('netmask_test')
        netxml.ip = ipxml
        return netxml

    def test_getters(self):
        netxml = self._from_scratch()
        self.assertEqual(netxml.name, 'test1')
        self.assertEqual(netxml.uuid, 'test2')
        self.assertEqual(netxml.bridge, {'test3': 'test4'})

    def test_valid_xml(self):
        netxml = self._from_scratch()
        test_xtf = xml_utils.XMLTreeFile(netxml.xml)  # re-parse from filename
        self.assertEqual(test_xtf.find('name').text, 'test1')
        self.assertEqual(test_xtf.find('uuid').text, 'test2')
        self.assertEqual(test_xtf.find('bridge').get('test3'), 'test4')

    def test_ip_getter(self):
        netxml = self._from_scratch()
        ipxml = netxml.ip
        self.assertEqual(ipxml.address, 'address_test')
        self.assertEqual(ipxml.netmask, 'netmask_test')


class testLibrarian(LibvirtXMLTestBase):

    def test_bad_names(self):
        for badname in ('__init__', 'librarian', '__doc__', '/dev/null', '',
                        None):
            self.assertRaises(xcepts.LibvirtXMLError, librarian.get, badname)

    def test_no_module(self):
        # Bypass type-check to induse module load failure
        original_device_types = librarian.DEVICE_TYPES
        for badname in ('DoesNotExist', '/dev/null', '', None):
            librarian.DEVICE_TYPES.append(badname)
            self.assertRaises(xcepts.LibvirtXMLError, librarian.get,
                              badname)

    def test_serial_class(self):
        Serial = librarian.get('serial')
        self.assertTrue(issubclass(Serial, devices_base.UntypedDeviceBase))
        self.assertTrue(issubclass(Serial, devices_base.TypedDeviceBase))


class testStubXML(LibvirtXMLTestBase):

    class UntypedFoobar(devices_base.UntypedDeviceBase):
        __metaclass__ = devices_base.StubDeviceMeta
        _device_tag = 'foobar'

    class TypedFoobar(devices_base.TypedDeviceBase):
        __metaclass__ = devices_base.StubDeviceMeta
        _device_tag = 'foo'
        _def_type_name = 'bar'

    def setUp(self):
        logging.disable(logging.WARNING)
        super(testStubXML, self).setUp()

    def test_untyped_device_stub(self):
        foobar = self.UntypedFoobar(virsh_instance=self.dummy_virsh)
        self.assertEqual(foobar.virsh.domuuid(None),
                         "ddb0cf86-5ba8-4f83-480a-d96f54339219")
        self.assertEqual(foobar.device_tag, 'foobar')
        self.assertEqual(unicode(foobar),
                         u"<?xml version='1.0' encoding='UTF-8'?>\n<foobar />")

    def test_typed_device_stub(self):
        foobar = self.TypedFoobar(virsh_instance=self.dummy_virsh)
        self.assertEqual(foobar.virsh.domuuid(None),
                         "ddb0cf86-5ba8-4f83-480a-d96f54339219")
        self.assertEqual(foobar.device_tag, 'foo')
        self.assertEqual(foobar.type_name, 'bar')
        self.assertEqual(unicode(foobar),
                         u'<?xml version=\'1.0\' encoding=\'UTF-8\'?>\n<foo type="bar" />')


class testCharacterXML(LibvirtXMLTestBase):

    def test_arbitrart_attributes(self):
        parallel = librarian.get('parallel')(virsh_instance=self.dummy_virsh)
        serial = librarian.get('serial')(virsh_instance=self.dummy_virsh)
        channel = librarian.get('channel')(virsh_instance=self.dummy_virsh)
        console = librarian.get('console')(virsh_instance=self.dummy_virsh)
        for chardev in (parallel, serial, channel, console):
            attribute1 = utils_misc.generate_random_string(10)
            value1 = utils_misc.generate_random_string(10)
            attribute2 = utils_misc.generate_random_string(10)
            value2 = utils_misc.generate_random_string(10)
            chardev.add_source(**{attribute1: value1, attribute2: value2})
            chardev.add_target(**{attribute1: value1, attribute2: value2})
            self.assertEqual(chardev.sources, chardev.targets)


class testSerialXML(LibvirtXMLTestBase):

    XML = u"<serial type='pty'><source path='/dev/null'/>\
                                        <target port='-1'/></serial>"

    def _from_scratch(self):
        serial = librarian.get('Serial')(virsh_instance=self.dummy_virsh)
        self.assertEqual(serial.device_tag, 'serial')
        self.assertEqual(serial.type_name, 'pty')
        self.assertEqual(serial.virsh, self.dummy_virsh)
        serial.add_source(path='/dev/null')
        serial.add_target(port="-1")
        return serial

    def test_getters(self):
        serial = self._from_scratch()
        self.assertEqual(serial.sources[0]['path'], '/dev/null')
        self.assertEqual(serial.targets[0]['port'], '-1')

    def test_from_element(self):
        element = xml_utils.ElementTree.fromstring(self.XML)
        serial1 = self._from_scratch()
        serial2 = librarian.get('Serial').new_from_element(element)
        self.assertEqual(serial1, serial2)
        # Can't in-place modify the dictionary since it's virtual
        serial2.update_target(0, port="0")
        self.assertTrue(serial1 != serial2)
        serial1.targets = [{'port': '0'}]
        self.assertEqual(serial1, serial2)

    def test_vm_get_by_class(self):
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar',
                                              virsh_instance=self.dummy_virsh)
        serial_devices = vmxml.get_devices(device_type='serial')
        self.assertEqual(len(serial_devices), 4)

    def test_vm_get_modify(self):
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar',
                                              virsh_instance=self.dummy_virsh)
        devices = vmxml['devices']
        serial1 = devices[0]
        serial2 = devices[1]
        serial3 = devices[2]
        serial4 = devices[3]
        self.assertEqual(serial1.device_tag, 'serial')
        self.assertEqual(serial2.device_tag, 'serial')
        self.assertEqual(serial1.type_name, 'pty')
        self.assertEqual(serial2.type_name, 'pty')
        self.assertFalse(serial1 == serial2)
        self.assertEqual(serial1.sources, [])
        # mix up access style
        serial1.add_source(**serial2.sources[0])
        self.assertFalse(serial1 == serial2)
        serial1.update_target(0, port="1")
        self.assertEqual(serial1, serial2)
        # Exercize bind mode
        self.assertEqual(serial3.type_name, 'tcp')
        source_connect = serial3.sources[0]
        self.assertEqual(source_connect, {'mode': "connect", 'host': '1.2.3.4',
                                          'service': '2445'})
        self.assertEqual(serial3.protocol_type, 'raw')
        self.assertEqual(serial3.targets[0]['port'], '2')
        # Exercize udp type
        self.assertEqual(serial4.type_name, 'udp')
        source_bind = serial4.sources[0]
        source_connect = serial4.sources[1]
        self.assertEqual(source_bind['host'], "1.2.3.4")
        self.assertEqual(source_connect['host'], "4.3.2.1")
        self.assertEqual(source_bind['service'], '2445')
        self.assertEqual(source_connect['service'], '5442')


class testAddressXML(LibvirtXMLTestBase):

    def test_required(self):
        address = librarian.get('address')
        self.assertRaises(xcepts.LibvirtXMLError,
                          address.new_from_dict,
                          {}, self.dummy_virsh)
        # no type_name attribute
        element = xml_utils.ElementTree.Element('address', {'foo': 'bar'})
        self.assertRaises(xcepts.LibvirtXMLError,
                          address.new_from_element,
                          element, self.dummy_virsh)
        element.set('type', 'foobar')
        new_address = address.new_from_element(element, self.dummy_virsh)
        the_dict = {'type_name': 'foobar', 'foo': 'bar'}
        another_address = address.new_from_dict(the_dict, self.dummy_virsh)
        self.assertEqual(str(new_address), str(another_address))


class testVMXMLDevices(LibvirtXMLTestBase):

    def test_channels(self):
        logging.disable(logging.WARNING)
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar',
                                              virsh_instance=self.dummy_virsh)
        channels = vmxml.devices.by_device_tag('channel')
        self.assertEqual(len(channels), 2)
        self.assertTrue(isinstance(channels, vm_xml.VMXMLDevices))
        self.assertEqual(channels[0].type_name, 'foo1')
        self.assertEqual(channels[1].type_name, 'bar1')
        one = channels.pop()
        two = channels.pop()
        self.assertEqual(len(channels), 0)
        self.assertFalse(one == two)

    def test_graphics(self):
        logging.disable(logging.WARNING)
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar',
                                              virsh_instance=self.dummy_virsh)
        devices = vmxml.devices
        # Assume only one graphics device, take first in list
        graphics_index = devices.index(devices.by_device_tag('graphics')[0])
        # Make copy of existing graphics device
        graphics = devices[graphics_index]
        # Modify copy
        graphics.passwd = 'foobar'
        # Remove existing graphics device
        del devices[graphics_index]
        # Add modified copy (another copy)
        devices.append(graphics)
        # clean up graphics temp files
        del graphics
        # Copy modified devices to vm
        vmxml.devices = devices
        # clean up devices temp files
        del devices
        # Check result
        self.assertEqual(vmxml.devices[-1].passwd, 'foobar')


class testCAPXML(LibvirtXMLTestBase):

    def test_capxmlbase(self):
        capxmlbase = nodedev_xml.CAPXML()
        self.assertRaises(NotImplementedError,
                          capxmlbase.get_sysfs_sub_path)
        self.assertRaises(NotImplementedError,
                          capxmlbase.get_key2filename_dict)
        self.assertRaises(NotImplementedError,
                          capxmlbase.get_key2value_dict)


class testNodedevXMLBase(LibvirtXMLTestBase):

    def _from_scratch(self):
        nodedevxml = nodedev_xml.NodedevXMLBase()
        nodedevxml.name = 'name_test'
        nodedevxml.parent = 'parent_test'

        return nodedevxml

    def test_getter(self):
        nodedevxml = self._from_scratch()
        self.assertEqual(nodedevxml.name, 'name_test')
        self.assertEqual(nodedevxml.parent, 'parent_test')

    def test_static(self):
        base = nodedev_xml.NodedevXMLBase
        cap_list = ['system', 'pci']
        for cap_type in cap_list:
            result = base.get_cap_by_type(cap_type)
            self.assertTrue(isinstance(result, nodedev_xml.CAPXML))


class testNodedevXML(LibvirtXMLTestBase):

    def test_new_from_dumpxml(self):
        NodedevXML = nodedev_xml.NodedevXML
        nodedevxml = NodedevXML.new_from_dumpxml('pci_0000_00_00_0')
        self.assertTrue(isinstance(nodedevxml, NodedevXML))

    def test_get_key2value_dict(self):
        NodedevXML = nodedev_xml.NodedevXML
        xml = NodedevXML.new_from_dumpxml('pci_0000_00_00_0')
        result = xml.get_key2value_dict()

        self.assertTrue(isinstance(result, dict))

    def test_get_key2syspath_dict(self):
        NodedevXML = nodedev_xml.NodedevXML
        xml = NodedevXML.new_from_dumpxml('pci_0000_00_00_0')
        result = xml.get_key2syspath_dict()
        self.assertTrue(isinstance(result, dict))


class testPCIXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        pcixml = nodedev_xml.PCIXML()
        pcixml.domain = 0x10
        pcixml.bus = 0x20
        pcixml.slot = 0x30
        pcixml.function = 0x1
        pcixml.vendor_id = '0x123'
        pcixml.product_id = '0x123'

        return pcixml

    def test_static(self):
        PCIXML = nodedev_xml.PCIXML
        result = PCIXML.make_sysfs_sub_path(0x10, 0x20, 0x30, 0x1)
        self.assertEqual(result, 'pci_bus/0010:20/device/0010:20:30.1')

    def test_get_path(self):
        pcixml = self._from_scratch()
        result = pcixml.get_sysfs_sub_path()
        self.assertEqual(result, 'pci_bus/0010:20/device/0010:20:30.1')

    def test_get_key2filename_dict(self):
        PCIXML = nodedev_xml.PCIXML
        self.assertTrue(isinstance(PCIXML.get_key2filename_dict(), dict))

    def test_get_key2value_dict(self):
        pcixml = self._from_scratch()
        result = pcixml.get_key2value_dict()
        self.assertTrue(isinstance(result, dict))


if __name__ == "__main__":
    unittest.main()
