import os
import re
import commands
import glob
import shutil
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_test, utils_misc, data_dir


def run_performance(test, params, env):
    """
    KVM performance test:

    The idea is similar to 'client/tests/kvm/tests/autotest.py',
    but we can implement some special requests for performance
    testing.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    test_timeout = int(params.get("test_timeout", 240))
    monitor_cmd = params["monitor_cmd"]
    login_timeout = int(params.get("login_timeout", 360))
    test_cmd = params["test_cmd"]
    guest_path = params.get("result_path", "/tmp/guest_result")
    test_src = params["test_src"]
    test_patch = params.get("test_patch")

    # Prepare test environment in guest
    session = vm.wait_for_login(timeout=login_timeout)

    prefix = test.outputdir.split(".performance.")[0]
    summary_results = params.get("summary_results")
    guest_ver = session.cmd_output("uname -r").strip()

    if summary_results:
        result_dir = params.get("result_dir", os.path.dirname(test.outputdir))
        result_sum(result_dir, params, guest_ver, test.resultsdir, test)
        session.close()
        return

    guest_launcher = os.path.join(test.virtdir, "scripts/cmd_runner.py")
    vm.copy_files_to(guest_launcher, "/tmp")
    md5value = params.get("md5value")

    tarball = utils.unmap_url_cache(test.tmpdir, test_src, md5value)
    test_src = re.split("/", test_src)[-1]
    vm.copy_files_to(tarball, "/tmp")

    session.cmd("rm -rf /tmp/src*")
    session.cmd("mkdir -p /tmp/src_tmp")
    session.cmd("tar -xf /tmp/%s -C %s" % (test_src, "/tmp/src_tmp"))

    # Find the newest file in src tmp directory
    cmd = "ls -rt /tmp/src_tmp"
    s, o = session.cmd_status_output(cmd)
    if len(o) > 0:
        new_file = re.findall("(.*)\n", o)[-1]
    else:
        raise error.TestError("Can not decompress test file in guest")
    session.cmd("mv /tmp/src_tmp/%s /tmp/src" % new_file)

    if test_patch:
        test_patch_path = os.path.join(data_dir.get_root_dir(), 'shared',
                                       'deps', 'performance', test_patch)
        vm.copy_files_to(test_patch_path, "/tmp/src")
        session.cmd("cd /tmp/src && patch -p1 < /tmp/src/%s" % test_patch)

    compile_cmd = params.get("compile_cmd")
    if compile_cmd:
        session.cmd("cd /tmp/src && %s" % compile_cmd)

    prepare_cmd = params.get("prepare_cmd")
    if prepare_cmd:
        s, o = session.cmd_status_output(prepare_cmd, test_timeout)
        if s != 0:
            raise error.TestError("Fail to prepare test env in guest")

    cmd = "cd /tmp/src && python /tmp/cmd_runner.py \"%s &> " % monitor_cmd
    cmd += "/tmp/guest_result_monitor\"  \"/tmp/src/%s" % test_cmd
    cmd += " &> %s \" \"/tmp/guest_result\""
    cmd += " %s" % int(test_timeout)

    test_cmd = cmd
    # Run guest test with monitor
    tag = utils_test.cmd_runner_monitor(vm, monitor_cmd, test_cmd,
                                        guest_path, timeout=test_timeout)

    # Result collecting
    result_list = ["/tmp/guest_result_%s" % tag,
                   "/tmp/host_monitor_result_%s" % tag,
                   "/tmp/guest_monitor_result_%s" % tag]
    guest_results_dir = os.path.join(test.outputdir, "guest_results")
    if not os.path.exists(guest_results_dir):
        os.mkdir(guest_results_dir)
    ignore_pattern = params.get("ignore_pattern")
    head_pattern = params.get("head_pattern")
    row_pattern = params.get("row_pattern")
    for i in result_list:
        if re.findall("monitor_result", i):
            result = utils_test.summary_up_result(i, ignore_pattern,
                                                  head_pattern, row_pattern)
            fd = open("%s.sum" % i, "w")
            sum_info = {}
            head_line = ""
            for keys in result:
                head_line += "\t%s" % keys
                for col in result[keys]:
                    col_sum = "line %s" % col
                    if col_sum in sum_info:
                        sum_info[col_sum] += "\t%s" % result[keys][col]
                    else:
                        sum_info[col_sum] = "%s\t%s" % (col, result[keys][col])
            fd.write("%s\n" % head_line)
            for keys in sum_info:
                fd.write("%s\n" % sum_info[keys])
            fd.close()
            shutil.copy("%s.sum" % i, guest_results_dir)
        shutil.copy(i, guest_results_dir)

    session.cmd("rm -rf /tmp/src")
    session.cmd("rm -rf guest_test*")
    session.cmd("rm -rf pid_file*")
    session.close()


def mpstat_ana(filename):
    """
    Get the cpu usage from the mpstat summary file

    @param filename: filename of the mpstat summary file
    """
    mpstat_result = open(filename, 'r')
    key_value = "%idle"
    index = 0
    result = {}
    for line in mpstat_result.readlines():
        if key_value in line:
            index = line.split().index(key_value) + 1
        else:
            data = line.split()
            if data[0] == "all":
                vcpu = "all"
            else:
                vcpu = "vcpu%s" % data[0]
            cpu_use = "%20.2f" % (100 - utils_test.aton(data[index]))
            result[vcpu] = cpu_use
    return result


def time_ana(results_tuple):
    """
    Get the time from the results when run test with time

    @param results_tuple: the tuple get from results file
    """
    time_unit = 1.0
    time_data = 0.0
    l = len(results_tuple)
    while l > 0:
        l -= 1
        if results_tuple[l]:
            time_data += float(results_tuple[l]) * time_unit
            time_unit *= 60
    return str(time_data)


def format_result(result, base="20", fbase="2"):
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


def get_sum_result(sum_matrix, value, tag):
    """
    Calculate the summary result

    @param sum_matrix: matrix to store the summary results
    @param value: value to add to matrix
    @param tag: the keyword for the value in matrix
    """
    if tag in sum_matrix.keys():
        sum_matrix[tag] += value
    else:
        sum_matrix[tag] = value
    return sum_matrix


def result_sum(topdir, params, guest_ver, resultsdir, test):
    case_type = params.get("test")
    unit_std = params.get("unit_std", "M")
    no_table_list = params.get("no_table_list", "").split()
    ignore_cases = params.get("ignore_cases", "").split()
    repeatn = ""
    if "repeat" in test.outputdir:
        repeatn = re.findall("repeat\d+", test.outputdir)[0]
    category_key = re.split("/", test.outputdir)[-1]
    category_key = re.split(case_type, category_key)[0]
    category_key = re.sub("\.repeat\d+", "", category_key)

    kvm_ver = utils.system_output(params.get('ver_cmd', "rpm -q qemu-kvm"))
    host_ver = os.uname()[2]
    test.write_test_keyval({'kvm-userspace-ver': kvm_ver})
    test.write_test_keyval({'host-kernel-ver': host_ver})
    test.write_test_keyval({'guest-kernel-ver': guest_ver})
    # Find the results files

    results_files = {}
    file_list = ['guest_result', 'guest_monitor_result.*sum',
                 'host_monitor_result.*sum']
    if params.get("file_list"):
        file_list = params.get("file_list").split()

    for files in os.walk(topdir):
        if files[2]:
            for file in files[2]:
                jump_flag = False
                for ignore_case in ignore_cases:
                    if ignore_case in files[0]:
                        jump_flag = True
                if jump_flag:
                    continue
                file_dir_norpt = re.sub("\.repeat\d+", "", files[0])
                if (repeatn in files[0]
                    and category_key in file_dir_norpt
                        and case_type in files[0]):
                    for i, pattern in enumerate(file_list):
                        if re.findall(pattern, file):
                            prefix = re.findall("%s\.[\d\w_\.]+" % case_type,
                                                file_dir_norpt)[0]
                            prefix = re.sub("\.|_", "--", prefix)
                            if prefix not in results_files.keys():
                                results_files[prefix] = []
                                tmp = []
                                for j in range(len(file_list)):
                                    tmp.append(None)
                                results_files[prefix] = tmp
                            tmp_file = utils_misc.get_path(files[0], file)
                            results_files[prefix][i] = tmp_file

    # Start to read results from results file and monitor file
    results_matrix = {}
    no_table_results = {}
    thread_tag = params.get("thread_tag", "thread")
    order_list = []
    for prefix in results_files:
        marks = params.get("marks", "").split()
        case_infos = prefix.split("--")
        case_type = case_infos[0]
        threads = ""
        refresh_order_list = True
        prefix_perf = prefix
        if case_type == "ffsb":
            category = "-".join(case_infos[:-1])
            threads = case_infos[-1]
        elif case_type == "qcow2perf":
            refresh_order_list = False
            if len(case_infos) > 2:
                category = "-".join(case_infos[:-2])
                thread_tag = case_infos[-2]
                threads = " "
                marks[0] = re.sub("TIME", case_infos[-1], marks[0])
            else:
                category = case_infos[-1]
                marks[0] = re.sub("TIME", case_infos[-1], marks[0])
            prefix_perf = "--".join(case_infos[:-1])
        else:
            category = "-".join(case_infos)
        if refresh_order_list:
            order_list = []
        if (category not in results_matrix.keys()
                and category not in no_table_list):
            results_matrix[category] = {}
        if threads:
            if threads not in results_matrix[category].keys():
                results_matrix[category][threads] = {}
                results_matrix["thread_tag"] = thread_tag
            tmp_dic = results_matrix[category][threads]
        elif category not in no_table_list:
            tmp_dic = results_matrix[category]

        result_context_file = open(results_files[prefix][0], 'r')
        result_context = result_context_file.read()
        result_context_file.close()
        for mark in marks:
            mark_tag, mark_key = mark.split(":")
            datas = re.findall(mark_key, result_context)
            if isinstance(datas[0], tuple):
                data = time_ana(datas[0])
            else:
                tmp_data = 0.0
                for data in datas:
                    if re.findall("[bmkg]", data, re.I):
                        data = utils_misc.normalize_data_size(data, unit_std)
                    tmp_data += float(data)
                data = str(tmp_data)
            if data:
                if mark_tag in no_table_list:
                    no_table_results[mark_tag] = utils_test.aton(data)
                    perf_value = no_table_results[mark_tag]
                else:
                    tmp_dic[mark_tag] = utils_test.aton(data)
                    perf_value = tmp_dic[mark_tag]
            else:
                raise error.TestError("Can not get the right data from result."
                                      "Please check the debug file.")
            if mark_tag not in no_table_list and mark_tag not in order_list:
                order_list.append(mark_tag)
            test.write_perf_keyval({'%s-%s' % (prefix_perf, mark_tag):
                                    perf_value})
        # start analyze the mpstat results
        if params.get('mpstat') == "yes":
            guest_cpu_infos = mpstat_ana(results_files[prefix][1])
            for vcpu in guest_cpu_infos:
                if vcpu != "all":
                    tmp_dic[vcpu] = float(guest_cpu_infos[vcpu])
                    order_list.append(vcpu)
            host_cpu_infos = mpstat_ana(results_files[prefix][2])
            tmp_dic["Hostcpu"] = float(host_cpu_infos["all"])
            order_list.append("Hostcpu")
        # Add some special key for cases
        if case_type == "ffsb":
            tmp_dic["MBps_per_Hostcpu"] = (tmp_dic["Thro-MBps"] /
                                           tmp_dic["Hostcpu"])
            order_list.append("MBps_per_Hostcpu")
        elif case_type == "iozone":
            sum_kbps = 0
            for mark in marks:
                mark_tag, _ = mark.split(":")
                sum_kbps += tmp_dic[mark_tag]
            tmp_dic["SUMKbps_per_Hostcpu"] = sum_kbps / tmp_dic["Hostcpu"]
            order_list.append("SUMKbps_per_Hostcpu")

    sum_marks = params.get("sum_marks", "").split()
    sum_matrix = {}
    order_line = ""
    if results_matrix.get("thread_tag"):
        headline = "%20s|" % results_matrix["thread_tag"]
        results_matrix.pop("thread_tag")
    else:
        headline = ""
    for index, tag in enumerate(order_list):
        headline += "%s|" % format_result(tag)
        order_line += "DATA%d|" % index
    headline = headline.rstrip("|")
    order_line = order_line.rstrip("|")

    result_path = utils_misc.get_path(resultsdir,
                                      "%s-result.RHS" % case_type)
    if os.path.isfile(result_path):
        result_file = open(result_path, "r+")
    else:
        result_file = open(result_path, "w")
        result_file.write("### kvm-userspace-version : %s\n" % kvm_ver)
        result_file.write("### kvm-version : %s\n" % host_ver)
        result_file.write("### guest-kernel-version :%s\n" % guest_ver)

    test.write_test_keyval({'category': headline})
    result_file.write("Category:ALL\n")
    matrix_order = params.get("matrix_order", "").split()
    if not matrix_order:
        matrix_order = results_matrix.keys()
        matrix_order.sort()
    for category in matrix_order:
        out_loop_line = order_line
        result_file.write("%s\n" % category)
        line = ""
        write_out_loop = True
        result_file.write("%s\n" % headline)
        for item in results_matrix[category]:
            if isinstance(results_matrix[category][item], dict):
                tmp_dic = results_matrix[category][item]
                line = "%s|" % format_result(item)
                for tag in order_list:
                    line += "%s|" % format_result(tmp_dic[tag])
                    if tag in sum_marks:
                        sum_matrix = get_sum_result(sum_matrix, tmp_dic[tag],
                                                    tag)
                result_file.write("%s\n" % line.rstrip("|"))
                write_out_loop = False
            else:
                #line += "%s|" % format_result(results_matrix[category][item])
                re_data = "DATA%s" % order_list.index(item)
                out_loop_line = re.sub(re_data,
                                       format_result(
                                           results_matrix[category][item]),
                                       out_loop_line)
                if tag in sum_marks:
                    sum_matrix = get_sum_result(sum_matrix, tmp_dic[tag],
                                                tag)
        if write_out_loop:
            result_file.write("%s\n" % out_loop_line)

    if sum_matrix:
        if case_type == "ffsb":
            sum_matrix["MBps_per_Hostcpu"] = (sum_matrix["Thro-MBps"] /
                                              sum_matrix["Hostcpu"])
            sum_marks.append("MBps_per_Hostcpu")
        result_file.write("Category:SUM\n")
        headline = ""
        line = ""
        if len(sum_matrix) < 4:
            for i in range(4 - len(sum_matrix)):
                headline += "%20s|" % "None"
                line += "%20d|" % 0
        for tag in sum_marks:
            headline += "%20s|" % tag
            line += "%s|" % format_result(sum_matrix[tag])

        result_file.write("%s\n" % headline.rstrip("|"))
        result_file.write("%s\n" % line.rstrip("|"))

    if no_table_results:
        no_table_order = params.get("no_table_order", "").split()
        if not no_table_order:
            no_table_order = no_table_results.keys()
            no_table_order.sort()
        for item in no_table_order:
            result_file.write("%s: %s\n" % (item, no_table_results[item]))

    result_file.close()
