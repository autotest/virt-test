import os
import logging

from autotest.client.shared import error
from virttest import utils_test, utils_misc


def run(test, params, env):
    """
    Test steps:

    1) Get the params from params.
    2) Run unixbench on guest.
    3) Dump each VM and check result.
    3) Clean up.
    """
    vms = env.get_all_vms()
    unixbench_control_file = params.get("unixbench_controle_file",
                                        "unixbench5.control")
    # Run unixbench on guest.
    guest_unixbench_pids = []
    params["test_control_file"] = unixbench_control_file
    # Fork a new process to run unixbench on each guest.
    for vm in vms:
        params["main_vm"] = vm.name
        control_path = os.path.join(test.virtdir, "control",
                                    unixbench_control_file)

        session = vm.wait_for_login()
        command = utils_test.run_autotest(vm, session, control_path,
                                          None, None,
                                          params, copy_only=True)
        session.cmd("%s &" % command)

    for vm in vms:
        session = vm.wait_for_login()

        def _is_unixbench_running():
            return (not session.cmd_status("ps -ef|grep perl|grep Run"))
        if not utils_misc.wait_for(_is_unixbench_running, timeout=120):
            raise error.TestNAError("Failed to run unixbench in guest.\n"
                                    "Since we need to run a autotest of unixbench "
                                    "in guest, so please make sure there are some "
                                    "necessary packages in guest, such as gcc, tar, bzip2")

    logging.debug("Unixbench is already running in VMs.")

    try:
        dump_path = os.path.join(test.tmpdir, "dump_file")
        for vm in vms:
            vm.dump(dump_path)
            # Check the status after vm.dump()
            if not vm.is_alive():
                raise error.TestFail("VM is shutoff after dump.")
            if vm.wait_for_shutdown():
                raise error.TestFail("VM is going to shutdown after dump.")
            # Check VM is running normally.
            vm.wait_for_login()
    finally:
        for pid in guest_unixbench_pids:
            utils_misc.kill_process_tree(pid)
        # Destroy VM.
        for vm in vms:
            vm.destroy()
