#!/usr/bin/python

import unittest
import common
from virttest import xml_utils, virsh
from virttest.libvirt_xml import accessors, vm_xml, xcepts, network_xml, base
from virttest.libvirt_xml import libvirt_xml
from virttest.libvirt_xml.devices import librarian


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


    @staticmethod
    def _capabilities(option='', **dargs):
        # Compacted to save space
        return CAPABILITIES

    @staticmethod
    def _domuuid(name, **dargs):
        return "ddb0cf86-5ba8-4f83-480a-d96f54339219"


    @staticmethod
    def _dumpxml(name, to_file="", **dargs):
        return ("<domain type='kvm'>"
                "    <name>%s</name>"
                "    <uuid>%s</uuid>"
                "</domain>" % (name, LibvirtXMLTestBase._domuuid(None)))


    def setUp(self):
        # cause all virsh commands to do nothing and return nothing
        # necessary so virsh module doesn't complain about missing virsh command
        self.dummy_virsh = virsh.Virsh(virsh_exec='/bin/true',
                                       uri='qemu:///system',
                                       debug=True,
                                       ignore_status=True)
        # Normally not kosher to call super_set, but required here for testing
        self.dummy_virsh.super_set('capabilities', self._capabilities)
        self.dummy_virsh.super_set('dumpxml', self._dumpxml)
        self.dummy_virsh.super_set('domuuid', self._domuuid)


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


    def test_AllForbidden(self):
        class FooBar(base.LibvirtXMLBase):
            __slots__ = base.LibvirtXMLBase.__slots__ + ('test',)
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
            __slots__ = base.LibvirtXMLBase.__slots__ + ('test',)
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
            __slots__ = base.LibvirtXMLBase.__slots__ + ('test',)
        foobar = FooBar(self.dummy_virsh)
        self.assertRaises(ValueError,
                          accessors.XMLElementText, 'test',
                          foobar, '/', 'foobar')
        self.assertRaises(ValueError,
                          accessors.XMLElementText, 'test',
                          None, None, None, None)


class TestLibvirtXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        return libvirt_xml.LibvirtXML(self.dummy_virsh)


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
        vmxml = vm_xml.VMXML(self.dummy_virsh, 'test1')
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
        test_xtf = xml_utils.XMLTreeFile(vmxml.xml) # re-parse from filename
        self.assertEqual(test_xtf.getroot().get('type'), 'test1')
        self.assertEqual(test_xtf.find('name').text, 'test2')
        self.assertEqual(test_xtf.find('uuid').text, 'test3')
        self.assertEqual(test_xtf.find('vcpu').text, '4')


    def test_new_from_dumpxml(self):
        vmxml = vm_xml.VMXML.new_from_dumpxml('foobar', self.dummy_virsh)
        self.assertEqual(vmxml.vm_name, 'foobar')
        self.assertEqual(vmxml.uuid, self._domuuid(None))
        self.assertEqual(vmxml.hypervisor_type, 'kvm')


class testNetworkXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        netxml = network_xml.NetworkXML(virsh_instance = self.dummy_virsh,
                                        network_name = 'test0')
        self.assertEqual(netxml.name, 'test0')
        netxml.name = 'test1'
        netxml.uuid = 'test2'
        netxml.bridge = {'test3':'test4'}
        return netxml

    def test_getters(self):
        netxml = self._from_scratch()
        self.assertEqual(netxml.name, 'test1')
        self.assertEqual(netxml.uuid, 'test2')
        self.assertEqual(netxml.bridge, {'test3':'test4'})


    def test_valid_xml(self):
        netxml = self._from_scratch()
        test_xtf = xml_utils.XMLTreeFile(netxml.xml) # re-parse from filename
        self.assertEqual(test_xtf.find('name').text, 'test1')
        self.assertEqual(test_xtf.find('uuid').text, 'test2')
        self.assertEqual(test_xtf.find('bridge').get('test3'), 'test4')


class testLibrarian(LibvirtXMLTestBase):

    def testBadNames(self):
        for badname in ('__init__', 'librarian', '__doc__', '/dev/null', '', None):
            self.assertRaises(ValueError, librarian.get, badname)


    def testNoModule(self):
        original_known_types = librarian.known_types
        for badname in ('DoesNotExist', '/dev/null', '', None):
            librarian.known_types.add(badname)
            self.assertRaises(ValueError, librarian.get, badname)


if __name__ == "__main__":
    unittest.main()
