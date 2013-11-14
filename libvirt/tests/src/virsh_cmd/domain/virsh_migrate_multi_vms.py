import re
import os
import logging
import commands
import shutil
import threading
import time
from autotest.client.shared import utils, error
from virttest import libvirt_vm, virsh


# To get result in thread, using global parameters
# Result of virsh migrate command
global ret_migration
# Result of virsh domjobabort
global ret_jobabort
# True means command executed successfully
ret_migration = True
ret_jobabort = True


def make_migration_options(optionstr="", timeout=60):
    """
    Analyse a string to options for migration.
    They are split by one space.

    :param optionstr: a string contain all options and split by space
    :param timeout: timeout for migration.
    """
    options = ""
    for option in optionstr.split():
        if option == "live":
            options += " --live"
        elif option == "persistent":
            options += " --persistent"
        elif option == "suspend":
            options += " --suspend"
        elif option == "change-protection":
            options += " --change-protection"
        elif option == "timeout":
            options += " --timeout %s" % timeout
        else:
            logging.debug("Do not support option '%s' yet." % option)
    return options


def make_migration_cmd(vm_name, method, desturi, options=""):
    migrate_exec = "migrate %s" % vm_name

    if method == "p2p":
        migrate_exec += " --p2p"
    elif method == "p2p_tunnelled":
        migrate_exec += " --p2p --tunnelled"
    elif method == "direct":
        migrate_exec += " --direct"
    else:
        # Default method or unknown method
        pass

    if desturi is not None:
        migrate_exec += " --desturi %s" % desturi
    return migrate_exec + options


class MigrationHelper(object):

    """A class to help migration."""

    def __init__(self, vm_name, test, params, env):
        self.vm_name = vm_name
        self.vm = libvirt_vm.VM(vm_name, params, test.bindir,
                                env.get("address_cache"))
        self.virsh_instance = None
        self.migration_cmd = None

    def __str__(self):
        return "Migration VM %s, Command '%s'" % (self.vm_name,
                                                  self.migration_cmd)

    def set_virsh_instance(self):
        """
        Create a virsh instance for migration.
        TODO: support remote instance VirshConnectBack
        """
        # rs_dargs = {'remote_ip': remote_host, 'remote_user': host_user,
        #            'remote_pwd': host_passwd, 'uri': srcuri}
        #rvirsh = virsh.VirshConnectBack(**rs_dargs)
        self.virsh_instance = virsh.VirshPersistent()

    def set_migration_cmd(self, options, method, desturi, timeout=60):
        """
        Set command for migration.
        """
        self.migration_cmd = make_migration_cmd(
            self.vm_name, method, desturi,
            make_migration_options(options, timeout))

    def cleanup_vm(self, srcuri, desturi):
        """
        Cleanup migrated vm on remote host.
        """
        self.vm.connect_uri = desturi
        if self.vm.exists():
            if self.vm.is_persistent():
                self.vm.undefine()
            if self.vm.is_alive():
                self.vm.destroy()
        # Set connect uri back to local uri
        self.vm.connect_uri = srcuri


def thread_func_migration(virsh_instance, cmd):
    """
    Thread for virsh migrate command.

    :param virsh_instance: A VirshPersistent or VirshConnectBack instance.
    :param cmd: command to be executed in session
    """
    # Judge result for main_func with a global variable.
    global ret_migration
    # Migrate the domain.
    try:
        result = virsh_instance.command(cmd, ignore_status=False)
    except error.CmdError, detail:
        logging.error("Migration with %s failed:\n%s" % (cmd, detail))
        ret_migration = False


def thread_func_jobabort(vm):
    global ret_jobabort
    if not vm.domjobabort():
        ret_jobabort = False


def multi_migration(helpers, simultaneous=False, jobabort=False, timeout=60):
    """
    Migrate multiple vms simultaneously or not.
    If jobabort is True, run "virsh domjobabort vm_name" during migration.

    :param helper: A MigrationHelper class instance
    :param timeout: thread's timeout
    """
    migration_threads = []
    for helper in helpers:
        inst = helper.virsh_instance
        cmd = helper.migration_cmd
        migration_threads.append(threading.Thread(
                                 target=thread_func_migration,
                                 args=(inst, cmd)))

    if simultaneous:
        logging.info("Migrate vms simultaneously.")
        for migration_thread in migration_threads:
            migration_thread.start()
        if jobabort:
            # Confirm Migration has been executed.
            time.sleep(1)
            logging.info("Aborting job during migration.")
            jobabort_threads = []
            for helper in helpers:
                jobabort_thread = threading.Thread(target=thread_func_jobabort,
                                                   args=(helper.vm,))
                jobabort_threads.append(jobabort_thread)
                jobabort_thread.start()
            for jobabort_thread in jobabort_threads:
                jobabort_thread.join(timeout)
        for migration_thread in migration_threads:
            migration_thread.join(timeout)
            if migration_thread.isAlive():
                logging.error("Migrate %s timeout.", migration_thread)
                ret_migration = False
    else:
        logging.info("Migrate vms orderly.")
        for helper in helpers:
            inst = helper.virsh_instance
            cmd = helper.migration_cmd
            migration_thread = threading.Thread(target=thread_func_migration,
                                                args=(inst, cmd))
            migration_thread.start()
            migration_thread.join(timeout)
            if migration_thread.isAlive():
                logging.error("Migrate %s timeout.", migration_thread)
                ret_migration = False


def run(test, params, env):
    """
    Test migration of multi vms.
    """
    vm_names = params.get("vms").split()
    if len(vm_names) < 2:
        raise error.TestNAError("No multi vms provided.")

    # Prepare parameters
    method = params.get("virsh_migrate_method")
    simultaneous = "yes" == params.get("simultaneous_migration", "no")
    jobabort = "yes" == params.get("virsh_migrate_jobabort", "no")
    options = params.get("virsh_migrate_options", "")
    status_error = "yes" == params.get("status_error", "no")
    #remote_migration = "yes" == params.get("remote_migration", "no")
    remote_host = params.get("remote_host", "DEST_HOSTNAME.EXAMPLE.COM")
    local_host = params.get("local_host", "SOURCE_HOSTNAME.EXAMPLE.COM")
    host_user = params.get("host_user", "root")
    host_passwd = params.get("host_password", "PASSWORD")
    desturi = libvirt_vm.get_uri_with_transport(transport="ssh",
                                                dest_ip=remote_host)
    srcuri = libvirt_vm.get_uri_with_transport(transport="ssh",
                                               dest_ip=local_host)

    # Don't allow the defaults.
    if srcuri.count('///') or srcuri.count('EXAMPLE'):
        raise error.TestNAError("The srcuri '%s' is invalid", srcuri)
    if desturi.count('///') or desturi.count('EXAMPLE'):
        raise error.TestNAError("The desturi '%s' is invalid", desturi)

    # Prepare MigrationHelper instance
    helpers = []
    for vm_name in vm_names:
        helper = MigrationHelper(vm_name, test, params, env)
        helper.set_virsh_instance()
        helper.set_migration_cmd(options, method, desturi)
        helpers.append(helper)

    for helper in helpers:
        vm = helper.vm
        if vm.is_dead():
            vm.start()
        vm.wait_for_login()

    try:
        multi_migration(helpers, simultaneous=False, jobabort=False)
    finally:
        for helper in helpers:
            helper.virsh_instance.close_session()
            helper.cleanup_vm(srcuri, desturi)

        if not ret_migration:
            if not status_error:
                raise error.TestFail("Migration test failed.")
        if not ret_jobabort:
            if not status_error:
                raise error.TestFail("Abort migration failed.")
