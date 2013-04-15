import logging, os, re
from autotest.client.shared import error
from virttest import env_process, aexpect

def get_re_average(opt,re_str):
    """
    Get the average value which match re string.

    @param opt: string that contains all the information.
    @param re_str: re string used to filter the result.
    """

    values = re.findall(re_str, str(opt))
    vals = 0.0
    for val in values:
        val = float(val)
        vals += val
    return vals/len(values)


def run_ipi_x2apic(test, params, env):
    """
    Measure overhead of IPI with and without x2apic:
    1) Enable ept if the host support it.
    2) Boot guest with x2apic cpu flag (at least 2 vcpu).
    3) Check x2apic flag in guest.
    4) Run pipetest script in guest.
    5) Boot guest without x2apic.
    6) Run pipetest script in guest.
    7) Compare the result of step4 and step6.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    smp = params.get("smp")
    if int(smp) < 2:
        params["smp"] = 2
        logging.warn("This case need at least 2 vcpu, but only 1 specified in"
                     " configuration. So change the vcpu to 2.")
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cmd_timeout = int(params.get("cmd_timeout", 360))

    if params.get("check_x2apic_cmd"):
        check_x2apic_cmd = params.get("check_x2apic_cmd")
        x2apic_output = session.cmd_output(check_x2apic_cmd).strip()
        x2apic_check_string = params.get("x2apic_check_string").split(",")
        for str in x2apic_check_string:
            if str.strip() not in x2apic_output:
                raise error.TestFail("%s is not displayed in output" % str)

    file_link = os.path.join(test.virtdir, "scripts/pipetest.c")
    vm.copy_files_to(file_link, "/tmp/pipetest.c")
    run_pipetest_cmd = params.get("run_pipetest_cmd")
    try:
        (s, o) = session.cmd_status_output(run_pipetest_cmd, timeout=180)
    except aexpect.ShellTimeoutError, e:
        o = e
    re_str = "[0-9]*\.[0-9]+"
    val1 = get_re_average(o,re_str)
    session.close()
    vm.destroy()
    params["enable_x2apic"] = "no"
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    try:
        (s, o) = session.cmd_status_output(run_pipetest_cmd, timeout=180)
    except aexpect.ShellTimeoutError, e:
        o = e
    val2 = get_re_average(o,re_str)
    if val1 >= val2:
        raise error.TestFail("Overhead of IPI with x2apic is not smaller than"
                             "that without x2apic.\n with x2apic:%s"
                             "without x2apic:%s" % (val1, val2))
    session.close()
