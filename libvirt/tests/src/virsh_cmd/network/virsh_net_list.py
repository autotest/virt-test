import re
import os
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh net-list.

    The command returns list of networks.
    1.Get all parameters from configuration.
    2.Get current network's status(State, Autostart).
    3.Do some prepare works for testing.
    4.Perform virsh net-list operation.
    5.Recover network status.
    6.Confirm the result.
    """
    option = params.get("net_list_option", "")
    extra = params.get("net_list_extra", "")
    status_error = params.get("status_error", "no")
    net_name = params.get("net_list_name", "default")
    persistent = params.get("net_list_persistent", "yes")
    net_status = params.get("net_list_error", "active")
    tmp_xml = os.path.join(test.tmpdir, "tmp.xml")
    net_current_status = "active"
    autostart_status = "yes"
    if not virsh.net_state_dict()[net_name]['active']:
        net_current_status = "inactive"
    if not virsh.net_state_dict()[net_name]['autostart']:
        autostart_status = "no"

    # Create a transient network.
    try:
        if persistent == "no":
            virsh.net_dumpxml(net_name, to_file=tmp_xml, ignore_status=False)
            if net_current_status == "inactive":
                virsh.net_destroy(net_name, ignore_status=False)
            virsh.net_undefine(net_name, ignore_status=False)
            virsh.net_create(tmp_xml, ignore_status=False)
    except error.CmdError:
        raise error.TestFail("Transient network test failed!")

    # Prepare network's status for testing.
    if net_status == "active":
        try:
            if not virsh.net_state_dict()[net_name]['active']:
                virsh.net_start(net_name, ignore_status=False)
        except error.CmdError:
            raise error.TestFail("Active network test failed!")
    else:
        try:
            if virsh.net_state_dict()[net_name]['active']:
                virsh.net_destroy(net_name, ignore_status=False)
        except error.CmdError:
            raise error.TestFail("Inactive network test failed!")

    result = virsh.net_list(option, extra, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()

    # Recover network
    try:
        if persistent == "no":
            virsh.net_destroy(net_name, ignore_status=False)
            virsh.net_define(tmp_xml, ignore_status=False)
            if net_current_status == "active":
                virsh.net_start(net_name, ignore_status=False)
            if autostart_status == "yes":
                virsh.net_autostart(net_name, ignore_status=False)
        else:
            if net_current_status == "active" and net_status == "inactive":
                virsh.net_start(net_name, ignore_status=False)
            elif net_current_status == "inactive" and net_status == "active":
                virsh.net_destroy(net_name, ignore_status=False)
    except error.CmdError:
        raise error.TestFail("Recover network failed!")

    # check result
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
        if option == "--inactive":
            if net_status == "active":
                if re.search(net_name, output):
                    raise error.TestFail("Found an active network with"
                                         " --inactive option")
            else:
                if persistent == "yes":
                    if not re.search(net_name, output):
                        raise error.TestFail("Found no inactive networks with"
                                             " --inactive option")
                else:
                    # If network is transient, after net-destroy it,
                    # it will disapear.
                    if re.search(net_name, output):
                        raise error.TestFail("Found transient inactive networks"
                                             " with --inactive option")
        elif option == "":
            if net_status == "active":
                if not re.search(net_name, output):
                    raise error.TestFail("Can't find active network with no"
                                         " option")
            else:
                if re.search(net_name, output):
                    raise error.TestFail("Found inactive network with"
                                         " no option")
        elif option == "--all":
            if net_status == "active":
                if not re.search(net_name, output):
                    raise error.TestFail("Can't find active network with"
                                         " --all option")
            else:
                if persistent == "yes":
                    if not re.search(net_name, output):
                        raise error.TestFail("Can't find inactive network with"
                                             " --all option")
                else:
                    # If network is transient, after net-destroy it,
                    # it will disapear.
                    if re.search(net_name, output):
                        raise error.TestFail("Found transient inactive network"
                                             " with --all option")
