import os
import time
import logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import data_dir, utils_misc

@error.context_aware
def run_file_copy_stress(test, params, env):
    """
    Transfer a file back and forth between host and guest.

    1) Boot up a VM.
    2) Create a large file by dd on host.
    3) Copy this file from host to guest.
    4) Copy this file from guest to host.
    5) Check if file transfers ended good.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    @error.context_aware
    def do_file_copy(src_file, guest_file, dst_file, transfer_timeout):
        error.context("Transferring file host -> guest,"
                      " timeout: %ss" % transfer_timeout, logging.info)
        vm.copy_files_to(src_file, guest_file, timeout=transfer_timeout)
        error.context("Transferring file guest -> host,"
                      " timeout: %ss" % transfer_timeout, logging.info)
        vm.copy_files_from(guest_file, dst_file, timeout=transfer_timeout)
        error.context("Compare md5sum between original file and"
                      " transferred file", logging.info)

        if (utils.hash_file(src_file, method="md5") !=
                utils.hash_file(dst_file, method="md5")):
            raise error.TestFail("File changed after transfer host -> guest "
                                 "and guest -> host")


    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error.context("Login to guest", logging.info)
    session = vm.wait_for_login(timeout=login_timeout)

    dir_name = data_dir.get_tmp_dir()
    tmp_dir = params.get("tmp_dir", "/var/tmp/")
    clean_cmd = params.get("clean_cmd", "rm -f")
    scp_sessions = int(params.get("scp_para_sessions", 1))
    filesize = float(params.get("filesize", 4000))
    transfer_timeout = float(params.get("transfer_timeout", 600))

    src_path = []
    dst_path = []
    guest_path = []
    for _ in range(scp_sessions):
        random_file_name =  utils_misc.generate_random_string(8)
        src_path.append(os.path.join(dir_name, "h-src-%s" % random_file_name))
        guest_path.append(tmp_dir + "g-tmp-%s" % random_file_name)
        dst_path.append(os.path.join(dir_name, "h-dst-%s" % random_file_name))

    cmd = "dd if=/dev/zero of=%s bs=1M count=%d"
    try:
        for src_file in src_path:
            error.context("Create %dMB file on host" % filesize, logging.info)
            utils.run(cmd % (src_file, filesize))

        stress_timeout = float(params.get("stress_timeout", "3600"))

        error.context("Do file transfer between host and guest", logging.info)
        start_time = time.time()
        stop_time = start_time + stress_timeout
        #here when set a run flag, when other case call this case as a
        #subprocess backgroundly, can set this run flag to False to stop
        #the stress test.
        env["file_transfer_run"] = True
        while (env["file_transfer_run"] and time.time() < stop_time):
            scp_threads = []
            for index in range(scp_sessions):
                scp_threads.append((do_file_copy, (src_path[index],
                                   guest_path[index], dst_path[index],
                                   transfer_timeout)))
            utils_misc.parallel(scp_threads)

    finally:
        env["file_transfer_run"] = False
        logging.info('Cleaning temp file on host and guest')
        for del_file in guest_path:
            session.cmd("%s %s" % (clean_cmd, del_file),
                        ignore_all_errors=True)
        for del_file in src_path + dst_path:
            utils.system("%s %s" % (clean_cmd, del_file), ignore_status=True)

        if session:
            session.close()
