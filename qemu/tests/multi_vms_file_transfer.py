import time, os, logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import remote, utils_misc


@error.context_aware
def run_multi_vms_file_transfer(test, params, env):
    """
    Transfer a file back and forth between multi VMs for long time.

    1) Boot up two VMs .
    2) Create a large file by dd on host.
    3) Copy this file to VM1.
    4) Compare copied file's md5 with original file.
    5) Copy this file from VM1 to VM2.
    6) Compare copied file's md5 with original file.
    7) Copy this file from VM2 to VM1.
    8) Compare copied file's md5 with original file.
    9) Repeat step 5-8

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """


    def md5_check(session, orig_md5):
        msg = "Compare copied file's md5 with original file."
        error.context(msg, logging.info)
        md5_cmd = "md5sum %s | awk '{print $1}'" % guest_path
        s, o = session.cmd_status_output(md5_cmd)
        if s:
            msg = "Fail to get md5 value from guest. Output is %s" % o
            raise error.TestError(msg)
        new_md5 = o.splitlines()[-1]
        if new_md5 != orig_md5:
            msg = "File changed after transfer host -> VM1. Original md5 value"
            msg += " is %s. Current md5 value is %s" % (orig_md5, new_md5)
            raise error.TestFail(msg)


    vm1 = env.get_vm(params["main_vm"])
    vm1.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    vm2 = env.get_vm(params["vms"].split()[-1])
    vm2.verify_alive()

    session_vm1 = vm1.wait_for_login(timeout=login_timeout)
    session_vm2 = vm2.wait_for_login(timeout=login_timeout)

    transfer_timeout = int(params.get("transfer_timeout", 1000))
    username = params.get("username")
    password = params.get("password")
    port = int(params.get("file_transfer_port"))
    if (not port) or (not username) or (not password):
        raise error.TestError("Please set file_transfer_port, username,"
                               " password paramters for guest")
    tmp_dir = params.get("tmp_dir", "/tmp/")
    repeat_time = int(params.get("repeat_time", "20"))
    clean_cmd = params.get("clean_cmd", "rm -f")
    filesize = int(params.get("filesize", 4000))

    host_path = os.path.join(tmp_dir, "tmp-%s" %
                             utils_misc.generate_random_string(8))
    dd_cmd = "dd if=/dev/zero of=%s bs=1M count=%d oflag=direct"
    dd_cmd = params.get("dd_cmd", dd_cmd)
    dd_cmd = dd_cmd % (host_path, filesize)
    guest_path = (tmp_dir + "file_transfer-%s" %
                  utils_misc.generate_random_string(8))
    try:
        error.context("Creating %dMB file on host" % filesize, logging.info)
        utils.run(dd_cmd)
        orig_md5 = utils.hash_file(host_path, method="md5")
        error.context("Transfering file host -> VM1, timeout: %ss" % \
                       transfer_timeout, logging.info)
        t_begin = time.time()
        vm1.copy_files_to(host_path, guest_path, timeout=transfer_timeout)
        t_end = time.time()
        throughput = filesize / (t_end - t_begin)
        logging.info("File transfer host -> VM1 succeed, "
                     "estimated throughput: %.2fMB/s", throughput)
        md5_check(session_vm1, orig_md5)

        src_vm = vm1
        dst_vm = vm2
        for i in range(repeat_time):
            log_file = "scp_%s_to_%s_%s.log" % (src_vm.name, dst_vm.name, i)
            log_f = os.path.join(test.debugdir, log_file)

            msg = "Transfering file %s -> %s, timeout: %ss." % (src_vm.name,
                                                dst_vm.name, transfer_timeout)
            msg += " Repeat:%s/%s" % (i + 1, repeat_time)
            error.context(msg, logging.info)
            t_begin = time.time()
            src_ip = src_vm.get_address()
            dst_ip = dst_vm.get_address()
            remote.scp_between_remotes(src=src_ip, dst=dst_ip, port=port,
                                       s_passwd=password, d_passwd=password,
                                       s_name=username, d_name=username,
                                       s_path=guest_path, d_path=guest_path,
                                       timeout=transfer_timeout,
                                       log_filename=log_f)
            t_end = time.time()
            throughput = filesize / (t_end - t_begin)
            msg = "File transfer %s -> %s succeed, " % (src_vm.name,
                                                         dst_vm.name)
            msg += "estimated throughput: %.2fMB/s" % throughput
            logging.info(msg)
            session_dst = dst_vm.wait_for_login(timeout=login_timeout)
            md5_check(session_dst, orig_md5)
            tmp_vm = dst_vm
            dst_vm = src_vm
            src_vm = tmp_vm
    finally:
        try:
            session_vm1.cmd("%s %s" % (clean_cmd, guest_path))
        except Exception:
            pass
        try:
            session_vm2.cmd("%s %s" % (clean_cmd, guest_path))
        except Exception:
            pass
        try:
            os.remove(host_path)
        except OSError:
            pass
        if session_vm1:
            session_vm1.close()
        if session_vm2:
            session_vm2.close()
