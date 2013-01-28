#!/usr/bin/python

import unittest
import common
import libvirt_xml, xml_utils, virsh


class LibvirtXMLTestBase(unittest.TestCase):

    # Override instance methods needed for testing

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
        self.dummy_virsh.super_set('dumpxml', self._dumpxml)
        self.dummy_virsh.super_set('domuuid', self._domuuid)


class TestVMXML(LibvirtXMLTestBase):


    def _from_scratch(self):
        vmxml = libvirt_xml.VMXML(hypervisor_type = 'test1',
                                  virsh_instance = self.dummy_virsh)
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


    def test_del_proof(self):
        vmxml = self._from_scratch()
        # del is not a function
        self.assertRaises(libvirt_xml.LibvirtXMLError,
                          vmxml.del_hypervisor_type)
        self.assertRaises(libvirt_xml.LibvirtXMLError,
                          vmxml.del_vm_name)


    def test_valid_xml(self):
        vmxml = self._from_scratch()
        test_xtf = xml_utils.XMLTreeFile(vmxml.xml) # re-parse from filename
        self.assertEqual(test_xtf.getroot().get('type'), 'test1')
        self.assertEqual(test_xtf.find('name').text, 'test2')
        self.assertEqual(test_xtf.find('uuid').text, 'test3')
        self.assertEqual(test_xtf.find('vcpu').text, '4')


    def test_new_from_dumpxml(self):
        vmxml = libvirt_xml.VMXML.new_from_dumpxml('foobar', self.dummy_virsh)
        self.assertEqual(vmxml.vm_name, 'foobar')
        self.assertEqual(vmxml.uuid, self._domuuid(None))
        self.assertEqual(vmxml.hypervisor_type, 'kvm')


class testNetworkXML(LibvirtXMLTestBase):

    def _from_scratch(self):
        netxml = libvirt_xml.NetworkXML(network_name = 'test0',
                                        virsh_instance = self.dummy_virsh)
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


if __name__ == "__main__":
    unittest.main()
