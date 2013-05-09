import logging, os
from autotest.client.shared import error
from virttest import utils_test, remote, virt_vm, utils_misc


@error.context_aware
def run_migration_multi_host(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    @param test: kvm test object.
    @param params: Dictionary with test parameters.
    @param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    sub_test = params.get("sub_test")

    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = utils_test.MultihostMigration
    if mig_protocol == "fd":
        mig_type = utils_test.MultihostMigrationFd
    if mig_protocol == "exec":
        mig_type = utils_test.MultihostMigrationExec

    vms = params.get("vms").split(" ")
    srchost = params["hosts"][0]
    dsthost = params["hosts"][1]
    is_src = params["hostid"] == srchost

    mig = mig_type(test, params, env, False)
    mig.migrate_wait([vms[0]], srchost, dsthost)

    if not is_src:  #is destination
        if sub_test:
            error.context("Run sub test '%s' after checking"
                          " clock resolution" % sub_test, logging.info)
            utils_test.run_virt_sub_test(test, params, env, sub_test)