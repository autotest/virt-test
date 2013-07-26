#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm,iface
from virttest.libvirt_xml import vm_xml
from virttest.iface import *
"""
Test case:
Verify virsh iface-mac,iface-name. The interface which are having network
scripts those are only eligible for listed in virsh iface-mac and iface-name

Steps:

1. Veify virsh iface-mac should give the mac of the interface
2. Veify virsh iface-name should give the name of the interface

Input:
The interface whose network scripts are availble
"""

def run_virsh_iface_mac_name(test, params, env):
    def check_virsh_mac_name():
        error=0
        for ind_iface in input_ifaces():
            if ind_iface !='lo':
                if avail_vir_iface(ind_iface) == 'yes':
                    ac_op=virsh.iface_mac("%s" %ind_iface).stderr.strip()
                    ex_op= mac_vir_iface(ind_iface)
                    if ac_op != ex_op:
                        logging.debug("virsh ifac-mac of %s"%ind_iface)
                        logging.debug("is failed for available iface")
                        error += 1
                    ac_op=virsh.iface_name("%s" %mac_of_iface(ind_iface))
                    ac_op=ac_op.stderr.strip() 
                    ex_op=iface_vir_mac(mac_of_iface(ind_iface).lower())
                    if ac_op != ex_op:
                        logging.debug("virsh iface-name of")
                        logging.debug("%s"%mac_of_iface(ind_iface)) 
                        logging.debug("is failed for available iface")
                        error += 1
                else:
                    ac_op=virsh.iface_mac("%s" %ind_iface).stderr.strip()
                    ex_op= mac_vir_iface(ind_iface)
                    if ac_op != ex_op:
                        logging.debug("virsh ifac-mac of %s"%ind_iface)
                        logging.debug("is failed for unavailable iface")
                        error += 1
                    ac_op=virsh.iface_name("%s" %mac_of_iface(ind_iface))
                    ac_op=ac_op.stderr.strip()
                    ex_op=iface_vir_mac(mac_of_iface(ind_iface).lower())
                    if ac_op != ex_op:
                        logging.debug("virsh ifac-name of")
                        logging.debug("%s"%mac_of_iface(ind_iface))
                        logging.debug("is failed for unavailable iface")
                        error += 1
        if error > 0:
            return 'FAIL'
        else:
            return 'PASS'

    check_virsh_mac_name()
