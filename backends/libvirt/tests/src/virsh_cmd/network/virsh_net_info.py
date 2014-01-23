from autotest.client.shared import error
from virttest import virsh, libvirt_vm
from virttest.libvirt_xml import network_xml

def run(test, params, env):
    """
    Test command: virsh net-info <network>

    The command returns basic information about virtual network.
    """

    # Gather test parameters
    uri = libvirt_vm.normalize_connect_uri(params.get("connect_uri",
                                                      "default"))
    status_error = params.get("status_error", "no")
    net_name = params.get("testing_net_name", "default")
    net_ref = params.get("netinfo_net_ref", "name")
    extra = params.get("netinfo_options_extra", "")

    virsh_dargs = {'uri': uri, 'debug': True, 'ignore_status': True}
    virsh_instance = virsh.VirshPersistent(**virsh_dargs)

    # Get all network instance
    origin_nets = network_xml.NetworkXML.new_all_networks_dict(virsh_instance)

    # Prepare network for following test.
    try:
        netxml = origin_nets[net_name]
    except KeyError:
        virsh_instance.close_session()
        raise error.TestNAError("'%s' virtual network doesn't exist." % net_name)

    if net_ref == "name":
        net_ref = netxml.name
    elif net_ref == "uuid":
        net_ref = netxml.uuid
    elif net_ref.find("invalid") != -1:
        net_ref = params.get(net_ref)

    # Run test case
    result = virsh.net_info(net_ref, extra, **virsh_dargs)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()

    virsh_instance.close_session()

    # Check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
