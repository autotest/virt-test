import logging
from autotest.client.shared import error, utils
from virttest import env_process, utils_misc, utils_test


@error.context_aware
def run_boot_cpu_model(test, params, env):
    """
    boot cpu model test:
    steps:
    1). boot guest with cpu model
    2). check flags if enable_check == "yes", otherwise shutdown guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters

    """
    host_flags = utils_misc.get_cpu_flags()
    cpu_vendor = utils_misc.get_cpu_vendor(host_flags)
    host_model = utils_misc.get_cpu_model()

    model_list = params.get("cpu_model")
    if not model_list:
        if cpu_vendor == "unknow":
            raise error.TestError("unknow cpu vendor")
        else:
            model_list = params.get("cpu_model_%s" % cpu_vendor,
                                    host_model.split(",")[-1])

    if model_list:
        model_list = model_list.split(" ")
        for model in model_list:
            if model in host_model or model == "host":
                params["cpu_model"] = model
                params["start_vm"] = "yes"
                env_process.preprocess_vm(test, params, env, params["main_vm"])
                # check guest flags
                if params.get("enable_check", "no") == "yes":
                    utils_test.run_virt_sub_test(test, params,
                                                 env, sub_type="flag_check")
                else:
                    # log in and shutdown guest
                    utils_test.run_virt_sub_test(test, params,
                                                 env, sub_type="shutdown")
                    logging.info("shutdown guest successfully")
            else:
                if params.get("enable_check", "no") == "yes":
                    raise error.TestWarn("Can not test %s model on %s host, pls"
                                         " use %s host" % (model, host_model.split(",")[0], model))
