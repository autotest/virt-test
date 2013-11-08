from autotest.client.shared import error
from virttest import utils_test


def run_libvirt_bench_domstate_switch_by_groups(test, params, env):
    """
    Test steps:

    1) Get the params from params.
    2) Devide vms into two groups and run sub test for each group.
    3) clean up.
    """
    # Get VMs.
    vms = env.get_all_vms()
    if len(vms) < 2:
        raise error.TestNAError("We need at least 2 vms for this test.")
    timeout = params.get("LB_domstate_switch_loop_time", 600)
    # Devide vms into two groups.
    odd_group_vms = []
    even_group_vms = []
    for index in range(len(vms)):
        if (index % 2):
            even_group_vms.append(vms[index])
        else:
            odd_group_vms.append(vms[index])

    # Run sub test for odd_group_vms.
    odd_env = env.copy()
    # Unregister vm which belong to even_group from odd_env.
    for vm in even_group_vms:
        odd_env.unregister_vm(vm.name)
    odd_bt = utils_test.BackgroundTest(utils_test.run_virt_sub_test,
                                       params=[test, params, odd_env,
                                               "libvirt_bench_domstate_switch_in_loop"])
    odd_bt.start()

    # Run sub test for even_group_vms.
    even_env = env.copy()
    # Unregister vm which belong to odd_group from even_env.
    for vm in odd_group_vms:
        even_env.unregister_vm(vm.name)
    even_bt = utils_test.BackgroundTest(utils_test.run_virt_sub_test,
                                        params=[test, params, even_env,
                                                "libvirt_bench_domstate_switch_in_loop"])
    even_bt.start()

    # Wait for background_tests joining.
    err_msg = ""
    try:
        odd_bt.join(int(timeout) * 2)
    except error.TestFail, detail:
        err_msg += ("Group odd_group failed to run sub test.\n"
                    "Detail: %s." % detail)
    try:
        even_bt.join(int(timeout) * 2)
    except error.TestFail, detail:
        err_msg += ("Group even_group failed to run sub test.\n"
                    "Detail: %s." % detail)
    if err_msg:
        raise error.TestFail(err_msg)
