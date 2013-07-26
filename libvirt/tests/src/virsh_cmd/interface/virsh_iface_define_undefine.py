#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm,iface
from virttest.libvirt_xml import vm_xml
from virttest.iface import *
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
virsh internal network interface (virbr0,vnet0...)




""" 

def run_virsh_iface_define_undefine(test, params, env):
    
    def chk_virsh_define(opt):
        err_cnt=0
        virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
        if is_scr_avail(opt) is 'no' or avail_vir_iface(opt) is 'no':
            logging.debug("iface define failed for defined iface %s after undefine"%opt)
            err_cnt += 1
        else:
            if chk_mac_vir_iface(opt) is 'FAIL':
                logging.debug("mac address is not correct in virsh")
                err_cnt +=1
        if err_cnt > 0:
            return 'FAIL'
    def chk_virsh_undefine(opt):
        err_cnt=0
        virsh.iface_undefine("%s" %opt, ignore_status=True)
        if is_scr_avail(opt) is 'yes' or avail_vir_iface(opt) is 'yes':
            logging.debug("iface undefine failed for defined iface %s"%opt)
            err_cnt += 1
        if err_cnt > 0:
            return 'FAIL'
    def check_virsh_define_undefine(opt):
        error_cnt=0
        if avail_vir_iface(opt) is 'yes':
            edit_iface_xml(opt)
            if is_scr_avail(opt) is 'yes':
                network_scripts_backup(opt) 
                if chk_virsh_define(opt) is 'FAIL': 
                    error_cnt+=1
                if chk_virsh_undefine(opt) is 'FAIL':
                    error_cnt+=1
                network_scripts_restore(opt) 
            else:
                logging.debug("list shows %s as defined though absence of script"%opt)
                error_cnt += 1
            destroy_iface_xml(opt)
        else:
            create_iface_xml(opt)
            if is_scr_avail(opt) is 'no':
                if chk_virsh_define(opt) is 'FAIL':
                    error_cnt+=1
                if chk_virsh_undefine(opt) is 'FAIL':
                    error_cnt+=1
            else:
                logging.debug("list did not define iface %s though presnece of script "%opt)
                error_cnt += 1
            destroy_iface_xml(opt)
        if error_cnt > 0:
            return 'FAIL'
        else:
            return 'PASS'
    
    
    def check_virsh_define_undefine_all():
        error=0
        for ind_iface in input_ifaces():
            if check_virsh_define_undefine(ind_iface) is 'FAIL':
                logging.debug("iface define undefine is unsuccessful for iface %s"%ind_iface)
                error += 1
            else:
                logging.debug("iface define undefine is successful for iface %s"%ind_iface)
        if error > 0:
            return 'FAIL'
        else:
            return 'PASS'
    
    logging.debug("%s" %check_virsh_define_undefine_all())
    #print input_ifaces()
