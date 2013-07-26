#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm
from virttest.libvirt_xml import vm_xml
from virttest.iface import *
"""
Test case:
If a network bridge is available for the interface then, for virsh 
it is bridge or else ethernet. Verify iface-bridge and iface-
unbridge

Steps:
1.For bridge inetrface, unbridge followed by bridge would be checked
Before testing network scripts would be backed up and restored back after
testing

2.For ethernet inetrface, bridge followed by unbridge would be checked 
For bridge one new xml would be created, which would be deleted at the
 end of the testing

3. For undfined insterface, this test case define the interface
and try step 1 and 2.

Input:
All the interfaces available in the host other than bridged intercace
virsh internal network interface (virbr0,vnet0...) and the interfaces
where ipaddresses are configured


"""

def run_virsh_iface_bridge_unbridge(test, params, env):
    
    def avail_vir_dbl_ifaces(opt1,opt2):
        err_cnt=0
        if avail_vir_iface(opt1) == 'yes':
            if chk_mac_vir_iface(opt1) != 'FAIL' and state_vir_iface(opt1)=='active':
                logging.debug("%s is defined with proper mac and active"%opt1) 
            else: 
                logging.debug("%s is neither defined with proper mac nor active"%opt1) 
                err_cnt+=1
        else: 
            logging.debug("%s is not defined"%opt1) 
            err_cnt+=1
        if avail_vir_iface(opt2) == 'yes':
            logging.debug("%s is defined"%opt2)                   
            err_cnt+=1
        if err_cnt > 0:
            return "FAIL"
        else:
            return "PASS"
    #print avail_vir_dbl_ifaces('br0','eth0') 
    def chk_eth_bridgd(eth,br):
        error_cnt=0
        if is_bridge(br) == 'yes':
            if eth_of_brdg(br) == eth: 
                if avail_vir_dbl_ifaces(br,eth) == 'FAIL':
                    logging.debug("verification of % & %s are failed"%(br,eth))
                    error_cnt+=1
            else:
                logging.debug("%s is not the ethernet of %s"%(eth,br))
                error_cnt+=1
        else:
            logging.debug("%s is not a bridge"%br)
            error_cnt+=1
        if error_cnt > 0:
            return "FAIL"
        else:
            return "PASS"
    #print chk_eth_bridgd('lo','br0')
    def chk_br_unbridgd(br,eth):
        error_cnt=0
        if is_bridge(br) == 'no':
            if is_bridged(eth)=='no':
                if avail_vir_dbl_ifaces(eth,br) == 'FAIL':
                    logging.debug("verification of % and %s are failed"%(br,eth))
                    error_cnt+=1
            else:
                logging.debug("%s is still bridged"%(eth))
                error_cnt+=1
        else:
            logging.debug("%s is still a bridge"%br)
            error_cnt+=1
        if error_cnt > 0:
            return "FAIL"
        else:
            return "PASS"
    #print chk_br_unbridgd('br0','lo')
    def chk_virsh_bridged_unbridged(opt): 
        err_count=0
        org_state=state_vir_iface(opt)
        if is_bridge(opt) == 'yes': 
            br=opt
            eth=eth_of_brdg(opt) 
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) == 'FAIL':
                logging.debug("iface-unbridge is failed%s"%br)
                err_count+=1
            virsh.iface_bridge("%s"%eth,"%s"%br, ignore_status=True)
            if chk_eth_bridgd(eth,br) == 'FAIL':
                logging.debug("iface-bridge is failed from %s to %s"%(eth,br))
                err_count+=1
        else:
            eth=opt
            br="br-%s"%opt
            virsh.iface_bridge("%s"%eth,"%s"%br, ignore_status=True)
            if chk_eth_bridgd(eth,br) == 'FAIL':
                logging.debug("iface-bridge is failed from %s to %s"%(eth,br))
                err_count+=1
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) == 'FAIL':
                logging.debug("iface-unbridge is failed%s"%br)
                err_count+=1
        if org_state=='inactive':
            ifdown(opt) 
        if err_count > 0:
            return "FAIL"
        else:
            return "PASS"
    #print chk_virsh_bridged_unbridged('eth1')
    def chk_virsh_brd_unbrd_str_des_df_undf(opt):
        err_count_2=0
        if avail_vir_iface(opt) is 'yes':
            network_scripts_backup(opt)
            if chk_virsh_bridged_unbridged(opt)=='FAIL':
                err_count_2+=1
            network_scripts_restore(opt)
        else:
            create_iface_xml(opt)
            virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
            if chk_virsh_bridged_unbridged(opt) == 'FAIL':
                err_count_2+=1
            virsh.iface_undefine("%s" %opt, ignore_status=True)
            destroy_iface_xml(opt)
        if err_count_2 >0:
           return 'FAIL'
        else:
           return 'PASS'
    #print chk_virsh_brd_unbrd_str_des_df_undf('eth1')
    
    def chk_virsh_brd_unbrd_str_des_df_undf_all():
        error_count=0
        for ind_iface in input_ifaces():
            if is_ipaddr(ind_iface) == 'no':
                if chk_virsh_brd_unbrd_str_des_df_undf(ind_iface) == 'FAIL':
                    logging.debug("start destroy is failed for  %s"%ind_iface)
                    error += 1
                else:
                    logging.debug("start destroy is passed for %s"%ind_iface)
        if error_count >0:
           return 'FAIL'
        else:
           return 'PASS'
    print chk_virsh_brd_unbrd_str_des_df_undf_all()
    
