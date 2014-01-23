import re
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh net-destroy.

    The command can forcefully stop a given network.
    1.Make sure the network exists.
    2.Prepare network status.
    3.Perform virsh net-destroy operation.
    4.Check if the network has been destroied.
    5.Recover network environment.
    6.Confirm the test result.
    """

    net_ref = params.get("net_destroy_net_ref")
    extra = params.get("net_destroy_extra", "")
    network_name = params.get("net_destroy_network", "default")
    network_status = params.get("net_destroy_status", "active")
    status_error = params.get("status_error", "no")

    # Confirm the network exists.
    output_all = virsh.net_list("--all").stdout.strip()
    if not re.search(network_name, output_all):
        raise error.TestNAError("Make sure the network exists!!")

    # Run test case
    if net_ref == "uuid":
        net_ref = virsh.net_uuid(network_name).stdout.strip()
    elif net_ref == "name":
        net_ref = network_name

    # Get status of network and prepare network status.
    network_current_status = "active"
    try:
        if not virsh.net_state_dict()[network_name]['active']:
            network_current_status = "inactive"
            if network_status == "active":
                virsh.net_start(network_name)
        else:
            if network_status == "inactive":
                virsh.net_destroy(network_name)
    except error.CmdError:
        raise error.TestError("Prepare network status failed!")

    status = virsh.net_destroy(net_ref, extra,
                               ignore_status=True).exit_status

    # Confirm the network has been destroied.
    if virsh.net_state_dict()[network_name]['active']:
        status = 1

    # Recover network status
    try:
        if (network_current_status == "active" and
                not virsh.net_state_dict()[network_name]['active']):
            virsh.net_start(network_name)
        if (network_current_status == "inactive" and
                virsh.net_state_dict()[network_name]['active']):
            virsh.net_destroy(network_name)
    except error.CmdError:
        raise error.TestError("Recover network status failed!")

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
    else:
        raise error.TestError("The status_error must be 'yes' or 'no'!")
