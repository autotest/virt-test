import os
import re
import logging
from tempfile import mktemp

from virttest import virsh
from autotest.client.shared import error
from virttest.libvirt_xml.nodedev_xml import NodedevXML


_FC_HOST_PATH = "/sys/class/fc_host"


def check_nodedev(dev_name, dev_parent=None):
    """
    Check node device relevant values
    :params dev_name: name of the device
    :params dev_parent: parent name of the device, None is default
    """
    host = dev_name.split("_")[1]
    fc_host_path = os.path.join(_FC_HOST_PATH, host)

    # Check if the /sys/class/fc_host/host$NUM exists
    if not os.access(fc_host_path, os.R_OK):
        logging.debug("Can't access %s", fc_host_path)
        return False

    dev_xml = NodedevXML.new_from_dumpxml(dev_name)
    if not dev_xml:
        logging.error("Can't dumpxml %s XML", dev_name)
        return False

    # Check device parent name
    if dev_parent != dev_xml.parent:
        logging.error("The parent name is different: %s is not %s",
                      dev_parent, dev_xml.parent)
        return False

    wwnn_from_xml = dev_xml.wwnn
    wwpn_from_xml = dev_xml.wwpn
    fabric_wwn_from_xml = dev_xml.fabric_wwn

    fc_dict = {}
    name_list = ["node_name", "port_name", "fabric_name"]
    for name in name_list:
        fc_file = os.path.join(fc_host_path, name)
        fc_dict[name] = open(fc_file, "r").read().strip().split("0x")[1]

    # Check wwnn, wwpn and fabric_wwn
    if len(wwnn_from_xml) != 16 or \
        len(wwpn_from_xml) != 16 or \
        fc_dict["node_name"] != wwnn_from_xml or \
        fc_dict["port_name"] != wwpn_from_xml or \
            fc_dict["fabric_name"] != fabric_wwn_from_xml:
        logging.debug("The fc_dict is: %s", fc_dict)
        return False

    fc_type_from_xml = dev_xml.fc_type
    cap_type_from_xml = dev_xml.cap_type

    # Check capability type
    if cap_type_from_xml != "scsi_host" or fc_type_from_xml != "fc_host":
        logging.debug("The capability type isn't 'scsi_host' or 'fc_host'")
        return False

    return True


