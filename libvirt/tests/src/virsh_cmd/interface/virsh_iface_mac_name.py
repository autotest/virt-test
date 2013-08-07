#!/usr/bin/python
import os,logging
from autotest.client.shared import error
from virttest import virsh,iface
"""
Test case:
Verify virsh iface-mac,iface-name. The interface which are having network
scripts those are only eligible for listed in virsh iface-mac and iface-name

Steps:

1. Veify virsh iface-mac should give the mac of the interface  for defined 
   interfaces and should not for undefined interfaces
2. Veify virsh iface-name should give the name of the interface for define
   interfaces and should not for undefined interfaces


Input:
All the interfaces available in the host other than bridged intercace
 and virsh internal network interface (virbr0,vnet0...) and localhost(lo)

"""

def run_virsh_iface_mac_name(test, params, env):
    def check_virsh_mac_name():
        for name_iface in iface.input_ifaces():
            if name_iface != 'lo':
                mac_iface=iface.mac_of_iface(name_iface).lower()
                if iface.avail_vir_iface(name_iface):
                    ac_op=virsh.iface_mac("%s" %name_iface).stdout.strip()
                    ex_op= iface.mac_vir_iface(name_iface)
                    if ac_op != ex_op:
                        raise error.TestFail("virsh ifac-mac of " 
                        "%s is failed for virsh available iface"%name_iface)
                    else:
                        logging.debug("virsh ifac-mac of "
                        "%s is passed for virsh available iface"%name_iface)
                    ac_op=virsh.iface_name("%s" %mac_iface)
                    ac_op=ac_op.stdout.strip() 
                    ex_op=iface.iface_vir_mac(mac_iface)
                    if ac_op != ex_op:
                        raise error.TestFail("virsh iface-name of "
                        "%s is failed for virsh available iface"%mac_iface)
                    else:  
                        logging.debug("virsh iface-name of "
                        "%s is passed for virsh available iface"%mac_iface)

                else:
                    ac_op=virsh.iface_mac("%s" %name_iface).stdout.strip()
                    if ac_op: 
                        raise error.TestFail("virsh ifac-mac of "
                        "%s is failed for virsh unavailable iface"%name_iface)
                    else:
                        logging.debug("virsh ifac-mac of "
                        "%s is passed for virsh unavailable iface"%name_iface)
                    ac_op=virsh.iface_name("%s" %mac_iface)
                    ac_op=ac_op.stdout.strip() 
                    if ac_op: 
                        raise error.TestFail("virsh iface-name of "
                        "%s is failed for virsh unavailable iface"%mac_iface)
                    else:
                        logging.debug("virsh iface-name of "
                        "%s is passed for virsh unavailable iface"%mac_iface)



    check_virsh_mac_name()
