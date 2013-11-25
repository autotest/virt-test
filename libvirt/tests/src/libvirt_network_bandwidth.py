import os
import time

from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir
from virttest.libvirt_xml.vm_xml import VMXML
from virttest.libvirt_xml.network_xml import NetworkXML, PortgroupXML


def run_libvirt_network_bandwidth(test, params, env):
    """
    Test for network bandwidth in libvirt.

    1. Preparation:
        * Init variables from params.
        * Keep a backup for vmxml and networkxml.
        * Build a file with dd command.
    2. Edit vmxml and networkxml to control the bandwidth.
    3. Verify the bandwidth with scp.
    4. Clean up.
    """
    # get the params from params
    vm_name = params.get("main_vm", "virt-tests-vm1")
    vm = env.get_vm(vm_name)

    inbound_average = params.get("LNB_inbound_average", "512")
    inbound_peak = params.get("LNB_inbound_peak", "512")
    inbound_burst = params.get("LNB_inbound_burst", "32")

    outbound_average = params.get("LNB_outbound_average", "512")
    outbound_peak = params.get("LNB_outbound_peak", "512")
    outbound_burst = params.get("LNB_outbound_burst", "32")

    config_type = params.get("LNB_config_type", "network")

    bandwidth_tolerance = float(params.get("LNB_bandwidth_tolerance", "20")) / 100

    file_size = params.get("LNB_verify_file_size", "10")

    nic1_params = params.object_params('nic1')
    nettype = params.get('nettype')
    netdst = params.get('netdst')

    vm_xml = VMXML.new_from_inactive_dumpxml(vm_name)
    vm_xml_backup = vm_xml.copy()

    # This test assume that VM is using default network.
    # Check the interfaces of VM to make sure default network
    # is used by VM.
    interfaces = vm_xml.get_devices(device_type="interface")
    # interface which is using default network.
    default_interface = None
    for interface in interfaces:
        if interface.source == {nettype: netdst}:
            default_interface = interface
            break
    if not default_interface:
        raise error.TestNAError("VM is not using default network,"
                                "skip this test.")

    bandwidth_inbound = {'average': inbound_average,
                         'peak': inbound_peak,
                         'burst': inbound_burst}
    bandwidth_outbound = {'average': outbound_average,
                          'peak': outbound_peak,
                          'burst': outbound_burst}

    network_xml = NetworkXML.new_from_net_dumpxml("default")
    network_xml_backup = network_xml.copy()

    tmp_dir = data_dir.get_tmp_dir()
    file_path = os.path.join(tmp_dir, "scp_file")
    # Init a QemuImg instance.
    cmd = "dd if=/dev/zero of=%s bs=1M count=%s" % (file_path, file_size)
    utils.run(cmd)
    try:
        if config_type == "network":
            network_xml.bandwidth_inbound = bandwidth_inbound
            network_xml.bandwidth_outbound = bandwidth_outbound
            network_xml.sync()
        elif config_type == "interface":
            devices = vm_xml.devices
            for index in range(len(devices)):
                if not (devices[index].device_tag ==
                        default_interface.device_tag):
                    continue
                if devices[index].mac_address == default_interface.mac_address:
                    default_interface.bandwidth_inbound = bandwidth_inbound
                    default_interface.bandwidth_outbound = bandwidth_outbound
                    devices[index] = default_interface
                    break
            vm_xml.devices = devices
            vm_xml.sync()
        elif config_type == "portgroup":
            # Add a portgroup into default network
            portgroup_name = "test_portgroup"
            portgroup = PortgroupXML()
            portgroup.name = portgroup_name
            portgroup.bandwidth_inbound = bandwidth_inbound
            portgroup.bandwidth_outbound = bandwidth_outbound
            network_xml.portgroup = portgroup
            network_xml.sync()
            # Using the portgroup in VM.
            devices = vm_xml.devices
            for index in range(len(devices)):
                if not (devices[index].device_tag ==
                        default_interface.device_tag):
                    continue
                if devices[index].mac_address == default_interface.mac_address:
                    default_interface.portgroup = portgroup_name
                    devices[index] = default_interface
                    break
            vm_xml.devices = devices
            vm_xml.sync()
        else:
            raise error.TestNAError("Unsupported parameter config_type=%s." %
                                    config_type)

        # SCP to check the network bandwidth.
        if vm.is_alive():
            vm.destroy()
        vm.start()
        vm.wait_for_login()
        time_before = time.time()
        vm.copy_files_to(host_path=file_path, guest_path="/root")
        time_after = time.time()

        speed_expected = int(inbound_average)
        speed_actual = (10 * 1024 / (time_after - time_before))
        if not (abs(speed_actual - speed_expected) <=
                speed_expected * bandwidth_tolerance):
            raise error.TestFail("Speed from host to guest is %s.\n"
                                 "But the average of bandwidth.inbound is %s.\n"
                                 % (speed_actual, speed_expected))
        time_before = time.time()
        vm.copy_files_from(host_path=file_path, guest_path="/root/scp_file")
        time_after = time.time()

        speed_expected = int(outbound_average)
        speed_actual = (10 * 1024 / (time_after - time_before))
        if not (abs(speed_actual - speed_expected) <=
                speed_expected * bandwidth_tolerance):
            raise error.TestFail("Speed from guest to host is %s.\n"
                                 "But the average of bandwidth.outbound is %s\n"
                                 % (speed_actual, speed_expected))

    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
        network_xml_backup.sync()
        vm_xml_backup.sync()
