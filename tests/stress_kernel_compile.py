import logging, os, math
from autotest.client.shared import error
from autotest.client import utils
from autotest.client.virt import utils_test, utils_misc, env_process


def run_stress_kernel_compile(tests, params, env):
    """
    Boot VMs and run kernel compile inside VM parallel.

    1) Boot up VMs:
       Every VM has 4G vmem, the total vmem of VMs' are
       $overcommit times as host's mem.
    2) Launch kernel compile inside every guest.

    @param test: KVM test object.
    @param params: Dictionary with the test parameters.
    @param env: Dictionary with test environment.
    """
    def kernelcompile(se, vmnum):
        vm_name = "vm" + str(vmnum)
        vm = env.get_vm(vm_name)
        ip = vm.get_address()
        path = params.get("test_src")
        logging.info("kernel path = %s" % path)
        get_kernel_cmd = "wget %s" % path
        try:
            s, o = se.cmd_status_output(get_kernel_cmd, timeout=240)
            if s != 0:
                logging.error(o)
                raise error.TestFail("Fail to download the kernel in vm%s" %vmnum)
            else:
                logging.info("Completed download the kernel src in vm%s" %vmnum)
            test_cmd = params.get("test_cmd")
            s, o = se.cmd_status_output(test_cmd, timeout=1200)
            if s != 0:
                logging.error(o)
        finally:
            s, o = utils_test.ping(ip, count=10, timeout=30)
            if s != 0:
                logging.error("vm no response, pls check serial log")

    vmem = 4096
    params["mem"] = vmem

    check_host_mem = params.get("query_cmd")
    over_c = float(params.get("overcommit"))
    mem_host = int(utils.system_output(check_host_mem))/1024
    num_vm = int(math.ceil(mem_host * over_c / vmem))

    login_timeout = int(params.get("login_timeout", 360))
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(tests, params, env, vm_name)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    if not session:
        raise error.TestFail("Could not log into first guest")

    num = 2
    sessions = [session]

    # boot the VMs
    while num <= (num_vm):
        # clone vm according to the first one
        vm_name = "vm" + str(num)
        vm_params = vm.get_params().copy()
        curr_vm = vm.clone(vm_name, vm_params)
        env.register_vm(vm_name, curr_vm)
        logging.info("Booting guest #%d" % num)
        env_process.preprocess_vm(tests, vm_params, env, vm_name)
        params['vms'] += " " + vm_name

        curr_vm_session = curr_vm.wait_for_login(timeout=login_timeout)

        if not curr_vm_session:
            raise error.TestFail("Could not log into guest #%d" % num)

        logging.info("Guest #%d boots up successfully" % num)
        sessions.append(curr_vm_session)
        num += 1

    # run kernel compile in vms
    try:
        logging.info("run kernel compile in vms")
        bg = []
        for num, session in enumerate(sessions):
            bg.append(utils_test.BackgroundTest(kernelcompile, (session,num+1)))
            bg[num].start()

        completed = False
        while not completed:
            completed = True
            for b in bg:
                if b.is_alive():
                    completed = False
    finally:
        try:
            for b in bg:
                if b:
                    b.join()
        finally:
            for se in sessions:
                se.close()
