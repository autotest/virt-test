import logging
import time
import tempfile
import os
from autotest.client.shared import error
from virttest import qemu_storage, data_dir, utils_misc


def run(test, params, env):
    """
    libvirt boot savevm test:

    1) Start guest booting
    2) Record origin informations of snapshot list for floppy(optional).
    3) Periodically savevm/loadvm while guest booting
    4) Stop test when able to login, or fail after timeout seconds.
    5) Check snapshot list for floppy and compare with the origin
       one(optional).

    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    if params.get("with_floppy") == "yes":
        floppy_name = params.get("floppies", "fl")
        floppy_params = {"image_format": params.get("floppy_format", "qcow2"),
                         "image_size": params.get("floppy_size", "1.4M"),
                         "image_name": params.get("%s_name" % floppy_name,
                                                  "images/test"),
                         "vm_type": params.get("vm_type"),
                         "qemu_img_binary": utils_misc.get_qemu_img_binary(params)}
        floppy = qemu_storage.QemuImg(floppy_params,
                                      data_dir.get_data_dir(), floppy_name)
        floppy.create(floppy_params)
        floppy_orig_info = floppy.snapshot_list()
        vm.create(params=params)

    vm.verify_alive()  # This shouldn't require logging in to guest
    savevm_delay = float(params["savevm_delay"])
    savevm_login_delay = float(params["savevm_login_delay"])
    savevm_login_timeout = float(params["savevm_timeout"])
    savevm_statedir = params.get("savevm_statedir", tempfile.gettempdir())
    fd, savevm_statefile = tempfile.mkstemp(
        suffix='.img', prefix=vm.name + '-',
        dir=savevm_statedir)
    os.close(fd)  # save_to_file doesn't need the file open
    start_time = time.time()
    cycles = 0

    successful_login = False
    while (time.time() - start_time) < savevm_login_timeout:
        logging.info("Save/Restore cycle %d", cycles + 1)
        time.sleep(savevm_delay)
        vm.pause()
        if params['save_method'] == 'save_to_file':
            vm.save_to_file(savevm_statefile)  # Re-use same filename
            vm.restore_from_file(savevm_statefile)
        else:
            vm.savevm("1")
            vm.loadvm("1")
        vm.resume()  # doesn't matter if already running or not
        vm.verify_kernel_crash()  # just in case
        try:
            vm.wait_for_login(timeout=savevm_login_delay)
            successful_login = True  # not set if timeout expires
            os.unlink(savevm_statefile)  # don't let these clutter disk
            break
        except:
            pass  # loop until successful login or time runs out
        cycles += 1

    time_elapsed = int(time.time() - start_time)
    info = "after %s s, %d load/save cycles" % (time_elapsed, cycles + 1)
    if not successful_login:
        raise error.TestFail("Can't log on '%s' %s" % (vm.name, info))
    else:
        logging.info("Test ended %s", info)

    if params.get("with_floppy") == "yes":
        vm.destroy()
        floppy_info = floppy.snapshot_list()
        if floppy_info == floppy_orig_info:
            raise error.TestFail("savevm didn't create snapshot in floppy."
                                 "    original snapshot list is: %s"
                                 "    now snapshot list is: %s"
                                 % (floppy_orig_info, floppy_info))
