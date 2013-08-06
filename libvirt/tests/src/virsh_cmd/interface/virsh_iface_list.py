#!/usr/bin/python
import os,logging, fileinput, re, os.path
from autotest.client.shared import utils,error
from virttest import virsh, libvirt_vm,iface
from virttest.libvirt_xml import vm_xml
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
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface):
                if iface.avail_vir_iface(ind_iface):
                    if iface.chk_state_vir_iface(ind_iface) == False: 
                        logging.debug("virsh list --all shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if iface.chk_mac_vir_iface(ind_iface) == False:
                        logging.debug("virsh list --all shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list --all does")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
            else:
                if iface.avail_vir_iface(ind_iface):
                    logging.debug("virsh iface-list --all should")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
        if error > 0:
            return False
        else:
            return True
    
    
    def check_virsh_list_active():
        error=0
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface) and iface.is_up(ind_iface):
                if iface.avail_vir_iface_active(ind_iface):
                    if iface.chk_state_vir_iface_active(ind_iface) == False:
                        logging.debug("virsh list shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if iface.chk_mac_vir_iface_active(ind_iface) == False:
                        logging.debug("virsh list  shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list does")
                    logging.debug("not show iface %s"%ind_iface)

                    error += 1
            else:
                if iface.avail_vir_iface_active(ind_iface):
                    logging.debug("virsh iface-list should")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
        if error > 0:
            return False
        else:
            return True
    
    def check_virsh_list_inactive():
        error=0
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface)  and iface.is_up(ind_iface)==False:
                if iface.avail_vir_iface_inactive(ind_iface):
                    if iface.chk_state_vir_iface(ind_iface) == False:
                        logging.debug("virsh list --inactive shows wrong")
                        logging.debug("for the state of %s"%ind_iface)
                        error += 1
                    if iface.chk_mac_vir_iface(ind_iface) == False:
                        logging.debug("virsh list --inactive shows")
                        logging.debug("wrong for the mac of %s"%ind_iface)
                        error += 1
                else:
                    logging.debug("virsh iface-list --inactive does")
                    logging.debug("not show iface %s"%ind_iface)
                    error += 1
            else:
                if iface.avail_vir_iface_inactive(ind_iface):
                    logging.debug("virsh iface-list --inactive should")
                    logging.debug("not show iface %s"%ind_iface)

                    error += 1
        if error > 0:
            return False
        else:
            return True
    
    options_ref = params.get("iface_list_option","");
    if options_ref == '--all':
        return check_virsh_list_all()
    elif options_ref == '--inactive':
        return check_virsh_list_inactive()
    else:
        return check_virsh_list_active()

