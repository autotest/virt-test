#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm, iface
from virttest.libvirt_xml import vm_xml
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
        if iface.avail_vir_iface(opt1):
            if iface.chk_mac_vir_iface(opt1) != False and iface.state_vir_iface(opt1)=='active':
                logging.debug("%s is defined with proper mac and active"%opt1) 
            else: 
                logging.debug("%s is neither defined with proper mac nor active"%opt1) 
                err_cnt+=1
        else: 
            logging.debug("%s is not defined"%opt1) 
            err_cnt+=1
        if iface.avail_vir_iface(opt2):
            logging.debug("%s is defined"%opt2)                   
            err_cnt+=1
        if err_cnt > 0:
            return False
        else:
            return True
    #print avail_vir_dbl_ifaces('br0','eth0') 
    def chk_eth_bridgd(eth,br):
        error_cnt=0
        if iface.is_bridge(br):
            if iface.eth_of_brdg(br) == eth: 
                if avail_vir_dbl_ifaces(br,eth) == False:
                    logging.debug("verification of % & %s are failed"%(br,eth))
                    error_cnt+=1
            else:
                logging.debug("%s is not the ethernet of %s"%(eth,br))
                error_cnt+=1
        else:
            logging.debug("%s is not a bridge"%br)
            error_cnt+=1
        if error_cnt > 0:
            return False
        else:
            return True
    #print chk_eth_bridgd('lo','br0')
    def chk_br_unbridgd(br,eth):
        error_cnt=0
        if iface.is_bridge(br) == False:
            if iface.is_bridged(eth)==False:
                if avail_vir_dbl_ifaces(eth,br) == False:
                    logging.debug("verification of % and %s are failed"%(br,eth))
                    error_cnt+=1
            else:
                logging.debug("%s is still bridged"%(eth))
                error_cnt+=1
        else:
            logging.debug("%s is still a bridge"%br)
            error_cnt+=1
        if error_cnt > 0:
            return False
        else:
            return True
    #print chk_br_unbridgd('br0','lo')
    def chk_virsh_bridged_unbridged(opt): 
        err_count=0
        org_state=iface.state_vir_iface(opt)
        if iface.is_bridge(opt): 
            logging.debug("%s is a bridge"%opt)
            br=opt
            eth=iface.eth_of_brdg(opt) 
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) == False:
                logging.debug("iface-unbridge is failed for %s"%br)
                err_count+=1
            else:
                logging.debug("iface-unbridge is passed for %s"%br)
            virsh.iface_bridge("%s"%eth,"%s"%br, ignore_status=True)
            if chk_eth_bridgd(eth,br) == False:
                logging.debug("iface-bridge is failed from %s to %s"%(eth,br))
                err_count+=1
            else:
                logging.debug("iface-bridge is passed from %s to %s"%(eth,br))
        else:
            logging.debug("%s is not a bridge"%opt)
            eth=opt
            br="br-%s"%opt
            virsh.iface_bridge("%s"%eth,"%s"%br, ignore_status=True)
            if chk_eth_bridgd(eth,br) == False:
                logging.debug("iface-bridge is failed from %s to %s"%(eth,br))
                err_count+=1
            else:
                logging.debug("iface-bridge is passed from %s to %s"%(eth,br))
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) == False:
                logging.debug("iface-unbridge is failed for %s"%br)
                err_count+=1
            else:
                logging.debug("iface-unbridge is passed for %s"%br)
        if org_state=='inactive':
            iface.ifdown(opt) 
        if err_count > 0:
            return False
        else:
            return True
    #print chk_virsh_bridged_unbridged('eth1')
    def chk_virsh_brd_unbrd_str_des_df_undf(opt):
        err_count_2=0
        if iface.avail_vir_iface(opt):
            iface.network_scripts_backup(opt)
            if chk_virsh_bridged_unbridged(opt)==False:
                err_count_2+=1
            iface.network_scripts_restore(opt)
        else:
            iface.create_iface_xml(opt)
            virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
            if chk_virsh_bridged_unbridged(opt) == False:
                err_count_2+=1
            virsh.iface_undefine("%s" %opt, ignore_status=True)
            iface.destroy_iface_xml(opt)
        if err_count_2 >0:
           return False
        else:
           return True
    #print chk_virsh_brd_unbrd_str_des_df_undf('eth1')
    
    def chk_virsh_brd_unbrd_str_des_df_undf_all():
        error_count=0
        logging.debug("Bridge/Unbridge test would be run on")
        logging.debug("following interfaces")
        logging.debug("%s"%iface.input_ifaces())
        for ind_iface in iface.input_ifaces():
            if iface.is_ipaddr(ind_iface) == False:
                if chk_virsh_brd_unbrd_str_des_df_undf(ind_iface) == False:
                    logging.debug("start destroy is failed for  %s"%ind_iface)
                    error += 1
                else:
                    logging.debug("start destroy is passed for %s"%ind_iface)
            else: 
                logging.debug("Bridge/Unbridge testing is ruled out")
                logging.debug("as %s is hosting an ipaddress"%ind_iface)
        if error_count >0:
           return False
        else:
           return True
    logging.debug("%s"%chk_virsh_brd_unbrd_str_des_df_undf_all())
    
