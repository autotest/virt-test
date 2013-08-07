#!/usr/bin/python
import os,logging 
from autotest.client.shared import error
from virttest import virsh,iface
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
        if iface.state_vir_iface(opt) == 'active':
            if iface.is_up(opt):
                logging.debug("iface is up for active %s"%opt)
                virsh.iface_destroy("%s" %opt, ignore_status=True)
                if iface.chk_state_vir_iface(opt) is False:
                    raise error.TestFail("iface-destroy is unsuccessful in virsh  for active %s"%opt)
                else:
                    logging.debug("iface-destroy is successful in virsh  for active %s"%opt)
                if iface.is_up(opt):
                    raise error.TestFail("iface-destroy did not stop active %s"%opt)
                else:
                    logging.debug("iface-destroy did stop active %s"%opt)
                virsh.iface_start("%s" %opt, ignore_status=True)
                if iface.chk_state_vir_iface(opt) is False:
                    raise error.TestFail("iface-start is unsuccessful in virsh  for destroyed active %s"%opt)
                else:
                    logging.debug("iface-start is successful in virsh  for destroyed active %s"%opt)
                if iface.is_up(opt) is False:
                    raise error.TestFail("iface-start did not start destroyed active %s"%opt)
                else:
                    logging.debug("iface-start did start destroyed active %s"%opt)
                iface.ifup(opt)
            else:
                raise error.TestFail("iface is down for active %s"%opt)
        else:
            if iface.is_up(opt) is False:
                logging.debug("iface is down for inactive %s"%opt)
                virsh.iface_start("%s" %opt, ignore_status=True)
                if iface.chk_state_vir_iface(opt) is False:
                    raise error.TestFail("iface-start is unsuccessful in virsh  for inactive %s"%opt)
                else:
                    logging.debug("iface-start is successful in virsh  for inactive %s"%opt)
                if iface.is_up(opt) is False:
                    raise error.TestFail("iface-start did not start inactive %s"%opt)
                else: 
                    logging.debug("iface-start did start inactive %s"%opt)
                virsh.iface_destroy("%s" %opt, ignore_status=True)
                if iface.chk_state_vir_iface(opt) is False:
                    raise error.TestFail("iface-destroy is unsuccessful in virsh  for started inactive %s"%opt)
                else:
                    logging.debug("iface-destroy is successful in virsh  for started inactive %s"%opt)
                if iface.is_up(opt):
                    raise error.TestFail("iface-destroy did not stop started inactive %s"%opt)
                else:
                    logging.debug("iface-destroy did  stop started inactive %s"%opt)
                iface.ifdown(opt)
            else:
                raise error.TestFail("iface is down for active %s"%opt)
      
    
    def chk_vrs_ifc_str_dst_df_undf(opt):
        if iface.avail_vir_iface(opt):
            chk_vrs_ifc_str_dst(opt) 
        else:
            iface.create_iface_xml(opt)
            virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
            chk_vrs_ifc_str_dst(opt)
            virsh.iface_undefine("%s" %opt, ignore_status=True)
            iface.destroy_iface_xml(opt)
    
    
    
    
    def check_virsh_iface_start_destroy_all():
        for ind_iface in iface.input_ifaces():
            logging.debug("Start/Destroy test would be run on"
            "following interfaces"
            "%s"%iface.input_ifaces())
            if iface.is_ipaddr(ind_iface) is False:
                chk_vrs_ifc_str_dst_df_undf(ind_iface)
            else:
                logging.debug("Start/destroy testing is ruled out"
                "as %s is hosting an ipaddress"%ind_iface)


    check_virsh_iface_start_destroy_all()
    
    
            
    
    
    
