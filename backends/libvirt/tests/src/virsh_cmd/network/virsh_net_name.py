from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh net-name.

    The command can convert a network UUID to network name.
    1.Get all parameters from config file.
    2.Perform virsh net-uuid operation.
    3.Confirm the test result.`
    """
    vm_ref = params.get("net_name_vm_ref")
    net_name = params.get("net_name_network", "default")
    extra = params.get("net_name_extra", "")
    status_error = params.get("status_error")

    net_uuid = virsh.net_uuid(net_name)
    if vm_ref == "uuid":
        vm_ref = net_uuid
    elif vm_ref == "name":
        vm_ref = net_name

    result = virsh.net_name(vm_ref, extra, ignore_status=True)
    status = result.exit_status
    output = result.stdout.strip()
    err = result.stderr.strip()

    # check status_error
    if status_error == "yes":
        if status == 0 or err == "":
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0 or output == "":
            raise error.TestFail("Run failed with right command")
