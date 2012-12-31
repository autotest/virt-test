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
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = utils_test.MultihostMigration
    if mig_protocol == "fd":
        base_class = utils_test.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = utils_test.MultihostMigrationExec

    class TestMultihostMigration(base_class):
        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.vms = params.get("vms").split()


        def migration_scenario(self, worker=None):
            error.context("Migration from %s to %s over protocol %s." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)
            self.migrate_wait(self.vms, self.srchost, self.dsthost,
                              start_work=worker)


    mig = TestMultihostMigration(test, params, env)
    mig.run()
