#!/usr/bin/python
import logging
from autotest.client.shared import error
from virttest import virsh, utils_net
"""
Test case:
Verify virsh iface-list. The interface which are having network scripts
those are only eligible for listed in virsh iface-list

Steps:

1. Veify virsh iface-list --all and compare the mac & status of them
2. Veify virsh iface-list  and compare the mac & status of them
3. Veify virsh iface-list --inactive and compare the mac & status of them
3. Veify virsh iface-list --xyz and ensure it should fail

Input:
All the interfaces available in the host other than the interfaces which
are not poted to any bridge(eth0,vnet0... in below e.g).
brctl show
bridge name	bridge id		STP enabled	interfaces
br0		8000.e41f13180acc	yes		eth0
							vnet0
							vnet2
							vnet5
virbr0		8000.525400895d70	yes		virbr0-nic
							vnet1
							vnet3
							vnet4


"""


def run_virsh_iface_list(test, params, env):
    def check_virsh_list_all(ifa,chk_ifc_virsh):
        if ifa.avail_net_scr() and not ifa.is_brport():
            if chk_ifc_virsh['avail']:
                if chk_ifc_virsh['isup'] != ifa.is_up():
                    raise error.TestFail("virsh list --all shows wrongly "
                    "for the state of %s"%opt)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list --all shows "
                    "wrongly for the mac of %s"%opt)
            else:
                raise error.TestFail("virsh iface-list --all does "
                "not show iface %s"%opt)
        else:
            if chk_ifc_virsh['avail']:
                raise error.TestFail("virsh iface-list --all should "
                "not show iface %s"%opt)


    def check_virsh_list_active(ifa,chk_ifc_virsh):
        if ifa.avail_net_scr() and not ifa.is_brport() and ifa.is_up():
            if chk_ifc_virsh['avail']:
                if not chk_ifc_virsh['isup']:
                    raise error.TestFail("virsh list shows wrongly "
                    "for the state of %s"%opt)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list  shows "
                    "wrongly for the mac of %s"%opt)
            else:
                raise error.TestFail("virsh iface-list  does "
                "not show iface %s"%opt)
        else:
            if chk_ifc_virsh['avail']:
                raise error.TestFail("virsh iface-list --active should "
                "not show iface %s"%opt)


    def check_virsh_list_inactive(ifa,chk_ifc_virsh):
        if ifa.avail_net_scr() and not ifa.is_brport() and not ifa.is_up():
            if chk_ifc_virsh['avail']:
                if chk_ifc_virsh['isup']:
                    raise error.TestFail("virsh list --inactive shows wrongly "
                                         "for the state of %s"%opt)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list --inactive shows "
                                         "wrongly for the mac of %s"%opt)
            else:
                raise error.TestFail("virsh iface-list --inactive does "
                "not show iface %s"%opt)
        else:
            if chk_ifc_virsh['avail']:
                raise error.TestFail("virsh iface-list --inactive should "
                                    "not show iface %s"%opt)


    options_ref = params.get("iface_list_option","");
    result=virsh.iface_list(options_ref,ignore_status=True)
    status_error = params.get("status_error", "no")
    if status_error == "yes":
        if result.exit_status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if result.exit_status == 1:
            raise error.TestFail("Run unsuccessfully with proper command!")
        for ind_iface in utils_net.get_net_if():
            ifa=utils_net.Interface(ind_iface)
            chk_ifc_virsh=virsh.virsh_ifaces(ind_iface,options_ref)
            if options_ref == '--all':
                check_virsh_list_all(ifa,chk_ifc_virsh)
            elif options_ref == '--inactive':
                check_virsh_list_inactive(ifa,chk_ifc_virsh)
            else:
                check_virsh_list_active(ifa,chk_ifc_virsh)
        
