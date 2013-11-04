import logging
import os
from autotest.client.shared import error
from virttest import utils_test, remote, virt_vm, utils_misc


@error.context_aware
def run_migration_multi_host(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.
    steps:
        1) try log to VM if login_before_pre_tests == yes
        2) before migration start pre_sub_test
        3) migration
        4) after migration start post_sub_test

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    pre_sub_test = params.get("pre_sub_test")
    post_sub_test = params.get("post_sub_test")
    pre_sub_test_timeout = int(params.get("pre_sub_test_timeout", "240"))
    login_before_pre_tests = params.get("login_before_pre_tests", "no")

    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = utils_test.qemu.MultihostMigration
    if mig_protocol == "fd":
        mig_type = utils_test.qemu.MultihostMigrationFd
    if mig_protocol == "exec":
        mig_type = utils_test.qemu.MultihostMigrationExec

    vms = params.get("vms").split(" ")
    srchost = params["hosts"][0]
    dsthost = params["hosts"][1]
    is_src = params["hostid"] == srchost

    if is_src:  # is destination
        if pre_sub_test:
            if login_before_pre_tests == "yes":
                vm = env.get_vm(vms[0])
                vm.wait_for_login(timeout=login_timeout)
            error.context("Run sub test '%s' before migration on src"
                          % pre_sub_test, logging.info)
            utils_test.run_virt_sub_test(test, params, env, pre_sub_test)

    mig = mig_type(test, params, env, False)
    mig._hosts_barrier([srchost, dsthost],
                       {'src': srchost, 'dst': dsthost, "vms": vms[0]},
                       "sync", pre_sub_test_timeout)
    mig.migrate_wait([vms[0]], srchost, dsthost)

    if not is_src:  # is destination
        if post_sub_test:
            error.context("Run sub test '%s' after migration on dst"
                          % post_sub_test, logging.info)
            utils_test.run_virt_sub_test(test, params, env, post_sub_test)
