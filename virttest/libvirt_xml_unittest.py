#!/usr/bin/python

import unittest
import common
import libvirt_xml, xml_utils, virsh

class LibvirtXMLTestBase(unittest.TestCase):

    def setUp(self):
        # cause all virsh commands to do nothing and return nothing
        # necessary so virsh module doesn't complain about missing virsh command
        self.dummy_virsh = virsh.Virsh(virsh_exec='/bin/true')


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


if __name__ == "__main__":
    unittest.main()
