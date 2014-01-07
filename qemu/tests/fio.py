import logging
import os
import commands
import threading
import re
import glob
import time
from autotest.client.shared import error
from virttest import utils_misc
from virttest import utils_test
from virttest import data_dir
from autotest.client import utils


def format_result(result, base="12", fbase="2"):
    """
    Format the result to a fixed length string.

    @param result: result need to convert
    @param base: the length of converted string
    @param fbase: the decimal digit for float
    """
    if isinstance(result, str):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    return value % result


def check_status(session, timeout):
    disk_status_cmd = "echo list disk > cmd &&"
    disk_status_cmd += " echo exit >> cmd && diskpart /s cmd"
    disks = []
    start_time = time.time()
    while time.time() - start_time < timeout:
        disks_str = session.cmd(disk_status_cmd)
        logging.info("disks_str is %s" % disks_str)
        if len(re.findall("Disk 1", disks_str)) >= 1:
            disks = re.findall("Disk 1.*\n", disks_str)
            break
    return disks


@error.context_aware
def run_fio(test, params, env):
    """
    Block performance test with fio
    Step1: run test seanario
    Step2: analyse result
    Step3: Put result in ***.RHS which can be used by regression.py
    """
    def seup_env(session, vm):
        fio_dir = data_dir.get_deps_dir()
        fio_file = params.get("fio_file")
        vm.copy_files_to("%s/%s" % (fio_dir, fio_file), "/tmp/")
        session.cmd("cd /tmp/ && tar -xjf /tmp/%s" % fio_file)
        session.cmd("cd /tmp/%s && %s" % (fio_file.rstrip(".tar.bz2"),
                    params.get("compile_cmd")))

    def cpu_thread(cpu_cmd, cpufile):
        cpu_cmd = "%s > %s" % (cpu_cmd, cpufile)
        commands.getoutput(cpu_cmd)

    def get_state(cmd_timeout):
        kvm_exits = utils.system_output("cat /sys/kernel/debug/kvm/exits",
                                        cmd_timeout)
        return int(kvm_exits)

    def get_version(session, result_file, type, timeout):
        kvm_ver = utils.system_output("rpm -q qemu-kvm")
        host_ver = os.uname()[2]

        result_file.write("### kvm-userspace-ver : %s\n" % kvm_ver)
        result_file.write("### kvm_version : %s\n" % host_ver)

        result = session.cmd_output(params.get("guest_ver_cmd"), timeout)
        if type == "windows":
            if params.get(driver_format) == "ide":
                result_file.write("%s [Version ide driver format]\n"
                                  % params.get("guest_kernel_title"))
            else:
                guest_ver = re.findall(".*?(\d{2}\.\d{2}\.\d{3}\.\d{4}).*?",
                                       result)
                result_file.write("%s [Version %s]\n"
                                  % (params.get("guest_kernel_title"),
                                     guest_ver[0]))
        else:
            result_file.write("### guest-kernel-ver :%s" % result)

    # login virtual machine
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    session = vm.wait_for_login(timeout=login_timeout)

    # get parameter from dictionary
    fio_cmd = params.get("fio_cmd")
    cmd_timeout = int(params.get("cmd_timeout", 1200))
    driver_format = params.get("drive_format")
    guest_ver_cmd = params.get("guest_ver_cmd")
    os_type = params.get("os_type")

    #setup env for linux guest
    if os_type == "linux":
        error.context("Install fio tools in guest", logging.info)
        seup_env(session, vm)

    result_path = utils_misc.get_path(test.resultsdir,
                                      "fio_result.RHS")
    result_file = open(result_path, "w")

    # scratch host and windows guest version info
    get_version(session, result_file, os_type, cmd_timeout)

    # online disk
    if os_type == "windows":
        disks = check_status(session, cmd_timeout)
        diskstatus = re.findall("Disk\s+\d+\s+(\w+).*?\s+\d+", disks[0])[0]
        if diskstatus == "Offline":
            online_disk_cmd = params.get("online_disk_cmd")
            (s, o) = session.cmd_status_output(online_disk_cmd,
                                               timeout=cmd_timeout)
            if s != 0:
                raise error.TestFail("Failed to online disk: %s" % o)
        session.cmd(params.get("pre_cmd"), cmd_timeout)

    # format disk
    if params.get("format_disk") == "yes":
        error.context("Formatting %s disk" % os_type, logging.info)
        session.cmd(params.get("format_disk_cmd"), cmd_timeout)

    # get order_list
    order_line = ""
    for order in params.get("order_list").split():
            order_line += "%s|" % format_result(order)

    # get result tested by each seanario
    for i in params.get('rw').split():
        result_file.write("Category:%s\n" % i)
        result_file.write("%s\n" % order_line.rstrip("|"))
        if i == "rewrite":
            i = "write"
        for j in params.get("block_size").split():
            for k in params.get("iodepth").split():
                for l in params.get("threads").split():
                    line = ""
                    line += "%s|" % format_result(j[:-1])
                    line += "%s|" % format_result(k)
                    line += "%s|" % format_result(l)
                    if params.get("format_disk") == "yes":
                        m = "_".join([i, j, k])
                        run_cmd = fio_cmd % (i, j, k, m, l)
                    else:
                        run_cmd = fio_cmd % (i, j, k, l)

                    logging.info("run_cmd is: %s" % run_cmd)

                    start_state = get_state(cmd_timeout)
                    cpu_t = threading.Thread(target=cpu_thread,
                                             args=("mpstat 1 60", "/tmp/cpus"))
                    cpu_t.start()
                    s = session.cmd(run_cmd, cmd_timeout)
                    cpu_t.join()

                    end_state = get_state(cmd_timeout)
                    vm.copy_files_from(params.get("guest_result_file"),
                                       "/tmp/")

                    tmp_result = utils.system_output("egrep '(read|write)' " +
                                                     "/tmp/fio_result")
                    results = re.findall(params.get("io_pattern"), tmp_result)
                    tmp_result = utils.system_output("egrep 'lat' " +
                                                     "/tmp/fio_result")
                    logging.info("tmp result is: %s" % tmp_result)
                    laten = re.findall(params.get("laten_pattern"), tmp_result)
                    bw = float(utils_misc.normalize_data_size(results[0][0]))
                    iops = int(results[0][1])
                    if os_type == "linux":
                        tmp_result = utils.system_output("egrep 'util' " +
                                                         "/tmp/fio_result")
                        util = float(re.findall(".*?util=(\d+(?:[\.][\d]+))%",
                                     tmp_result)[0])

                    if laten[0][0] == "usec":
                        lat = float(laten[0][1]) / 1000
                    else:
                        lat = float(laten[0][1])
                    if re.findall("rw", i):
                        bw_wr = utils_misc.normalize_data_size(results[1][0])
                        bw = bw + float(bw_wr)
                        iops = iops + int(results[1][1])
                        if laten[1][0] == "usec":
                            lat = lat + float(laten[1][1]) / 1000
                        else:
                            lat = lat + float(laten[1][1])

                    ret = commands.getoutput("cat /tmp/cpus | tail -n 1")
                    cpu = 100 - float(ret.split()[-1])
                    normal = bw / cpu
                    io_exits = start_state - end_state
                    line += "%s|" % format_result(bw)
                    line += "%s|" % format_result(iops)
                    line += "%s|" % format_result(lat)
                    line += "%s|" % format_result(cpu)
                    line += "%s|" % format_result(normal)
                    line += "%s|" % format_result(io_exits)
                    if os_type == "linux":
                        line += "%s" % format_result(util)
                    result_file.write("%s\n" % line)

    result_file.close()

    if session:
        session.close()
