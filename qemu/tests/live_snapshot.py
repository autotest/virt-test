from autotest_lib.client.virt import virt_utils, virt_test_utils
from autotest_lib.client.virt.tests import file_transfer
import time, logging

def run_live_snapshot(test, params, env):
    """
    live_snapshot test:
    1). Create live snapshot during big file creating
    2). Create live snapshot when guest reboot
    3). Check if live snapshot is created
    4). Shutdown guest

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """

    def create_snapshot(vm):
        """
        Create live snapshot:
        1). Check which monitor is used
        2). Get device info
        3). Create snapshot
        """

        cmd = params.get("create_sn_cmd")

        block_info = vm.monitor.info("block")
        if virt_utils.has_option("qmp") and params.get("monitor_type") == "qmp":
            device = block_info[0]["device"]
        else:
            string = ""
            device = string.join(block_info).split(":")[0]
        cmd += " %s" % device

        snapshot_name = params.get("snapshot_name")
        cmd += " %s" % snapshot_name

        format = params.get("snapshot_format")
        if format:
            cmd += " %s" % format
        logging.info("Creating live snapshot ...")
        vm.monitor.send_args_cmd(cmd)

        logging.info("Check snapshot is created ...")
        snapshot_info = str(vm.monitor.info("block"))
        if snapshot_name not in snapshot_info:
            logging.error(snapshot_info)
            raise error.TestFail("Snapshot doesn't exist")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    dd_timeout = int(params.get("dd_timeout", 900))
    session = vm.wait_for_login(timeout=timeout)

    def runtime_test():
        try:
            clean_cmd = params.get("clean_cmd")
            file_create = params.get("file_create")
            clean_cmd += " %s" % file_create
            logging.info("Clean file before creation")
            session.cmd(clean_cmd)

            logging.info("Creating big file...")
            create_cmd = params.get("create_cmd") % file_create

            args = (create_cmd, dd_timeout)
            bg = virt_test_utils.BackgroundTest(session.cmd_output, args)
            bg.start()
            time.sleep(5)
            create_snapshot(vm)
            if bg.is_alive():
                try:
                    bg.join()
                except:
                    raise
        finally:
            session.close()

    def reboot_test():
        try:
            bg = virt_test_utils.BackgroundTest(vm.reboot, (session,))
            logging.info("Rebooting guest ...")
            bg.start()
            sleep_time = int(params.get("sleep_time"))
            time.sleep(sleep_time)
            create_snapshot(vm)
        finally:
            bg.join()

    def file_transfer_test():
        try:
            bg_cmd = file_transfer.run_file_transfer
            args = (test, params, env)
            bg = virt_test_utils.BackgroundTest(bg_cmd, args)
            bg.start()
            sleep_time = int(params.get("sleep_time"))
            time.sleep(sleep_time)
            create_snapshot(vm)
            if bg.is_alive():
                try:
                    bg.join()
                except:
                    raise
        finally:
            session.close()
    subcommand = params.get("subcommand")
    eval("%s_test()" % subcommand)
