import logging
from autotest.client.shared import error
from virttest import utils_net, env_process


@error.context_aware
def run_invalid_para_mq(test, params, env):
    """
    Enable MULTI_QUEUE feature in guest

    1) Boot up VM with wrong queues number
    2) check the qemu can report the error.

    @param test: QEMU test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    params["start_vm"] = "yes"
    error.context("Boot the vm using queues %s'" % params.get("queues"), logging.info)
    try:
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        env.get_vm(params["main_vm"])
    except utils_net.TAPCreationError, e:
        logging.info("Error when open tap, error info is '%s'" % e)
    else:
        error.TestError("Params is wrong, the qemu should report that error")
