#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm,iface
from virttest.libvirt_xml import vm_xml
from virttest.iface import *
"""
Test case:
Verify virsh iface-list. The interface which are having network scripts
those are only eligible for listed in virsh iface-list

Steps:

1. Veify virsh iface-list --all and compare the mac and status of them
2. Veify virsh iface-list  and compare the mac and status of them
3. Veify virsh iface-list --inactive and compare the mac and status of them

Input:
The interface whose network scripts are availble
"""


def run_virsh_iface_list(test, params, env):
    def check_virsh_list_all():
        error=0
        for ind_iface in input_ifaces():
            if is_scr_avail(ind_iface) == 'yes':
                if avail_vir_iface(ind_iface) == 'yes':
                    if chk_state_vir_iface(ind_iface) == 'FAIL': 
                        logging.debug("virsh list --all shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if chk_mac_vir_iface(ind_iface) == 'FAIL':
                        logging.debug("virsh list --all shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list --all does")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
            else:
                if avail_vir_iface(ind_iface) == 'yes':
                    logging.debug("virsh iface-list --all should")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
        if error > 0:
            return 'FAIL'
        else:
            return 'PASS'
    
    
    def check_virsh_list_active():
        error=0
        for ind_iface in input_ifaces():
            if is_scr_avail(ind_iface) == 'yes' and is_up(ind_iface)=='yes' :
                if avail_vir_iface_active(ind_iface) == 'yes':
                    if chk_state_vir_iface_active(ind_iface) == 'FAIL':
                        logging.debug("virsh list shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if chk_mac_vir_iface_active(ind_iface) == 'FAIL':
                        logging.debug("virsh list  shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list does")
                    logging.debug("not show iface %s"%ind_iface)

                    error += 1
            else:
                if avail_vir_iface_active(ind_iface) == 'yes':
                    logging.debug("virsh iface-list should")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
        if error > 0:
            return 'FAIL'
        else:
            return 'PASS'
    
    def check_virsh_list_inactive():
        error=0
        for ind_iface in input_ifaces():
            if is_scr_avail(ind_iface) == 'yes'  and is_up(ind_iface)=='no':
                if avail_vir_iface_inactive(ind_iface) == 'yes':
                    if chk_state_vir_iface(ind_iface) == 'FAIL':
                        logging.debug("virsh list --inactive shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if chk_mac_vir_iface(ind_iface) == 'FAIL':
                        logging.debug("virsh list --inactive shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list --inactive does")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
            else:
                if avail_vir_iface_inactive(ind_iface) == 'yes':
                    logging.debug("virsh iface-list --inactive should")
                    logging.debug("not show iface %s"%ind_iface)

                    error += 1
        if error > 0:
            return 'FAIL'
        else:
            return 'PASS'
    
    options_ref = params.get("iface_list_option","");
    if options_ref == '--all':
        return check_virsh_list_all()
    elif options_ref == '--inactive':
        return check_virsh_list_inactive()
    else:
        return check_virsh_list_active()

