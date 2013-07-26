#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm,iface
from virttest.libvirt_xml import vm_xml
from virttest.iface import *
"""
Test Case:
If a network of the ethernet is up and network scripts are available then, 
for virsh it is active or else inactive. This tests virsh iface-start and
iface in various scenarios 


Steps:
1. For defined active inetrface, destroy followed by start would be checked
At the end it would make the interface up
2. For defined inactive inetrface, start followed by destroy would be checked
At the end it would make the interface down 
3. For undefined active inetrface, define, then destroy,then  start later
undefine would be checked
4. For undefined inactive inetrface, define, then start,then  destroy
later undefine would be checked

Input:
All the interfaces available in the host other than bridged intercace
virsh internal network interface (virbr0,vnet0...) and the interfaces
where ipaddresses are configured

"""

    
def run_virsh_iface_start_destroy(test, params, env):
    def chk_vrs_ifc_str_dst(opt):
        err_cnt=0
        if state_vir_iface(opt) == 'active':
            if is_up(opt) == 'yes':
                logging.debug("iface is up for active %s"%opt)
                virsh.iface_destroy("%s" %opt, ignore_status=True)
                if chk_state_vir_iface(opt) is not 'inactive':
                    logging.debug("iface-destroy is unsuccessful in virsh  for active %s"%opt)
                    err_cnt+=1
                virsh.iface_start("%s" %opt, ignore_status=True)
                if chk_state_vir_iface(opt) is not 'active':
                    logging.debug("iface-start is unsuccessful in virsh  for destroyed active %s"%opt)
                    err_cnt+=1
                ifup(opt)
            else:
                logging.debug("iface is down for active %s"%opt)
                err_cnt+=1
        else:
            if is_up(opt) == 'no':
                logging.debug("iface is down for inactive %s"%opt)
                virsh.iface_start("%s" %opt, ignore_status=True)
                if chk_state_vir_iface(opt) is not 'active':
                    logging.debug("iface-start is unsuccessful in virsh  for inactive %s"%opt)
                    err_cnt+=1
                virsh.iface_destroy("%s" %opt, ignore_status=True)
                if chk_state_vir_iface(opt) is not 'inactive':
                    logging.debug("iface-destroy is unsuccessful in virsh  for started inactive %s"%opt)
                    err_cnt+=1
            else:
                logging.debug("iface is down for active %s"%opt)
                err_cnt+=1
        if err_cnt > 0:
           return 'FAIL'
        else:
           return 'PASS'
      
    
    def chk_vrs_ifc_str_dst_df_undf(opt):
        error=0
        if avail_vir_iface(opt) == 'yes':
             if chk_vrs_ifc_str_dst(opt) is 'FAIL':
                 error += 1
        else:
            create_iface_xml(opt)
            virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
            if chk_vrs_ifc_str_dst(opt) is 'FAIL':
                 error += 1
            virsh.iface_undefine("%s" %opt, ignore_status=True)
            destroy_iface_xml(opt)
        if error >0:
           return 'FAIL'
        else:
           return 'PASS'
    
    
    
    
    def check_virsh_iface_start_destroy_all():
        error_count=0
        for ind_iface in input_ifaces():
            if is_ipaddr(ind_iface) == 'no':
                if chk_vrs_ifc_str_dst_df_undf(ind_iface) is 'FAIL':
                    logging.debug("iface start destroy is unsuccessful for iface %s"%ind_iface)
                    error += 1
                else:
                    logging.debug("iface start destroy is successful for iface %s"%ind_iface)
        if error_count >0:
           return 'FAIL'
        else:
           return 'PASS'
    print check_virsh_iface_start_destroy_all()
    
    
            
    
    
    
    #print input_ifaces()
