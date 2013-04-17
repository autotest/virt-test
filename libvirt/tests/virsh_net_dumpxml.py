from autotest.client.shared import error
from virttest import virsh

def run_virsh_net_dumpxml(test, params, env):
    """
    Test command: virsh net-dumpxml.

    This command can output the network information as an XML dump to stdout.
    1.Get all parameters from config file.
    2.If test case's network status is inactive, destroy it.
    3.Perform virsh net-dumpxml operation.
    4.Recover test environment(network status).
    5.Confirm the test result.
    """
    status_error = params.get("status_error", "no")
    net_ref = params.get("net_dumpxml_net_ref")
    net_name = params.get("net_dumpxml_network", "default")
    net_status = params.get("net_dumpxml_network_status", "active")
    extra = params.get("net_dumpxml_extra", "")

    # Run test case
    if net_ref == "uuid":
        net_ref = virsh.net_uuid(net_name).stdout.strip()
    elif net_ref == "name":
        net_ref = net_name

    net_status_current = "active"
    if not virsh.net_state_dict()[net_name]['active']:
        net_status_current = "inactive"

    if not virsh.net_state_dict()[net_name]['persistent']:
        raise error.TestFail("Network is transient!")

    if net_status == "inactive" and net_status_current == "active":
        s = virsh.net_destroy(net_name, ignore_status=True).exit_status
        if s != 0:
            raise error.TestFail("Network destroied failed!")

    result = virsh.net_dumpxml(net_ref, extra, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()
    if extra.find("--") != -1:
        options = extra.split("--")
        for option in options:
            if option.strip() == "":
                continue
            if not virsh.has_command_help_match("net-dumpxml", option.strip()):
                status_error = "yes"
                break

    # Recover network
    if net_status == "inactive" and net_status_current == "active":
        s = virsh.net_start(net_name, ignore_status=True).exit_status
        if s != 0:
            raise error.TestFail("Network started failed!")

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        if output == "":
            raise error.TestFail("The command has no detail outputed!")
    else:
        raise error.TestFail("The status_error must be 'yes' or 'no'!")
