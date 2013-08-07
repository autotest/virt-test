#!/usr/bin/python
import os,logging
from autotest.client.shared import error
from virttest import virsh, iface
"""
Test case:
Verify virsh iface-list. The interface which are having network scripts
those are only eligible for listed in virsh iface-list

Steps:

1. Veify virsh iface-list --all and compare the mac & status of them
2. Veify virsh iface-list  and compare the mac & status of them
3. Veify virsh iface-list --inactive and compare the mac & status of them

Input:
All the interfaces available in the host other than bridged intercace
 and virsh internal network interface (virbr0,vnet0...)

"""


def run_virsh_iface_list(test, params, env):
    def check_virsh_list_all():
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface):
                if iface.avail_vir_iface(ind_iface):
                    logging.debug("virsh iface-list --all "
                    "shows iface %s as expected"%ind_iface)
                    if iface.chk_state_vir_iface(ind_iface) is False:
                        raise error.TestFail("virsh list --all shows wrongly "
                        "for the state of %s"%ind_iface)
                    else:
                        logging.debug("virsh list --all shows correctly "
                        "for the state of %s"%ind_iface)
                    if iface.chk_mac_vir_iface(ind_iface) is False:
                        raise error.TestFail("virsh list --all shows "
                        "wrongly for the mac of %s"%ind_iface)
                    else:
                        logging.debug("virsh list --all shows "
                        "correctly for the mac of %s"%ind_iface)
                else:
                    raise error.TestFail("virsh iface-list --all does "
                    "not show iface %s"%ind_iface)
            else:
                if iface.avail_vir_iface(ind_iface):
                    raise error.TestFail("virsh iface-list --all should "
                    "not show iface %s"%ind_iface)
                else: 
                    logging.debug("virsh iface-list --all is "
                    "not showing iface %s as expected"%ind_iface)


    def check_virsh_list_active():
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface) and iface.is_up(ind_iface):
                if iface.avail_vir_iface_active(ind_iface):
                    logging.debug("virsh iface-list "
                    "shows iface %s as expected"%ind_iface)
                    if iface.chk_state_vir_iface_active(ind_iface) is False:
                        raise error.TestFail("virsh list shows wrongly "
                        "for the state of %s"%ind_iface)
                    else:
                        logging.debug("virsh list shows correctly "
                        "for the state of %s"%ind_iface)
                    if iface.chk_mac_vir_iface_active(ind_iface) is False:
                        raise error.TestFail("virsh list  shows "
                        "wrongly for the mac of %s"%ind_iface)
                    else:     
                        logging.debug("virsh list  shows "
                        "correctly for the mac of %s"%ind_iface)
                else:
                    raise error.TestFail("virsh iface-list does "
                    "not show iface %s"%ind_iface)
            else:
                if iface.avail_vir_iface_active(ind_iface):
                    raise error.TestFail("virsh iface-list should "
                    "not show iface %s"%ind_iface)
                else:
                    logging.debug("virsh iface-list is "
                                  "not showing iface %s as expected"%ind_iface)

    def check_virsh_list_inactive():
        for ind_iface in iface.input_ifaces():
            if iface.is_scr_avail(ind_iface)  and iface.is_up(ind_iface) is False:
                if iface.avail_vir_iface_inactive(ind_iface):
                    logging.debug("virsh iface-list --inactive "
                                   "shows iface %s as expected"%ind_iface)
                    if iface.chk_state_vir_iface(ind_iface) is False:
                        raise error.TestFail("virsh list --inactive shows wrongly "
                                             "for the state of %s"%ind_iface)
                    else: 
                        logging.debug("virsh list --inactive shows correctly "
                                      "for the state of %s"%ind_iface)
                    if iface.chk_mac_vir_iface(ind_iface) is False:
                        raise error.TestFail("virsh list --inactive shows "
                                             "wrongly for the mac of %s"%ind_iface)
                    else: 
                        logging.debug("virsh list --inactive shows "
                        "correctly for the mac of %s"%ind_iface)
                else:
                    raise error.TestFail("virsh iface-list --inactive does "
                    "not show iface %s"%ind_iface)
            else:
                if iface.avail_vir_iface_inactive(ind_iface):
                    raise error.TestFail("virsh iface-list --inactive should "
                                        "not show iface %s"%ind_iface)
                else: 
                    logging.debug("virsh iface-list --inactive is "
                                  "not showing iface %s as expected"%ind_iface)

    options_ref = params.get("iface_list_option","");
    if options_ref == '--all':
        check_virsh_list_all()
    elif options_ref == '--inactive':
        check_virsh_list_inactive()
    else:
        check_virsh_list_active()
