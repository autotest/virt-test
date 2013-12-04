import os
import re
import time
import random
import logging
from autotest.client.shared import error, utils
from virttest import test_setup, utils_net, utils_misc, env_process


def check_network_interface_ip(interface, ipv6="no"):
    check_cmd = "ifconfig %s" % interface
    status = utils.system_output(check_cmd)
    ip_re = "inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    if ipv6 == "yes":
        ip_re = "inet6 (\S+)"
    try:
        _ip = re.findall(ip_re, status)[0]
    except IndexError:
        _ip = None
    return _ip


def ifup_down_interface(interface, action="up"):
    check_cmd = "ifconfig %s" % interface
    status = utils.system_output(check_cmd)
    if action == "up":
        if not check_network_interface_ip(interface):
            if "UP" in status.splitlines()[0]:
                utils.system("ifdown %s" % interface, timeout=120,
                             ignore_status=True)
            utils.system("ifup %s" % interface, timeout=120, ignore_status=True)
    elif action == "down":
        if "UP" in status.splitlines()[0]:
            utils.system("ifdown %s" % interface, timeout=120,
                         ignore_status=True)
    else:
        msg = "Unsupport action '%s' on network interface." % action
        raise error.TestError(msg)


@error.context_aware
def run_sr_iov_sanity(test, params, env):
    """
    SR-IOV devices sanity test:
    1) Bring up VFs by following instructions How To in Setup.
    2) Configure all VFs in host.
    3) Check whether all VFs get ip in host.
    4) Unbind PFs/VFs from host kernel driver to sr-iov driver.
    5) Bind PFs/VFs back to host kernel driver.
    6) Repeat step 4, 5.
    7) Try to boot up guest(s) with VF(s).

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    device_driver = params.get("device_driver", "pci-assign")
    repeat_time = int(params.get("bind_repeat_time", 1))
    pci_assignable = test_setup.PciAssignable(
        driver=params.get("driver"),
        driver_option=params.get("driver_option"),
        host_set_flag=1,
        kvm_params=params.get("kvm_default"),
        vf_filter_re=params.get("vf_filter_re"),
        pf_filter_re=params.get("pf_filter_re"),
        device_driver=device_driver)

    devices = []
    device_type = params.get("device_type", "vf")
    if device_type == "vf":
        device_num = pci_assignable.get_vfs_count()
    elif device_type == "pf":
        device_num = len(pci_assignable.get_pf_vf_info())
    else:
        msg = "Unsupport device type '%s'." % device_type
        msg += " Please set device_type to 'vf' or 'pf'."
        raise error.TestError(msg)

    for i in xrange(device_num):
        device = {}
        device["type"] = device_type
        if device_type == "vf":
            device['mac'] = utils_net.generate_mac_address_simple()
        if params.get("device_name"):
            device["name"] = params.get("device_name")
        devices.append(device)

    pci_assignable.devices = devices
    vf_pci_id = []
    pf_vf_dict = pci_assignable.get_pf_vf_info()
    for pf_dict in pf_vf_dict:
        vf_pci_id.extend(pf_dict["vf_ids"])

    ethname_dict = []
    ips = {}

    msg = "Configure all VFs in host."
    error.context(msg, logging.info)
    for pci_id in vf_pci_id:
        cmd = "ls /sys/bus/pci/devices/%s/net/" % pci_id
        ethname = utils.system_output(cmd).strip()
        ethname_dict.append(ethname)
        network_script = os.path.join("/etc/sysconfig/network-scripts",
                                      "ifcfg-%s" % ethname)
        if not os.path.exists(network_script):
            error.context("Create %s file." % network_script, logging.info)
            txt = "DEVICE=%s\nONBOOT=yes\nBOOTPROTO=dhcp\n" % ethname
            file(network_script, "w").write(txt)

    msg = "Check whether VFs could get ip in host."
    error.context(msg, logging.info)
    for ethname in ethname_dict:
        ifup_down_interface(ethname)
        _ip = check_network_interface_ip(ethname)
        if not _ip:
            msg = "Interface '%s' could not get IP." % ethname
            logging.error(msg)
        else:
            ips[ethname] = _ip
            logging.info("Interface '%s' get IP '%s'", ethname, _ip)

    for i in xrange(repeat_time):
        msg = "Bind/unbind device from host. Repeat %s/%s" % (i + 1,
                                                              repeat_time)
        error.context(msg, logging.info)
        bind_device_num = random.randint(1, device_num)
        pci_assignable.request_devs(devices[:bind_device_num])
        logging.info("Sleep 3s before releasing vf to host.")
        time.sleep(3)
        pci_assignable.release_devs()
        logging.info("Sleep 3s after releasing vf to host.")
        time.sleep(3)
        if device_type == "vf":
            post_device_num = pci_assignable.get_vfs_count()
        else:
             post_device_num = len(pci_assignable.get_pf_vf_info())
        if post_device_num != device_num:
            msg = "lspci cannot report the correct PF/VF number."
            msg += " Correct number is '%s'" % device_num
            msg += " lspci report '%s'" % post_device_num
            raise error.TestFail(msg)
    dmesg = utils.system_output("dmesg")
    file_name = "host_dmesg_after_unbind_device.txt"
    logging.info("Log dmesg after bind/unbing device to '%s'.", file_name)
    utils_misc.log_line(file_name, dmesg)
    msg = "Check whether VFs still get ip in host."
    error.context(msg, logging.info)
    for ethname in ips:
        ifup_down_interface(ethname, action="up")
        _ip = check_network_interface_ip(ethname)
        if not _ip:
            msg = "Interface '%s' could not get IP." % ethname
            msg += "Before bind/unbind it have IP '%s'." % ips[ethname]
            logging.error(msg)
        else:
            logging.info("Interface '%s' get IP '%s'", ethname, _ip)

    msg = "Try to boot up guest(s) with VF(s)."
    error.context(msg, logging.info)
    for vm_name in params["vms"].split(" "):
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.verify_alive()
        vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