def create_nodedev_from_xml(params):
    """
    Create a device defined by an XML file on the node
    :params: the parameter dictionary
    """
    scsi_host = params.get("nodedev_scsi_host")
    options = params.get("nodedev_options")
    status_error = params.get("status_error", "no")

    vhba_xml = """
<device>
    <parent>%s</parent>
    <capability type='scsi_host'>
        <capability type='fc_host'>
        </capability>
    </capability>
</device>
""" % scsi_host

    logging.debug("Prepare the nodedev XML: %s", vhba_xml)

    vhba_file = mktemp()
    xml_object = open(vhba_file, 'w')
    xml_object.write(vhba_xml)
    xml_object.close()

    result = virsh.nodedev_create(vhba_file, options)
    status = result.exit_status

    # Remove temprorary file
    os.unlink(vhba_file)

    # Check status_error
    if status_error == "yes":
        if status:
            logging.info("It's an expected %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            output = result.stdout
            logging.info(output)
            for scsi in output.split():
                if scsi.startswith('scsi_host'):
                    # Check node device
                    if check_nodedev(scsi, scsi_host):
                        return scsi
                    else:
                        raise error.TestFail("Can't find %s", scsi)


def destroy_nodedev(params):
    """
    Destroy (stop) a device on the node
    :params: the parameter dictionary
    """
    dev_name = params.get("nodedev_new_dev")
    options = params.get("nodedev_options")
    status_error = params.get("status_error", "no")

    result = virsh.nodedev_destroy(dev_name, options)
    status = result.exit_status

    # Check status_error
    if status_error == "yes":
        if status:
            logging.info("It's an expected %s", result.stderr)
        else:
            raise error.TestFail("%d not a expected command "
                                 "return value", status)
    elif status_error == "no":
        if status:
            raise error.TestFail(result.stderr)
        else:
            # Check nodedev value
            if not check_nodedev(dev_name):
                logging.info(result.stdout)
            else:
                raise error.TestFail("The relevant directory still exists"
                                     "or mismatch with result")


def find_devices_by_cap(cap_type="scsi_host"):
    """
    Find device by capability
    :params cap_type: capability type
    """
    result = virsh.nodedev_list('--cap %s' % cap_type)
    if result.exit_status:
        raise error.TestFail(result.stderr)

    scsi_hosts = result.stdout.strip().splitlines()
    return scsi_hosts


def check_vport_ops_cap(scsi_hosts):
    """
    Check vport operation capability
    :params scsi_hosts: list of the scsi_host
    """
    vport_ops_list = []
    for scsi_host in scsi_hosts:
        result = virsh.nodedev_dumpxml(scsi_host)
        if result.exit_status:
            raise error.TestFail(result.stderr)
        if re.search('vport_ops', result.stdout.strip()):
            vport_ops_list.append(scsi_host)

    logging.debug("The vport_ops list: %s", vport_ops_list)
    return vport_ops_list


def check_port_connectivity(vport_ops_list):
    """
    Check port connectivity
    :params vport_ops_list: list of the vport operation
    """
    port_state_dict = {}
    port_linkup = []
    port_linkdown = []
    fc_path = "/sys/class/fc_host"
    for scsi_host in vport_ops_list:
        port_state = scsi_host.split('_')[1] + "/port_state"
        port_state_file = os.path.join(fc_path, port_state)
        logging.debug("The port_state file: %s", port_state_file)
        state = open(port_state_file).read().strip()
        logging.debug("The port state: %s", state)
        if state == "Online" or state == "Linkup":
            port_linkup.append(scsi_host)
        if state == "Offline" or state == "Linkdown":
            port_linkdown.append(scsi_host)

    port_state_dict["online"] = port_linkup
    port_state_dict["offline"] = port_linkdown

    return port_state_dict


def run(test, params, env):
    """
    Test create/destroy node device

    1) Positive testing
       1.1) create node device from XML file
       1.2) destroy node device
    2) Negative testing
       2.1) create node device with noexist name of the parent HBA
       2.2) create node device with offline port
       2.3) create node device with invalid option
       2.4) destroy noexist node device
       2.5) destroy node device with invalid option
       2.6) destroy node device without capable of vport operations
    """
    # Run test case
    options = params.get("nodedev_options")
    dev_name = params.get("nodedev_dev_name")
    status_error = params.get("status_error", "no")
    no_vport_ops = params.get("nodedev_no_vport_ops", "no")
    port_state = params.get("nodedev_port_state", "offline")
    create_device = params.get("nodedev_create_device", "no")

    # Find available HBAs
    scsi_hosts = find_devices_by_cap()

    # Find available vHBA
    vport_ops_list = check_vport_ops_cap(scsi_hosts)

    # No HBA or no vHBA supporting
    if not vport_ops_list:
        raise error.TestNAError("No HBAs to support vHBA on the host!")

    # Check ports connectivity
    port_state_dict = check_port_connectivity(vport_ops_list)

    # Get ports list of the online and offline
    port_online_list = port_state_dict["online"]
    port_offline_list = port_state_dict["offline"]

    # No online port is available
    if not port_online_list:
        raise error.TestNAError("No port is active!")

    if dev_name:
        # Negative testing for creating device
        params["nodedev_scsi_host"] = dev_name
        # Negative testing for destroying device
        params["nodedev_new_dev"] = dev_name
    elif port_state == "online" or options:
        # Pick up one online port for positive testing
        params["nodedev_scsi_host"] = port_online_list[0]
        # Negative testing with invalid option
        params["nodedev_new_dev"] = port_online_list[0]
    elif no_vport_ops == "yes":
        # Negative testing for not capable of vport operations
        if port_offline_list:
            params["nodedev_new_dev"] = port_offline_list[0]
    else:
        # Pick up one offline port for negative testing
        if port_offline_list:
            params["nodedev_scsi_host"] = port_offline_list[0]

    # positive and negative testing #########

    if status_error == "no":
        try:
            # Create device from XML
            params["nodedev_new_dev"] = create_nodedev_from_xml(params)
            # Destroy the device
            destroy_nodedev(params)
        except error.TestFail, detail:
            raise error.TestFail("Failed to create/destroy node device.\n"
                                 "Detail: %s." % detail)

    if status_error == "yes":
        if create_device == "yes":
            # Create device from XML
            create_nodedev_from_xml(params)
        if create_device == "no":
            # Destroy the device
            destroy_nodedev(params)
