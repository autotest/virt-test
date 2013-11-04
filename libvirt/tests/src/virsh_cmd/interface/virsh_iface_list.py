#!/usr/bin/python
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
All the interfaces available in the host.

Otput:
Virsh iface-list only returns those interfaces whose are not bridged
or bonded and it's network script file should be available
"""


def run_virsh_iface_list(test, params, env):
    def check_virsh_list_all(ifa,chk_ifc_virsh):
        if ifa.avail_net_scr() and not bridged_bonded:
            if chk_ifc_virsh['avail']:
                if chk_ifc_virsh['isup'] != ifa.is_up():
                    raise error.TestFail("virsh list --all shows wrongly "
                    "for the state of %s"%ifa.name)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list --all shows "
                    "wrongly for the mac of %s"%ifa.name)
            else:
                raise error.TestFail("virsh iface-list --all does "
                "not show iface %s"%ifa.name)
        else:
            if chk_ifc_virsh['avail']:
                if ifa.is_brport():
                    raise error.TestFail("virsh iface-list --all should "
                                    "not show bridged port %s"%ifa.name)
                elif ifa.is_bonded():
                    raise error.TestFail("virsh iface-list --all should "
                                    "not show slave iface %s"%ifa.name)
                else:
                    raise error.TestFail("virsh iface-list --all should "
                                    "not show iface %s as network sciprt"
                                    "is not available"%ifa.name)


    def check_virsh_list_active(ifa,chk_ifc_virsh):
        if ifa.avail_net_scr() and not bridged_bonded and ifa.is_up():
            if chk_ifc_virsh['avail']:
                if not chk_ifc_virsh['isup']:
                    raise error.TestFail("virsh list shows wrongly "
                    "for the state of %s"%ifa.name)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list  shows "
                    "wrongly for the mac of %s"%ifa.name)
            else:
                raise error.TestFail("virsh iface-list  does "
                "not show iface %s"%ifa.name)
        else:
            if chk_ifc_virsh['avail']:
                if ifa.is_brport():
                    raise error.TestFail("virsh iface-list should "
                                    "not show bridged port %s"%ifa.name)
                elif ifa.is_bonded():
                    raise error.TestFail("virsh iface-list should "
                                    "not show slave iface %s"%ifa.name)
                elif not ifa.is_up():
                    raise error.TestFail("virsh iface-list should"
                                    "not show inactive iface %s"%ifa.name)
                else:
                    raise error.TestFail("virsh iface-list should "
                                    "not show iface %s as network sciprt"
                                    "is not available"%ifa.name)



    def check_virsh_list_inactive(ifa,chk_ifc_virsh):
        
        if ifa.avail_net_scr() and not bridged_bonded and not ifa.is_up():
            if chk_ifc_virsh['avail']:
                if chk_ifc_virsh['isup']:
                    raise error.TestFail("virsh list --inactive shows wrongly "
                                         "for the state of %s"%ifa.name)
                if chk_ifc_virsh['mac'].upper() != ifa.get_mac():
                    raise error.TestFail("virsh list --inactive shows "
                                         "wrongly for the mac of %s"%ifa.name)
            else:
                raise error.TestFail("virsh iface-list --inactive does "
                "not show iface %s"%ifa.name)
        else:
            if chk_ifc_virsh['avail']:
                if ifa.is_brport():
                    raise error.TestFail("virsh iface-list --inactive should "
                                    "not show bridged port %s"%ifa.name)
                elif ifa.is_bonded():
                    raise error.TestFail("virsh iface-list --inactive should "
                                    "not show slave iface %s"%ifa.name)
                elif ifa.is_up():
                    raise error.TestFail("virsh iface-list --inactive should"
                                    "not show active iface %s"%ifa.name)
                else:
                    raise error.TestFail("virsh iface-list --inactive should "
                                    "not show iface %s as network sciprt"
                                    "is not available"%ifa.name)




    options_ref = params.get("iface_list_option","");
    result=virsh.iface_list(options_ref,ignore_status=True)
    status_error = params.get("status_error", "no")
    bridged_bonded=True
    if status_error == "yes":
        if result.exit_status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    else:
        if result.exit_status == 1:
            raise error.TestFail("Run unsuccessfully with proper command!")
        for ind_iface in utils_net.get_net_if():
            ifa=utils_net.Interface(ind_iface)
            chk_ifc_virsh=virsh.virsh_ifaces(ind_iface,options_ref)
            if not ifa.is_brport() and not ifa.is_bonded():
                bridged_bonded=False
            else:
                bridged_bonded=True
            if options_ref == '--all':
                check_virsh_list_all(ifa,chk_ifc_virsh)
            elif options_ref == '--inactive':
                check_virsh_list_inactive(ifa,chk_ifc_virsh)
            else:
                check_virsh_list_active(ifa,chk_ifc_virsh)
        
