import os, logging, time
from autotest.client.shared import error
from autotest.client import utils

def run_check_unhalt_vcpu(test, params, env):
    """
    Check unhalt vcpu of guest.
    1) Use qemu-img create any image which can not boot.
    2) Start vm with the image created by step 1
    3) Use ps get qemu-kvm process %cpu, if greater than 90%, report fial.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    pid = vm.get_pid()
    if not pid:
        raise error.TestError("Can't get pid of qemu")
    sleep_time = params.get("sleep_time", 60)
    time.sleep(sleep_time)
    get_usage_cmd = "top -b -n1 -p %s|tail -n2" % pid
    usage_cpu = utils.system_output(get_usage_cmd).split()[8]
    if float(usage_cpu) >= 90:
        raise error.TestFail("Guest have unhalt vcpu.")
    logging.info("Guest vcpu work normally")
