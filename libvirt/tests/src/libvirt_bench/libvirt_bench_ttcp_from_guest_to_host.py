import time
import logging

from autotest.client import os_dep, utils
from autotest.client.shared import error
from virttest import virsh, utils_net


def run_libvirt_bench_ttcp_from_guest_to_host(test, params, env):
    """
    Test steps:

    1) Check the environment and get the params from params.
    2) while(loop_time < timeout):
            ttcp command.
    3) clean up.
    """
    # Find the ttcp command.
    try:
        os_dep.command("ttcp")
    except ValueError:
        raise error.TestNAError("Not find ttcp command on host.")
    # Get VM.
    vm = env.get_vm(params.get("main_vm", "virt-tests-vm1"))
    session = vm.wait_for_login()
    status, _ = session.cmd_status_output("which ttcp")
    if status:
        raise error.TestNAError("Not find ttcp command on guest.")
    # Get parameters from params.
    timeout = int(params.get("LB_ttcp_timeout", "600"))
    ttcp_server_command = params.get("LB_ttcp_server_command",
                                     "ttcp -s -r -v -D -p5015 &")
    ttcp_client_command = params.get("LB_ttcp_client_command",
                                     "ttcp -s -t -v -D -p5015 -b65536 -l65536 -n1000 -f K")

    try:
        current_time = int(time.time())
        end_time = current_time + timeout
        # Start the loop from current_time to end_time.
        while current_time < end_time:
            utils.run(ttcp_server_command)
            status, output = session.cmd_status_output("%s %s" %
                                                       (ttcp_client_command,
                                                        utils_net.get_host_ip_address(params)))
            if status:
                raise error.TestFail("Failed to run ttcp command on guest.\n"
                                     "Detail: %s." % output)
            current_time = int(time.time())
    finally:
        # Clean up.
        logging.debug("No clean up operation for this test.")
