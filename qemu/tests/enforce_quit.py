import logging
import re
from autotest.client.shared import error
from virttest import env_process, utils_misc


@error.context_aware
def run(test, params, env):
    """
    enforce quit test:
    steps:
    1). boot guest with enforce params
    2). guest will quit if flags is not supported in host

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    guest_cpumodel = params.get("cpu_model", "Conroe").split(",")[0]
    host_cpumodel = utils_misc.get_host_cpu_models()
    host_flags = utils_misc.get_cpu_flags()
    extra_flags = params.get("cpu_model_flags", " ")

    lack_flags = []
    flags = re.findall("\+(\w+)", extra_flags)
    for flag in flags:
        if flag not in host_flags:
            lack_flags.append(flag)
    force_quit = False
    # force quit if flag is not no host
    if lack_flags:
        force_quit = True
    # force quit if 'svm' is added
    if "svm" in extra_flags:
        force_quit = True
    # force quit if guest cpu is not included in host cpu cluster
    if guest_cpumodel not in host_cpumodel and guest_cpumodel != "host":
        force_quit = True

    if "enforce" not in extra_flags:
        raise error.TestError("pls add 'enforce' params to the cmd line")

    msg_unavailable = params.get("msg_unavailable", "").split(":")
    msg_unknow = params.get("msg_unknow", "not found")
    try:
        error.context("boot guest with -cpu %s,%s" % (guest_cpumodel,
                                                      extra_flags),
                                                      logging.info)
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    except Exception, err:
        tmp_flag = False
        for msg in msg_unavailable:
            if msg in str(err):
                tmp_flag = True
        if tmp_flag or msg_unknow in str(err):
            logging.info("unavailable host feature, guest force quit")
        else:
            raise error.TestFail("guest quit with error\n%s" % str(err))

    vm = env.get_vm(params["main_vm"])
    if force_quit:
        if not vm.is_dead():
            raise error.TestFail("guest didn't enforce quit"
                                 " while flag lacked in host")
