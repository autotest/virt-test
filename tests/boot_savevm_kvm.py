import logging, time
from autotest.client.shared import error
from autotest.client.virt import kvm_monitor, kvm_storage


def run_boot_savevm_kvm(test, params, env):
    """
    KVM boot savevm test:

    1) Start guest.
    2) Record origin informations of snapshot list for floppy(optional).
    3) Periodically savevm/loadvm.
    4) Log into the guest to verify it's up, fail after timeout seconds.
    5) Check snapshot list for floppy and compare with the origin
       one(optional).

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    if params.get("with_floppy") == "yes":
        floppy_params = {"image_format": params.get("floppy_format", "qcow2"),
                         "image_size": params.get("floppy_size", "1.4M"),
                         "image_name": params.get("fl_name", "images/test")}
        floppy = kvm_storage.QemuImg(floppy_params, test.bindir, "fl")
        floppy.create(floppy_params)
        floppy_orig_info = floppy.snapshot_list()
        vm.create(params=params)

    vm.verify_alive()
    savevm_delay = float(params.get("savevm_delay"))
    savevm_login_delay = float(params.get("savevm_login_delay"))
    savevm_login_timeout = float(params.get("savevm_timeout"))
    start_time = time.time()

    cycles = 0

    successful_login = False
    while (time.time() - start_time) < savevm_login_timeout:
        logging.info("Save/load cycle %d", cycles + 1)
        time.sleep(savevm_delay)
        try:
            vm.monitor.cmd("stop")
        except kvm_monitor.MonitorError, e:
            logging.error(e)
        try:
            # This should be replaced by a proper monitor method call
            vm.monitor.send_args_cmd("savevm id=1")
        except kvm_monitor.MonitorError, e:
            logging.error(e)
        try:
            vm.monitor.cmd("system_reset")
        except kvm_monitor.MonitorError, e:
            logging.error(e)
        try:
            # This should be replaced by a proper monitor method call
            vm.monitor.send_args_cmd("loadvm id=1")
        except kvm_monitor.MonitorError, e:
            logging.error(e)
        try:
            vm.monitor.cmd("cont")
        except kvm_monitor.MonitorError, e:
            logging.error(e)

        vm.verify_kernel_crash()

        try:
            vm.wait_for_login(timeout=savevm_login_delay)
            successful_login = True
            break
        except:
            pass

        cycles += 1

    time_elapsed = int(time.time() - start_time)
    info = "after %s s, %d load/save cycles" % (time_elapsed, cycles + 1)
    if not successful_login:
        raise error.TestFail("Can't log on '%s' %s" % (vm.name, info))
    else:
        logging.info("Test ended %s", info)

    if params.get("with_floppy")  == "yes":
        vm.destroy()
        floppy_info = floppy.snapshot_list()
        if floppy_info == floppy_orig_info:
            raise error.TestFail("savevm didn't create snapshot in floppy."
                                 "    original snapshot list is: %s"
                                 "    now snapshot list is: %s"
                                 % (floppy_orig_info, floppy_info))
