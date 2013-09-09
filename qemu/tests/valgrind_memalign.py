import logging
import time
from autotest.client.shared import error, utils
from virttest import env_process


@error.context_aware
def run_valgrind_memalign(test, params, env):
    """
    This case is from [general operation] Work around valgrind choking on our
    use of memalign():
    1.download valgrind form valgrind download page: www.valgrind.org.
    2.install the valgrind in host.
    3.run # valgrind /usr/libexec/qemu-kvm  -vnc :0 -S -m 384 -monitor stdio
    4.check the status and do continue the VM.
    5.quit the VM.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment
    """
    interval = float(params.get("interval_time", "10"))

    def valgrind_intall():
        valgrind_install_cmd = params.get("valgrind_install_cmd")
        s = utils.system(valgrind_install_cmd, timeout=3600)
        if s != 0:
            raise error.TestError("Fail to install valgrind")
        else:
            logging.info("Install valgrind successfully.")

    valgring_support_check_cmd = params.get("valgring_support_check_cmd")
    try:
        utils.system(valgring_support_check_cmd, timeout=interval)
    except Exception:
        valgrind_intall()

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])

    time.sleep(interval)
    vm.verify_status("running")
