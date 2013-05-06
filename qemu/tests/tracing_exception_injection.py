import logging
from autotest.client import utils
from autotest.client.shared import error


@error.context_aware
def run_tracing_exception_injection(test, params, env):
    """
    Run tracing of exception injection test

    1) Boot the main vm, or just verify it if it's already booted.
    2) In host run kvm_stat, it works.
    3) In host check host allow tracing of exception injection in KVM.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    error.context("Get the main VM", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error.context("Check kvm_stat works in host", logging.info)
    check_cmd = "kvm_stat -1 -f exits"
    host_cmd_output = utils.system_output(check_cmd)
    if host_cmd_output:
        if host_cmd_output.split()[1] == '0':
            raise error.TestFail("Kvm stat not works in host")
        logging.info("kvm_stat works in host")
    logging.info("Host cmd output '%s'", host_cmd_output)

    error.context("Check host Allow tracing of exception injection in KVM",
                  logging.info)
    exec_cmd = "grep kvm:kvm_inj_exception "
    exec_cmd += " /sys/kernel/debug/tracing/available_events"
    inj_check_cmd = params.get("injection_check_cmd", exec_cmd)
    s = utils.system(inj_check_cmd)
    if s:
        err_msg = "kvm:kvm_inj_exception is not an avaliable events in host"
        raise error.TestFail(err_msg)
    logging.info("Host support tracing of exception injection in KVM")
