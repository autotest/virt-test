#!/usr/bin/python
import os,logging
from autotest.client.shared import error
from virttest import virsh,iface
"""
Test Case:
If a network script is available then, for virsh it is defined or else 
undefined.This test case would check virsh iface-define and virsh
iface-undefine in various scenrios. 

Steps:
1. For defined inetrface, undefine followed by defined would be checked
Before testing network scripts would be backed up and restored back after
testing

2. For undefine inetrface, define followed by undefined would be checked 
To define one new xml would be created, which would be deleted at the
 end of the testing

Input:
All the interfaces available in the host other than bridged intercace
 and virsh internal network interface (virbr0,vnet0...)




""" 

def run_virsh_iface_define_undefine(test, params, env):
    
    def chk_virsh_define(opt):
        virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
        logging.debug("Running virsh iface define for undefined iface %s"%opt)
        if iface.is_scr_avail(opt) is False or iface.avail_vir_iface(opt) is False:
            raise error.TestFail("iface define failed for undefined iface %s"%opt)
        else:
            if iface.chk_mac_vir_iface(opt) is False:
                raise error.TestFail("mac address is not correct in virsh for %s"%opt)
            else:
                logging.debug("iface define is passed for undefined iface %s"%opt)

    def chk_virsh_undefine(opt):
        virsh.iface_undefine("%s" %opt, ignore_status=True)
        logging.debug("Running virsh iface undefine for defined iface %s"%opt)
        if iface.is_scr_avail(opt) or iface.avail_vir_iface(opt):
            raise error.TestFail("iface undefine failed for defined iface %s"%opt)
        else: 
            logging.debug("iface undefine passed for defined iface %s"%opt)

    def check_virsh_define_undefine(opt):
        if iface.avail_vir_iface(opt):
            iface.edit_iface_xml(opt)
            if iface.is_scr_avail(opt):
                iface.network_scripts_backup(opt) 
                if chk_virsh_define(opt) is False: 
                    error_cnt+=1
                if chk_virsh_undefine(opt) is False:
                    error_cnt+=1
                iface.network_scripts_restore(opt) 
            else:
                raise error.TestFail("list shows %s as defined though absence of script"%opt)
            iface.destroy_iface_xml(opt)
        else:
            iface.create_iface_xml(opt)
            if iface.is_scr_avail(opt) is False:
                if chk_virsh_define(opt) is False:
                    error_cnt+=1
                if chk_virsh_undefine(opt) is False:
                    error_cnt+=1
            else:
                raise error.TestFail("list did not define iface %s though presence of script "%opt)
            iface.destroy_iface_xml(opt)
    
    
    def check_virsh_define_undefine_all():
        for ind_iface in iface.input_ifaces():
            logging.debug("Define/Undefine test would be run on "
            "following interfaces "
            "%s "%iface.input_ifaces())
            if check_virsh_define_undefine(ind_iface) is False:
                raise error.TestFail("iface define undefine is unsuccessful for iface %s"%ind_iface)
            else:
                logging.debug("iface define undefine is successful for iface %s"%ind_iface)

    logging.debug("%s" %check_virsh_define_undefine_all())
