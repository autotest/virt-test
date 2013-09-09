import logging
import re
import os
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc

STEP_1, STEP_2, STEP_3, STEP_4, STEP_5, STEP_6 = range(6)


@error.context_aware
def run_nfs_perf(test, params, env):
    """
    KVM nfs performance test:
    1) boot guest over virtio driver.
    2) mount nfs server in guest with tcp protocol.
    3) test write performance in guest using dd commands.
    4) test read performance in guest using dd commands.

    Note: This test is used for performance benchmark test,
          not for the functional test usage. The result of
          this test depends on the regression.py tool,
          though you can run it during function testing,
          you may not get any possible error report from
          this script directly.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """
    def _do_clean_up(func, *args):
        try:
            if args:
                func(*args)
            else:
                func()
        except Exception, e:
            logging.warn("Failed to execute function '%s'."
                         " error message:\n%s", func.__name__, e)

    def _clean_up(step_cnt):
        error.context("Clean up", logging.info)
        if step_cnt >= STEP_5:
            # remove test file.
            cmd = "rm -f %s" % " ".join(test_file_list)
            _do_clean_up(session.cmd, cmd)
        if step_cnt >= STEP_4:
            # umount nfs partition.
            cmd = "umount %s" % mnt_point
            _do_clean_up(session.cmd, cmd)
        if step_cnt >= STEP_3:
            # remove mount ponit directory.
            cmd = "rm -rf %s" % mnt_point
            _do_clean_up(session.cmd, cmd)
        if step_cnt >= STEP_2:
            # close result file.
            _do_clean_up(result_file.close)
        if step_cnt >= STEP_1:
            # close session.
            _do_clean_up(session.close)

    def _do_write_test(blk_size, test_file):
        # Clean up caches
        session.cmd("echo 3 >/proc/sys/vm/drop_caches")

        error.context("test %s size block write performance in guest"
                      " using dd commands" % blk_size, logging.info)
        dd_cmd = "dd"
        dd_cmd += " if=/dev/zero"
        dd_cmd += " of=%s" % test_file
        dd_cmd += " bs=%s" % blk_size
        dd_cmd += " oflag=direct"
        dd_cmd += " count=10000"
        try:
            out = session.cmd_output(dd_cmd, timeout=test_timeout)
        except Exception:
            _clean_up(STEP_4)
            raise

        return out

    def _do_read_test(blk_size, test_file):
        # Clean up caches
        session.cmd("echo 3 >/proc/sys/vm/drop_caches")

        error.context("test %s size block read performance in guest"
                      " using dd commands" % blk_size, logging.info)
        dd_cmd = "dd"
        dd_cmd += " if=%s" % test_file
        dd_cmd += " of=/dev/null"
        dd_cmd += " bs=%s" % blk_size
        dd_cmd += " iflag=direct"
        try:
            out = session.cmd_output(dd_cmd, timeout=test_timeout)
        except Exception:
            _clean_up(STEP_5)
            raise
        # After STEP 6

        return out

    if not hasattr(test, "write_perf_keyval"):
        raise error.TestNAError("There is no 'write_perf_keyval' method in"
                                " test object, skip this test")

    error.context("boot guest over virtio driver", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    test_timeout = int(params["test_timeout"])
    session = vm.wait_for_login(timeout=timeout)
    guest_ver = session.cmd_output("uname -r").strip()
    host_ver = os.uname()[2]
    kvm_ver = utils.system_output(
        params.get('kvm_userspace_ver_cmd', "rpm -q qemu-kvm"))
    # After STEP 1

    try:
        result_name = params.get("result_name", "nfs-perf.RHS")
        result_file_path = utils_misc.get_path(test.resultsdir, result_name)
        result_file = open(result_file_path, 'w')
    except Exception:
        _clean_up(STEP_1)
        raise
    # After STEP 2

    error.context("mount nfs server in guest with tcp protocol", logging.info)
    nfs_server = params.get("nfs_server")
    nfs_path = params.get("nfs_path")
    mnt_option = params.get("mnt_option")
    mnt_point = "/tmp/nfs_perf_%s" % utils_misc.generate_random_string(4)
    test_file_prefix = os.path.join(mnt_point, "test_%si_" %
                                    utils_misc.generate_random_string(4))

    blk_size_list = params.get("blk_size_list", "8k").split()
    test_file_list = map(lambda x: test_file_prefix + x, blk_size_list)

    if (not nfs_server) or (not nfs_path) or (not mnt_point):
        _clean_up(STEP_2)
        raise error.TestError("Missing configuration for nfs partition."
                              " Check your config files")

    try:
        session.cmd("mkdir -p %s" % mnt_point)
    except Exception:
        _clean_up(STEP_2)
        raise
    # After STEP 3
    # Prepare nfs partition.
    mnt_cmd = "mount"
    mnt_cmd += " -t nfs"
    if mnt_option:
        mnt_cmd += " -o %s" % mnt_option
    mnt_cmd += " %s:%s" % (nfs_server, nfs_path)
    mnt_cmd_out = mnt_cmd + " /tmp/***_****_****"
    mnt_cmd += " %s" % mnt_point
    try:
        session.cmd(mnt_cmd)
    except Exception:
        _clean_up(STEP_3)
        raise
    # After STEP 4

    # Record mount command in result file.
    try:
        result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
        result_file.write("### kvm_version : %s\n" % host_ver)
        result_file.write("### guest-kernel-ver : %s\n" % guest_ver)
        result_file.write("### %s\n" % mnt_cmd_out)
        result_file.write("Category:ALL\n")
    except (IOError, ValueError), e:
        logging.error("Failed to write to result file,"
                      " error message:\n%s", e)

    result_list = ["%s|%016s|%016s" % ("blk_size", "Write", "Read")]
    speed_pattern = r"(\d+ bytes).*?([\d\.]+ s).*?([\d\.]+ [KkMmGgTt])B/s"
    try:
        prefix = "nfs"
        for blk_size in blk_size_list:
            prefix += "--%s" % blk_size
            test_file = test_file_list[blk_size_list.index(blk_size)]
            result = "%08s|" % blk_size[:-1]
            # Get write test result.
            out = _do_write_test(blk_size, test_file)
            tmp_list = re.findall(speed_pattern, out)
            if not tmp_list:
                _clean_up(STEP_5)
                raise error.TestError("Could not get correct write result."
                                      " dd cmd output:\n%s" % out)
            _, _, speed = tmp_list[0]
            speed = utils_misc.normalize_data_size(speed)
            result += "%016s|" % speed
            test.write_perf_keyval({"%s--%s" % (prefix, "write"): speed})

            # Get read test result.
            out = _do_read_test(blk_size, test_file)
            tmp_list = re.findall(speed_pattern, out)
            if not tmp_list:
                _clean_up(STEP_6)
                raise error.TestError("Could not get correct read result."
                                      " dd cmd output:\n%s" % out)
            _, _, speed = tmp_list[0]
            speed = utils_misc.normalize_data_size(speed)
            result += "%016s" % speed
            test.write_perf_keyval({"%s--%s" % (prefix, "read"): speed})
            # Append result into result list.
            result_list.append(result)
    finally:
        try:
            result_file.write("\n".join(result_list))
        except (IOError, ValueError), e:
            logging.error("Failed to write to result file,"
                          " error message:\n%s", e)

    _clean_up(STEP_6)
