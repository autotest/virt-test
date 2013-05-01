import re, string, logging
from autotest.client.shared import error
from virttest import kvm_monitor, storage


def run_physical_resources_check(test, params, env):
    """
    Check physical resources assigned to KVM virtual machines:
    1) Log into the guest
    2) Verify whether cpu counts ,memory size, nics' model,
       count and drives' format & count, drive_serial, UUID
       reported by the guest OS matches what has been assigned
       to the VM (qemu command line)
    3) Verify all MAC addresses for guest NICs

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    # Define a function for checking number of hard drivers & NICs
    def check_num(devices, info_cmd, check_str):
        f_fail = []
        expected_num = params.objects(devices).__len__()
        o = ""
        try:
            o = vm.monitor.info(info_cmd)
        except kvm_monitor.MonitorError, e:
            fail_log =  e + "\n"
            fail_log += "info/query monitor command failed (%s)" % info_cmd
            f_fail.append(fail_log)
            logging.error(fail_log)

        actual_num = string.count(o, check_str)
        if expected_num != actual_num:
            fail_log =  "%s number mismatch:\n" % str(devices)
            fail_log += "    Assigned to VM: %d\n" % expected_num
            fail_log += "    Reported by OS: %d" % actual_num
            f_fail.append(fail_log)
            logging.error(fail_log)
        return expected_num, f_fail

    # Define a function for checking hard drives & NICs' model
    def chk_fmt_model(device, fmt_model, info_cmd, regexp):
        f_fail = []
        devices = params.objects(device)
        for chk_device in devices:
            expected = params.object_params(chk_device).get(fmt_model)
            if not expected:
                expected = "rtl8139"
            o = ""
            try:
                o = vm.monitor.info(info_cmd)
            except kvm_monitor.MonitorError, e:
                fail_log = e + "\n"
                fail_log += "info/query monitor command failed (%s)" % info_cmd
                f_fail.append(fail_log)
                logging.error(fail_log)

            device_found = re.findall(regexp, o)
            logging.debug("Found devices: %s", device_found)
            found = False
            for fm in device_found:
                if expected in fm:
                    found = True

            if not found:
                fail_log =  "%s model mismatch:\n" % str(device)
                fail_log += "    Assigned to VM: %s\n" % expected
                fail_log += "    Reported by OS: %s" % device_found
                f_fail.append(fail_log)
                logging.error(fail_log)
        return f_fail

    # Define a function to verify UUID & Serial number
    def verify_device(expect, name, verify_cmd):
        f_fail = []
        if verify_cmd:
            actual = session.cmd_output(verify_cmd)
            if not string.upper(expect) in actual:
                fail_log =  "%s mismatch:\n" % name
                fail_log += "    Assigned to VM: %s\n" % string.upper(expect)
                fail_log += "    Reported by OS: %s" % actual
                f_fail.append(fail_log)
                logging.error(fail_log)
        return f_fail


    def check_cpu_number(chk_type, expected_n, chk_timeout):
        """
        Checking cpu sockets/cores/threads number.

        @param chk_type: Should be one of 'sockets', 'cores', 'threads'.
        @param expected_n: Expected number of guest cpu number.
        @param chk_timeout: timeout of running chk_cmd.

        @return a list that contains fail report.
        """
        f_fail = []
        chk_str = params.get("mem_chk_re_str")
        chk_cmd = params.get("cpu_%s_chk_cmd" % chk_type)
        if chk_cmd is None:
            fail_log = "Unknown cpu number checking type: '%s'" % chk_type
            logging.error(fail_log)
            f_fail.append(fail_log)
            return f_fail

        if chk_cmd == "":
            return f_fail

        logging.info("CPU %s number check", string.capitalize(chk_type))
        s, output = session.cmd_status_output(chk_cmd, timeout=chk_timeout)
        num = re.findall(chk_str, output)
        if s != 0 or not num:
            fail_log = "Failed to get guest %s number, " % chk_type
            fail_log += "guest output: '%s'" % output
            f_fail.append(fail_log)
            logging.error(fail_log)
            return f_fail

        actual_n = int(num[0])
        if actual_n != expected_n:
            fail_log = "%s output mismatch:\n" % string.capitalize(chk_type)
            fail_log += "    Assigned to VM: '%s'\n" % expected_n
            fail_log += "    Reported by OS: '%s'" % actual_n
            f_fail.append(fail_log)
            logging.error(fail_log)
            return f_fail

        logging.debug("%s check pass. Expected: '%s', Actual: '%s'",
                      string.capitalize(chk_type), expected_n, actual_n)
        return f_fail


    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    chk_timeout = int(params.get("chk_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    logging.info("Starting physical resources check test")
    logging.info("Values assigned to VM are the values we expect "
                 "to see reported by the Operating System")
    # Define a failure counter, as we want to check all physical
    # resources to know which checks passed and which ones failed
    n_fail = []

    # We will check HDs with the image name
    image_name = storage.get_image_filename(params, test.bindir)

    # Check cpu count
    logging.info("CPU count check")
    actual_cpu_nr = vm.get_cpu_count()
    if vm.cpuinfo.smp != actual_cpu_nr:
        fail_log =  "CPU count mismatch:\n"
        fail_log += "    Assigned to VM: %s \n" % vm.cpuinfo.smp
        fail_log += "    Reported by OS: %s" % actual_cpu_nr
        n_fail.append(fail_log)
        logging.error(fail_log)

    n_fail.extend(check_cpu_number("cores", vm.cpuinfo.cores, chk_timeout))

    n_fail.extend(check_cpu_number("threads", vm.cpuinfo.threads, chk_timeout))

    n_fail.extend(check_cpu_number("sockets", vm.cpuinfo.sockets, chk_timeout))

    # Check the cpu vendor_id
    expected_vendor_id = params.get("cpu_model_vendor")
    cpu_vendor_id_chk_cmd = params.get("cpu_vendor_id_chk_cmd")
    if expected_vendor_id and cpu_vendor_id_chk_cmd:
        output = session.cmd_output(cpu_vendor_id_chk_cmd)

        if not expected_vendor_id in output:
            fail_log = "CPU vendor id check failed.\n"
            fail_log += "    Assigned to VM: '%s'\n" % expected_vendor_id
            fail_log += "    Reported by OS: '%s'" % output
            n_fail.append(fail_log)
            logging.error(fail_log)

    # Check memory size
    logging.info("Memory size check")
    expected_mem = int(params.get("mem"))
    actual_mem = vm.get_memory_size()
    if actual_mem != expected_mem:
        fail_log =  "Memory size mismatch:\n"
        fail_log += "    Assigned to VM: %s\n" % expected_mem
        fail_log += "    Reported by OS: %s\n" % actual_mem
        n_fail.append(fail_log)
        logging.error(fail_log)


    logging.info("Hard drive count check")
    _, f_fail = check_num("images", "block", image_name)
    n_fail.extend(f_fail)

    logging.info("NIC count check")
    _, f_fail = check_num("nics", "network", "model=")
    n_fail.extend(f_fail)

    logging.info("NICs model check")
    f_fail = chk_fmt_model("nics", "nic_model", "network", "model=(.*),")
    n_fail.extend(f_fail)

    logging.info("Drive format check")
    f_fail = chk_fmt_model("images", "drive_format",
                           "block", "(.*)\: .*%s" % image_name)
    n_fail.extend(f_fail)

    logging.info("Network card MAC check")
    o = ""
    try:
        o = vm.monitor.info("network")
    except kvm_monitor.MonitorError, e:
        fail_log =  e + "\n"
        fail_log += "info/query monitor command failed (network)"
        n_fail.append(fail_log)
        logging.error(fail_log)
    found_mac_addresses = re.findall("macaddr=(\S+)", o)
    logging.debug("Found MAC adresses: %s", found_mac_addresses)

    num_nics = len(params.objects("nics"))
    for nic_index in range(num_nics):
        mac = vm.get_mac_address(nic_index)
        if not string.lower(mac) in found_mac_addresses:
            fail_log =  "MAC address mismatch:\n"
            fail_log += "    Assigned to VM (not found): %s" % mac
            n_fail.append(fail_log)
            logging.error(fail_log)

    logging.info("UUID check")
    if vm.get_uuid():
        f_fail = verify_device(vm.get_uuid(), "UUID",
                               params.get("catch_uuid_cmd"))
        n_fail.extend(f_fail)

    logging.info("Hard Disk serial number check")
    catch_serial_cmd = params.get("catch_serial_cmd")
    f_fail = verify_device(params.get("drive_serial"), "Serial",
                           catch_serial_cmd)
    n_fail.extend(f_fail)

    # only check if the MS Windows VirtIO driver is digital signed.
    chk_cmd = params.get("vio_driver_chk_cmd")
    if chk_cmd:
        logging.info("Virtio Driver Check")
        chk_output = session.cmd_output(chk_cmd, timeout=chk_timeout)
        if "FALSE" in chk_output:
            fail_log = "VirtIO driver is not digitally signed!"
            fail_log += "    VirtIO driver check output: '%s'" % chk_output
            n_fail.append(fail_log)
            logging.error(fail_log)

    if n_fail:
        session.close()
        raise error.TestFail("Physical resources check test "
                             "reported %s failures:\n%s" %
                             (len(n_fail), "\n".join(n_fail)))

    session.close()
