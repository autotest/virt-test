import os
from autotest.client.shared import error, utils
from virttest import virsh


def run(test, params, env):
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
    xml_flie = params.get("net_dumpxml_xml_file", "default.xml")
    extra = params.get("net_dumpxml_extra", "")
    network_xml = os.path.join(test.tmpdir, xml_flie)

    # Run test case
    if net_ref == "uuid":
        net_ref = virsh.net_uuid(net_name).stdout.strip()
    elif net_ref == "name":
        net_ref = net_name

    net_status_current = "active"
    if not virsh.net_state_dict()[net_name]['active']:
        net_status_current = "inactive"

    if not virsh.net_state_dict()[net_name]['persistent']:
        raise error.TestError("Network is transient!")
    try:
        if net_status == "inactive" and net_status_current == "active":
            status_destroy = virsh.net_destroy(net_name,
                                               ignore_status=True).exit_status
            if status_destroy != 0:
                raise error.TestError("Network destroied failed!")

        result = virsh.net_dumpxml(net_ref, extra, network_xml,
                                   ignore_status=True)
        status = result.exit_status
        err = result.stderr.strip()
        xml_validate_cmd = "virt-xml-validate %s network" % network_xml
        valid_s = utils.run(xml_validate_cmd, ignore_status=True).exit_status

        # Check option valid or not.
        if extra.find("--") != -1:
            options = extra.split("--")
            for option in options:
                if option.strip() == "":
                    continue
                if not virsh.has_command_help_match("net-dumpxml", option.strip()):
                    status_error = "yes"
                    break
    finally:
        # Recover network
        if net_status == "inactive" and net_status_current == "active":
            status_start = virsh.net_start(net_name,
                                           ignore_status=True).exit_status
            if status_start != 0:
                raise error.TestError("Network started failed!")

    # Check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
        if err == "":
            raise error.TestFail("The wrong command has no error outputed!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command!")
        if valid_s != 0:
            raise error.TestFail("Command output is invalid!")
    else:
        raise error.TestError("The status_error must be 'yes' or 'no'!")
