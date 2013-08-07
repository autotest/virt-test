#!/usr/bin/python
import os,logging
from autotest.client.shared import error
from virttest import virsh,iface
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
All the interfaces available in the host other than bridged intercace,
 virsh internal network interface (virbr0,vnet0...) and the interfaces
where ipaddresses are configured


"""

def run_virsh_iface_bridge_unbridge(test, params, env):
    def avail_vir_dbl_ifaces(iface_y,iface_n):
        if iface.avail_vir_iface(iface_y):
            if iface.chk_mac_vir_iface(iface_y) and iface.state_vir_iface(iface_y)=='active':
                logging.debug("%s is defined with proper mac and active"%iface_y)
            else:
                raise error.TestFail("%s is neither defined with proper mac nor active"%iface_y)
        else:
            raise error.TestFail("%s is not defined"%iface_y)
        if iface.avail_vir_iface(iface_n):
            raise error.TestFail("%s is defined"%iface_n)

    def chk_eth_bridgd(eth,br):
        if iface.is_bridge(br):
            if iface.eth_of_brdg(br) == eth:
                if avail_vir_dbl_ifaces(br,eth) is False:
                    raise error.TestFail("verification of % & %s are failed"%(br,eth))
            else:
                raise error.TestFail("%s is not the ethernet of %s"%(eth,br))
        else:
            raise error.TestFail("%s is not a bridge"%br)

    def chk_br_unbridgd(br,eth):
        if iface.is_bridge(br) is False:
            if iface.is_bridged(eth) is False:
                if avail_vir_dbl_ifaces(eth,br) is False:
                    raise error.TestFail("verification of %s and %s are failed"%(br,eth))
            else:
                raise error.TestFail("%s is still bridged"%(eth))
        else:
            raise error.TestFail("%s is still a bridge"%br)

    def chk_virsh_bridged_unbridged(opt):
        org_state=iface.state_vir_iface(opt)
        if iface.is_bridge(opt):
            logging.debug("%s is a bridge"%opt)
            br=opt
            eth=iface.eth_of_brdg(opt)
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) is False:
                raise error.TestFail("iface-unbridge is failed for %s"%br)
            else:
                logging.debug("iface-unbridge is passed for %s"%br)
            virsh.iface_bridge("%s %s" %(eth,br), "",ignore_status=True)
            if chk_eth_bridgd(eth,br) is False:
                raise error.TestFail("iface-bridge is failed from %s to %s"%(eth,br))
            else:
                logging.debug("iface-bridge is passed from %s to %s"%(eth,br))
        else:
            logging.debug("%s is not a bridge"%opt)
            eth=opt
            br="br-%s"%opt
            virsh.iface_bridge("%s %s" %(eth,br),"", ignore_status=True)
            if chk_eth_bridgd(eth,br) is False:
                raise error.TestFail("iface-bridge is failed from %s to %s"%(eth,br))
            else:
                logging.debug("iface-bridge is passed from %s to %s"%(eth,br))
            virsh.iface_unbridge("%s" %br, ignore_status=True)
            if chk_br_unbridgd(br,eth) is False:
                raise error.TestFail("iface-unbridge is failed for %s"%br)
            else:
                logging.debug("iface-unbridge is passed for %s"%br)
        if org_state=='inactive':
            iface.ifdown(opt)

    def chk_virsh_brd_unbrd_df_undf(opt):
        if iface.avail_vir_iface(opt):
            iface.network_scripts_backup(opt)
            chk_virsh_bridged_unbridged(opt) 
            iface.network_scripts_restore(opt)
        else:
            iface.create_iface_xml(opt)
            virsh.iface_define("tmp-%s.xml" %opt, ignore_status=True)
            chk_virsh_bridged_unbridged(opt) 
            virsh.iface_undefine("%s" %opt, ignore_status=True)
            iface.destroy_iface_xml(opt)

    def chk_virsh_brd_unbrd_df_undf_all():
        logging.debug("Bridge/Unbridge test would be run on "
        "following interfaces "
        "%s"%iface.input_ifaces())
        for ind_iface in iface.input_ifaces():
            if iface.is_ipaddr(ind_iface) is False:
                chk_virsh_brd_unbrd_df_undf(ind_iface)
            else:
                logging.debug("Bridge/Unbridge testing is ruled out "
                "as %s is hosting an ipaddress"%ind_iface)

    chk_virsh_brd_unbrd_df_undf_all()

