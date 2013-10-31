"""
High-level KVM test utility functions.

This module is meant to reduce code size by performing common test procedures.
Generally, code here should look like test code.
More specifically:
    - Functions in this module should raise exceptions if things go wrong
      (unlike functions in kvm_utils.py and qemu_vm.py which report failure via
      their returned values).
    - Functions in this module may use logging.info(), in addition to
      logging.debug() and logging.error(), to log messages the user may be
      interested in (unlike kvm_utils.py and qemu_vm.py which use
      logging.debug() for anything that isn't an error).
    - Functions in this module typically use functions and classes from
      lower-level modules (e.g. kvm_utils.py, qemu_vm.py, kvm_subprocess.py).
    - Functions in this module should not be used by lower-level modules.
    - Functions in this module should be used in the right context.
      For example, a function should not be used where it may display
      misleading or inaccurate info or debug messages.

:copyright: 2008-2009 Red Hat Inc.
"""

import time
import os
import logging
import re
import signal
import imp
import tempfile
import commands
import errno
import fcntl
import threading
import shelve
import socket
import glob
import locale
from Queue import Queue
from autotest.client.shared import error
from autotest.client import utils, os_dep
from autotest.client.tools import scan_results
from autotest.client.shared.syncdata import SyncData, SyncListenServer
import aexpect
import utils_misc
import virt_vm
import remote
import storage
import env_process
import virttest

try:
    from virttest.staging import utils_cgroup
except ImportError:
    # TODO: Obsoleted path used prior autotest-0.15.2/virttest-2013.06.24
    from autotest.client.shared import utils_cgroup

try:
    from virttest.staging import utils_memory
except ImportError:
    from autotest.client.shared import utils_memory

# Handle transition from autotest global_config (0.14.x series) to
# settings (0.15.x onwards)
try:
    from autotest.client.shared import global_config
    section_values = global_config.global_config.get_section_values
    settings_value = global_config.global_config.get_config_value
except ImportError:
    from autotest.client.shared.settings import settings
    section_values = settings.get_section_values
    settings_value = settings.get_value


def get_living_vm(env, vm_name):
    """
    Get a VM object from the environment and make sure it's alive.

    :param env: Dictionary with test environment.
    :param vm_name: Name of the desired VM object.
    :return: A VM object.
    """
    vm = env.get_vm(vm_name)
    if not vm:
        raise error.TestError("VM '%s' not found in environment" % vm_name)
    if not vm.is_alive():
        raise error.TestError("VM '%s' seems to be dead; test requires a "
                              "living VM" % vm_name)
    return vm


def wait_for_login(vm, nic_index=0, timeout=240, start=0, step=2, serial=None):
    """
    Try logging into a VM repeatedly.  Stop on success or when timeout expires.

    :param vm: VM object.
    :param nic_index: Index of NIC to access in the VM.
    :param timeout: Time to wait before giving up.
    :param serial: Whether to use a serial connection instead of a remote
            (ssh, rss) one.
    :return: A shell session object.
    """
    end_time = time.time() + timeout
    session = None
    if serial:
        mode = 'serial'
        logging.info("Trying to log into guest %s using serial connection,"
                     " timeout %ds", vm.name, timeout)
        time.sleep(start)
        while time.time() < end_time:
            try:
                session = vm.serial_login()
                break
            except remote.LoginError, e:
                logging.debug(e)
            time.sleep(step)
    else:
        mode = 'remote'
        logging.info("Trying to log into guest %s using remote connection,"
                     " timeout %ds", vm.name, timeout)
        time.sleep(start)
        while time.time() < end_time:
            try:
                session = vm.login(nic_index=nic_index)
                break
            except (remote.LoginError, virt_vm.VMError), e:
                logging.debug(e)
            time.sleep(step)
        if not session and vm.get_params().get("try_serial_login") == "yes":
            mode = "serial"
            logging.info("Remote login failed, trying to login '%s' with "
                         "serial, timeout %ds", vm.name, timeout)
            time.sleep(start)
            while time.time() < end_time:
                try:
                    session = vm.serial_login()
                    break
                except remote.LoginError, e:
                    logging.debug(e)
                time.sleep(step)
    if not session:
        raise error.TestFail(
            "Could not log into guest %s using %s connection" %
            (vm.name, mode))
    logging.info("Logged into guest %s using %s connection", vm.name, mode)
    return session


def reboot(vm, session, method="shell", sleep_before_reset=10, nic_index=0,
           timeout=240):
    """
    Reboot the VM and wait for it to come back up by trying to log in until
    timeout expires.

    :param vm: VM object.
    :param session: A shell session object.
    :param method: Reboot method.  Can be "shell" (send a shell reboot
            command) or "system_reset" (send a system_reset monitor command).
    :param nic_index: Index of NIC to access in the VM, when logging in after
            rebooting.
    :param timeout: Time to wait before giving up (after rebooting).
    :return: A new shell session object.
    """
    if method == "shell":
        # Send a reboot command to the guest's shell
        session.sendline(vm.get_params().get("reboot_command"))
        logging.info("Reboot command sent. Waiting for guest to go down")
    elif method == "system_reset":
        # Sleep for a while before sending the command
        time.sleep(sleep_before_reset)
        # Clear the event list of all QMP monitors
        monitors = [m for m in vm.monitors if m.protocol == "qmp"]
        for m in monitors:
            m.clear_events()
        # Send a system_reset monitor command
        vm.monitor.cmd("system_reset")
        logging.info("Monitor command system_reset sent. Waiting for guest to "
                     "go down")
        # Look for RESET QMP events
        time.sleep(1)
        for m in monitors:
            if not m.get_event("RESET"):
                raise error.TestFail("RESET QMP event not received after "
                                     "system_reset (monitor '%s')" % m.name)
            else:
                logging.info("RESET QMP event received")
    else:
        logging.error("Unknown reboot method: %s", method)

    # Wait for the session to become unresponsive and close it
    if not utils_misc.wait_for(lambda: not session.is_responsive(timeout=30),
                               120, 0, 1):
        raise error.TestFail("Guest refuses to go down")
    session.close()

    # Try logging into the guest until timeout expires
    logging.info("Guest is down. Waiting for it to go up again, timeout %ds",
                 timeout)
    session = vm.wait_for_login(nic_index, timeout=timeout)
    logging.info("Guest is up again")
    return session


@error.context_aware
def update_boot_option(vm, args_removed=None, args_added=None,
                       need_reboot=True):
    """
    Update guest default kernel option.

    :param vm: The VM object.
    :param args_removed: Kernel options want to remove.
    :param args_added: Kernel options want to add.
    :param need_reboot: Whether need reboot VM or not.
    :raise error.TestError: Raised if fail to update guest kernel cmdlie.

    """
    if vm.params.get("os_type") == 'windows':
        # this function is only for linux, if we need to change
        # windows guest's boot option, we can use a function like:
        # update_win_bootloader(args_removed, args_added, reboot)
        # (this function is not implement.)
        # here we just:
        return

    login_timeout = int(vm.params.get("login_timeout"))
    session = vm.wait_for_login(timeout=login_timeout)

    msg = "Update guest kernel cmdline. "
    cmd = "grubby --update-kernel=`grubby --default-kernel` "
    if args_removed is not None:
        msg += " remove args: %s." % args_removed
        cmd += '--remove-args="%s." ' % args_removed
    if args_added is not None:
        msg += " add args: %s" % args_added
        cmd += '--args="%s"' % args_added
    error.context(msg, logging.info)
    s, o = session.cmd_status_output(cmd)
    if s != 0:
        logging.error(o)
        raise error.TestError("Fail to modify guest kernel cmdline")

    if need_reboot:
        error.context("Rebooting guest ...", logging.info)
        vm.reboot(session=session, timeout=login_timeout)


def migrate(vm, env=None, mig_timeout=3600, mig_protocol="tcp",
            mig_cancel=False, offline=False, stable_check=False,
            clean=False, save_path=None, dest_host='localhost', mig_port=None):
    """
    Migrate a VM locally and re-register it in the environment.

    :param vm: The VM to migrate.
    :param env: The environment dictionary.  If omitted, the migrated VM will
            not be registered.
    :param mig_timeout: timeout value for migration.
    :param mig_protocol: migration protocol
    :param mig_cancel: Test migrate_cancel or not when protocol is tcp.
    :param dest_host: Destination host (defaults to 'localhost').
    :param mig_port: Port that will be used for migration.
    :return: The post-migration VM, in case of same host migration, True in
            case of multi-host migration.
    """
    def mig_finished():
        try:
            o = vm.monitor.info("migrate")
            if isinstance(o, str):
                return "status: active" not in o
            else:
                return o.get("status") != "active"
        except Exception:
            pass

    def mig_succeeded():
        o = vm.monitor.info("migrate")
        if isinstance(o, str):
            return "status: completed" in o
        else:
            return o.get("status") == "completed"

    def mig_failed():
        o = vm.monitor.info("migrate")
        if isinstance(o, str):
            return "status: failed" in o
        else:
            return o.get("status") == "failed"

    def mig_cancelled():
        o = vm.monitor.info("migrate")
        if isinstance(o, str):
            return ("Migration status: cancelled" in o or
                    "Migration status: canceled" in o)
        else:
            return (o.get("status") == "cancelled" or
                    o.get("status") == "canceled")

    def wait_for_migration():
        if not utils_misc.wait_for(mig_finished, mig_timeout, 2, 2,
                                   "Waiting for migration to finish"):
            raise error.TestFail("Timeout expired while waiting for migration "
                                 "to finish")

    if dest_host == 'localhost':
        dest_vm = vm.clone()

    if (dest_host == 'localhost') and stable_check:
        # Pause the dest vm after creation
        dest_vm.params['extra_params'] = (dest_vm.params.get('extra_params', '')
                                          + ' -S')

    if dest_host == 'localhost':
        dest_vm.create(migration_mode=mig_protocol, mac_source=vm)

    try:
        try:
            if mig_protocol in ["tcp", "rdma", "x-rdma"]:
                if dest_host == 'localhost':
                    uri = mig_protocol + ":0:%d" % dest_vm.migration_port
                else:
                    uri = mig_protocol + ':%s:%d' % (dest_host, mig_port)
            elif mig_protocol == "unix":
                uri = "unix:%s" % dest_vm.migration_file
            elif mig_protocol == "exec":
                uri = '"exec:nc localhost %s"' % dest_vm.migration_port

            if offline:
                vm.pause()
            vm.monitor.migrate(uri)

            if mig_cancel:
                time.sleep(2)
                vm.monitor.cmd("migrate_cancel")
                if not utils_misc.wait_for(mig_cancelled, 60, 2, 2,
                                           "Waiting for migration "
                                           "cancellation"):
                    raise error.TestFail("Failed to cancel migration")
                if offline:
                    vm.resume()
                if dest_host == 'localhost':
                    dest_vm.destroy(gracefully=False)
                return vm
            else:
                wait_for_migration()
                if (dest_host == 'localhost') and stable_check:
                    save_path = None or "/tmp"
                    save1 = os.path.join(save_path, "src")
                    save2 = os.path.join(save_path, "dst")

                    vm.save_to_file(save1)
                    dest_vm.save_to_file(save2)

                    # Fail if we see deltas
                    md5_save1 = utils.hash_file(save1)
                    md5_save2 = utils.hash_file(save2)
                    if md5_save1 != md5_save2:
                        raise error.TestFail("Mismatch of VM state before "
                                             "and after migration")

                if (dest_host == 'localhost') and offline:
                    dest_vm.resume()
        except Exception:
            if dest_host == 'localhost':
                dest_vm.destroy()
            raise

    finally:
        if (dest_host == 'localhost') and stable_check and clean:
            logging.debug("Cleaning the state files")
            if os.path.isfile(save1):
                os.remove(save1)
            if os.path.isfile(save2):
                os.remove(save2)

    # Report migration status
    if mig_succeeded():
        logging.info("Migration finished successfully")
    elif mig_failed():
        raise error.TestFail("Migration failed")
    else:
        status = vm.monitor.info("migrate")
        raise error.TestFail("Migration ended with unknown status: %s" %
                             status)

    if dest_host == 'localhost':
        if dest_vm.monitor.verify_status("paused"):
            logging.debug("Destination VM is paused, resuming it")
            dest_vm.resume()

    # Kill the source VM
    vm.destroy(gracefully=False)

    # Replace the source VM with the new cloned VM
    if (dest_host == 'localhost') and (env is not None):
        env.register_vm(vm.name, dest_vm)

    # Return the new cloned VM
    if dest_host == 'localhost':
        return dest_vm
    else:
        return vm


def guest_active(vm):
    o = vm.monitor.info("status")
    if isinstance(o, str):
        return "status: running" in o
    else:
        if "status" in o:
            return o.get("status") == "running"
        else:
            return o.get("running")


class MigrationData(object):

    def __init__(self, params, srchost, dsthost, vms_name, params_append):
        """
        Class that contains data needed for one migration.
        """
        self.params = params.copy()
        self.params.update(params_append)

        self.source = False
        if params.get("hostid") == srchost:
            self.source = True

        self.destination = False
        if params.get("hostid") == dsthost:
            self.destination = True

        self.src = srchost
        self.dst = dsthost
        self.hosts = [srchost, dsthost]
        self.mig_id = {'src': srchost, 'dst': dsthost, "vms": vms_name}
        self.vms_name = vms_name
        self.vms = []
        self.vm_ports = None

    def is_src(self):
        """
        :return: True if host is source.
        """
        return self.source

    def is_dst(self):
        """
        :return: True if host is destination.
        """
        return self.destination


class MultihostMigration(object):

    """
    Class that provides a framework for multi-host migration.

    Migration can be run both synchronously and asynchronously.
    To specify what is going to happen during the multi-host
    migration, it is necessary to reimplement the method
    migration_scenario. It is possible to start multiple migrations
    in separate threads, since self.migrate is thread safe.

    Only one test using multihost migration framework should be
    started on one machine otherwise it is necessary to solve the
    problem with listen server port.

    Multihost migration starts SyncListenServer through which
    all messages are transferred, since the multiple hosts can
    be in different states.

    Class SyncData is used to transfer data over network or
    synchronize the migration process. Synchronization sessions
    are recognized by session_id.

    It is important to note that, in order to have multi-host
    migration, one needs shared guest image storage. The simplest
    case is when the guest images are on an NFS server.

    Example:
        class TestMultihostMigration(utils_misc.MultihostMigration):
            def __init__(self, test, params, env):
                super(testMultihostMigration, self).__init__(test, params, env)

            def migration_scenario(self):
                srchost = self.params.get("hosts")[0]
                dsthost = self.params.get("hosts")[1]

                def worker(mig_data):
                    vm = env.get_vm("vm1")
                    session = vm.wait_for_login(timeout=self.login_timeout)
                    session.sendline("nohup dd if=/dev/zero of=/dev/null &")
                    session.cmd("killall -0 dd")

                def check_worker(mig_data):
                    vm = env.get_vm("vm1")
                    session = vm.wait_for_login(timeout=self.login_timeout)
                    session.cmd("killall -9 dd")

                # Almost synchronized migration, waiting to end it.
                # Work is started only on first VM.
                self.migrate_wait(["vm1", "vm2"], srchost, dsthost,
                                  worker, check_worker)

                # Migration started in different threads.
                # It allows to start multiple migrations simultaneously.
                mig1 = self.migrate(["vm1"], srchost, dsthost,
                                    worker, check_worker)
                mig2 = self.migrate(["vm2"], srchost, dsthost)
                mig2.join()
                mig1.join()

    mig = TestMultihostMigration(test, params, env)
    mig.run()
    """

    def __init__(self, test, params, env, preprocess_env=True):
        self.test = test
        self.params = params
        self.env = env
        self.hosts = params.get("hosts")
        self.hostid = params.get('hostid', "")
        self.comm_port = int(params.get("comm_port", 13234))
        vms_count = len(params["vms"].split())

        self.login_timeout = int(params.get("login_timeout", 360))
        self.disk_prepare_timeout = int(params.get("disk_prepare_timeout",
                                                   160 * vms_count))
        self.finish_timeout = int(params.get("finish_timeout",
                                             120 * vms_count))

        self.new_params = None

        if params.get("clone_master") == "yes":
            self.clone_master = True
        else:
            self.clone_master = False

        self.mig_timeout = int(params.get("mig_timeout"))
        # Port used to communicate info between source and destination
        self.regain_ip_cmd = params.get("regain_ip_cmd", None)
        self.not_login_after_mig = params.get("not_login_after_mig", None)

        self.vm_lock = threading.Lock()

        self.sync_server = None
        if self.clone_master:
            self.sync_server = SyncListenServer()

        if preprocess_env:
            self.preprocess_env()
            self._hosts_barrier(self.hosts, self.hosts, 'disk_prepared',
                                self.disk_prepare_timeout)

    def migration_scenario(self):
        """
        Multi Host migration_scenario is started from method run where the
        exceptions are checked. It is not necessary to take care of
        cleaning up after test crash or finish.
        """
        raise NotImplementedError

    def post_migration(self, vm, cancel_delay, mig_offline, dsthost, vm_ports,
                       not_wait_for_migration, fd, mig_data):
        pass

    def migrate_vms_src(self, mig_data):
        """
        Migrate vms source.

        :param mig_Data: Data for migration.

        For change way how machine migrates is necessary
        re implement this method.
        """
        def mig_wrapper(vm, cancel_delay, dsthost, vm_ports,
                        not_wait_for_migration, mig_offline, mig_data):
            vm.migrate(cancel_delay=cancel_delay, offline=mig_offline,
                       dest_host=dsthost, remote_port=vm_ports[vm.name],
                       not_wait_for_migration=not_wait_for_migration)

            self.post_migration(vm, cancel_delay, mig_offline, dsthost,
                                vm_ports, not_wait_for_migration, None,
                                mig_data)

        logging.info("Start migrating now...")
        cancel_delay = mig_data.params.get("cancel_delay")
        if cancel_delay is not None:
            cancel_delay = int(cancel_delay)
        not_wait_for_migration = mig_data.params.get("not_wait_for_migration")
        if not_wait_for_migration == "yes":
            not_wait_for_migration = True
        mig_offline = mig_data.params.get("mig_offline")
        if mig_offline == "yes":
            mig_offline = True
        else:
            mig_offline = False

        multi_mig = []
        for vm in mig_data.vms:
            multi_mig.append((mig_wrapper, (vm, cancel_delay, mig_data.dst,
                                            mig_data.vm_ports,
                                            not_wait_for_migration,
                                            mig_offline, mig_data)))
        utils_misc.parallel(multi_mig)

    def migrate_vms_dest(self, mig_data):
        """
        Migrate vms destination. This function is started on dest host during
        migration.

        :param mig_Data: Data for migration.
        """
        pass

    def __del__(self):
        if self.sync_server:
            self.sync_server.close()

    def master_id(self):
        return self.hosts[0]

    def _hosts_barrier(self, hosts, session_id, tag, timeout):
        logging.debug("Barrier timeout: %d tags: %s" % (timeout, tag))
        tags = SyncData(self.master_id(), self.hostid, hosts,
                        "%s,%s,barrier" % (str(session_id), tag),
                        self.sync_server).sync(tag, timeout)
        logging.debug("Barrier tag %s" % (tags))

    def preprocess_env(self):
        """
        Prepare env to start vms.
        """
        storage.preprocess_images(self.test.bindir, self.params, self.env)

    def _check_vms_source(self, mig_data):
        start_mig_tout = mig_data.params.get("start_migration_timeout", None)
        if start_mig_tout is None:
            for vm in mig_data.vms:
                vm.wait_for_login(timeout=self.login_timeout)

        if mig_data.params.get("host_mig_offline") != "yes":
            sync = SyncData(self.master_id(), self.hostid, mig_data.hosts,
                            mig_data.mig_id, self.sync_server)
            mig_data.vm_ports = sync.sync(timeout=240)[mig_data.dst]
            logging.info("Received from destination the migration port %s",
                         str(mig_data.vm_ports))

    def _check_vms_dest(self, mig_data):
        mig_data.vm_ports = {}
        for vm in mig_data.vms:
            logging.info("Communicating to source migration port %s",
                         vm.migration_port)
            mig_data.vm_ports[vm.name] = vm.migration_port

        if mig_data.params.get("host_mig_offline") != "yes":
            SyncData(self.master_id(), self.hostid,
                     mig_data.hosts, mig_data.mig_id,
                     self.sync_server).sync(mig_data.vm_ports, timeout=240)

    def _prepare_params(self, mig_data):
        """
        Prepare separate params for vm migration.

        :param vms_name: List of vms.
        """
        new_params = mig_data.params.copy()
        new_params["vms"] = " ".join(mig_data.vms_name)
        return new_params

    def _check_vms(self, mig_data):
        """
        Check if vms are started correctly.

        :param vms: list of vms.
        :param source: Must be True if is source machine.
        """
        logging.info("Try check vms %s" % (mig_data.vms_name))
        for vm in mig_data.vms_name:
            if not self.env.get_vm(vm) in mig_data.vms:
                mig_data.vms.append(self.env.get_vm(vm))
        for vm in mig_data.vms:
            logging.info("Check vm %s on host %s" % (vm.name, self.hostid))
            vm.verify_alive()

        if mig_data.is_src():
            self._check_vms_source(mig_data)
        else:
            self._check_vms_dest(mig_data)

    def prepare_for_migration(self, mig_data, migration_mode):
        """
        Prepare destination of migration for migration.

        :param mig_data: Class with data necessary for migration.
        :param migration_mode: Migration mode for prepare machine.
        """
        new_params = self._prepare_params(mig_data)

        new_params['migration_mode'] = migration_mode
        new_params['start_vm'] = 'yes'
        self.vm_lock.acquire()
        env_process.process(self.test, new_params, self.env,
                            env_process.preprocess_image,
                            env_process.preprocess_vm)
        self.vm_lock.release()

        self._check_vms(mig_data)

    def migrate_vms(self, mig_data):
        """
        Migrate vms.
        """
        if mig_data.is_src():
            self.migrate_vms_src(mig_data)
        else:
            self.migrate_vms_dest(mig_data)

    def check_vms_dst(self, mig_data):
        """
        Check vms after migrate.

        :param mig_data: object with migration data.
        """
        for vm in mig_data.vms:
            vm.resume()
            if not guest_active(vm):
                raise error.TestFail("Guest not active after migration")

        logging.info("Migrated guest appears to be running")

        logging.info("Logging into migrated guest after migration...")
        for vm in mig_data.vms:
            if not self.regain_ip_cmd is None:
                session_serial = vm.wait_for_serial_login(timeout=
                                                          self.login_timeout)
                # There is sometime happen that system sends some message on
                # serial console and IP renew command block test. Because
                # there must be added "sleep" in IP renew command.
                session_serial.cmd(self.regain_ip_cmd)

            if not self.not_login_after_mig:
                vm.wait_for_login(timeout=self.login_timeout)

    def check_vms_src(self, mig_data):
        """
        Check vms after migrate.

        :param mig_data: object with migration data.
        """
        pass

    def postprocess_env(self):
        """
        Kill vms and delete cloned images.
        """
        pass

    def before_migration(self, mig_data):
        """
        Do something right before migration.

        :param mig_data: object with migration data.
        """
        pass

    def migrate(self, vms_name, srchost, dsthost, start_work=None,
                check_work=None, mig_mode="tcp", params_append=None):
        """
        Migrate machine from srchost to dsthost. It executes start_work on
        source machine before migration and executes check_work on dsthost
        after migration.

        Migration execution progress:

        source host                   |   dest host
        --------------------------------------------------------
           prepare guest on both sides of migration
            - start machine and check if machine works
            - synchronize transfer data needed for migration
        --------------------------------------------------------
        start work on source guests   |   wait for migration
        --------------------------------------------------------
                     migrate guest to dest host.
              wait on finish migration synchronization
        --------------------------------------------------------
                                      |   check work on vms
        --------------------------------------------------------
                    wait for sync on finish migration

        :param vms_name: List of vms.
        :param srchost: src host id.
        :param dsthost: dst host id.
        :param start_work: Function started before migration.
        :param check_work: Function started after migration.
        :param mig_mode: Migration mode.
        :param params_append: Append params to self.params only for migration.
        """
        def migrate_wrap(vms_name, srchost, dsthost, start_work=None,
                         check_work=None, params_append=None):
            logging.info("Starting migrate vms %s from host %s to %s" %
                         (vms_name, srchost, dsthost))
            pause = self.params.get("paused_after_start_vm")
            mig_error = None
            mig_data = MigrationData(self.params, srchost, dsthost,
                                     vms_name, params_append)
            cancel_delay = self.params.get("cancel_delay", None)
            host_offline_migration = self.params.get("host_mig_offline")

            try:
                try:
                    if mig_data.is_src():
                        self.prepare_for_migration(mig_data, None)
                    elif self.hostid == dsthost:
                        if host_offline_migration != "yes":
                            self.prepare_for_migration(mig_data, mig_mode)
                    else:
                        return

                    if mig_data.is_src():
                        if start_work:
                            if pause != "yes":
                                start_work(mig_data)
                            else:
                                raise error.TestNAError("Can't start work if "
                                                        "vm is paused.")

                    # Starts VM and waits timeout before migration.
                    if pause == "yes" and mig_data.is_src():
                        for vm in mig_data.vms:
                            vm.resume()
                        wait = self.params.get("start_migration_timeout", 0)
                        logging.debug("Wait for migraiton %s seconds." %
                                      (wait))
                        time.sleep(int(wait))

                    self.before_migration(mig_data)

                    self.migrate_vms(mig_data)

                    timeout = 60
                    if cancel_delay is None:
                        if host_offline_migration == "yes":
                            self._hosts_barrier(self.hosts,
                                                mig_data.mig_id,
                                                'wait_for_offline_mig',
                                                self.finish_timeout)
                            if mig_data.is_dst():
                                self.prepare_for_migration(mig_data, mig_mode)
                            self._hosts_barrier(self.hosts,
                                                mig_data.mig_id,
                                                'wait2_for_offline_mig',
                                                self.finish_timeout)

                        if (not mig_data.is_src()):
                            timeout = self.mig_timeout
                        self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                                            'mig_finished', timeout)

                        if mig_data.is_dst():
                            self.check_vms_dst(mig_data)
                            if check_work:
                                check_work(mig_data)
                        else:
                            self.check_vms_src(mig_data)
                            if check_work:
                                check_work(mig_data)
                except:
                    mig_error = True
                    raise
            finally:
                if not mig_error and cancel_delay is None:
                    self._hosts_barrier(self.hosts,
                                        mig_data.mig_id,
                                        'test_finihed',
                                        self.finish_timeout)
                elif mig_error:
                    raise

        def wait_wrap(vms_name, srchost, dsthost):
            mig_data = MigrationData(self.params, srchost, dsthost, vms_name,
                                     None)
            timeout = (self.login_timeout + self.mig_timeout +
                       self.finish_timeout)

            self._hosts_barrier(self.hosts, mig_data.mig_id,
                                'test_finihed', timeout)

        if (self.hostid in [srchost, dsthost]):
            mig_thread = utils.InterruptedThread(migrate_wrap, (vms_name,
                                                                srchost,
                                                                dsthost,
                                                                start_work,
                                                                check_work,
                                                                params_append))
        else:
            mig_thread = utils.InterruptedThread(wait_wrap, (vms_name,
                                                             srchost,
                                                             dsthost))
        mig_thread.start()
        return mig_thread

    def migrate_wait(self, vms_name, srchost, dsthost, start_work=None,
                     check_work=None, mig_mode="tcp", params_append=None):
        """
        Migrate machine from srchost to dsthost and wait for finish.
        It executes start_work on source machine before migration and executes
        check_work on dsthost after migration.

        :param vms_name: List of vms.
        :param srchost: src host id.
        :param dsthost: dst host id.
        :param start_work: Function which is started before migration.
        :param check_work: Function which is started after
                           done of migration.
        """
        self.migrate(vms_name, srchost, dsthost, start_work, check_work,
                     mig_mode, params_append).join()

    def cleanup(self):
        """
        Cleanup env after test.
        """
        if self.clone_master:
            self.sync_server.close()
            self.postprocess_env()

    def run(self):
        """
        Start multihost migration scenario.
        After scenario is finished or if scenario crashed it calls postprocess
        machines and cleanup env.
        """
        try:
            self.migration_scenario()

            self._hosts_barrier(self.hosts, self.hosts, 'all_test_finihed',
                                self.finish_timeout)
        finally:
            self.cleanup()


class MultihostMigrationFd(MultihostMigration):

    def __init__(self, test, params, env, preprocess_env=True):
        super(MultihostMigrationFd, self).__init__(test, params, env,
                                                   preprocess_env)

    def migrate_vms_src(self, mig_data):
        """
        Migrate vms source.

        :param mig_Data: Data for migration.

        For change way how machine migrates is necessary
        re implement this method.
        """
        def mig_wrapper(vm, cancel_delay, mig_offline, dsthost, vm_ports,
                        not_wait_for_migration, fd):
            vm.migrate(cancel_delay=cancel_delay, offline=mig_offline,
                       dest_host=dsthost,
                       not_wait_for_migration=not_wait_for_migration,
                       protocol="fd",
                       fd_src=fd)

            self.post_migration(vm, cancel_delay, mig_offline, dsthost,
                                vm_ports, not_wait_for_migration, fd, mig_data)

        logging.info("Start migrating now...")
        cancel_delay = mig_data.params.get("cancel_delay")
        if cancel_delay is not None:
            cancel_delay = int(cancel_delay)
        not_wait_for_migration = mig_data.params.get("not_wait_for_migration")
        if not_wait_for_migration == "yes":
            not_wait_for_migration = True
        mig_offline = mig_data.params.get("mig_offline")
        if mig_offline == "yes":
            mig_offline = True
        else:
            mig_offline = False

        multi_mig = []
        for vm in mig_data.vms:
            fd = vm.params.get("migration_fd")
            multi_mig.append((mig_wrapper, (vm, cancel_delay, mig_offline,
                                            mig_data.dst, mig_data.vm_ports,
                                            not_wait_for_migration,
                                            fd)))
        utils_misc.parallel(multi_mig)

    def _check_vms_source(self, mig_data):
        start_mig_tout = mig_data.params.get("start_migration_timeout", None)
        if start_mig_tout is None:
            for vm in mig_data.vms:
                vm.wait_for_login(timeout=self.login_timeout)
        self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                            'prepare_VMS', 60)

    def _check_vms_dest(self, mig_data):
        self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                            'prepare_VMS', 120)
        for vm in mig_data.vms:
            fd = vm.params.get("migration_fd")
            os.close(fd)

    def _connect_to_server(self, host, port, timeout=60):
        """
        Connect to network server.
        """
        endtime = time.time() + timeout
        sock = None
        while endtime > time.time():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.connect((host, port))
                break
            except socket.error, err:
                (code, _) = err
                if (code != errno.ECONNREFUSED):
                    raise
                time.sleep(1)

        return sock

    def _create_server(self, port, timeout=60):
        """
        Create network server.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        sock.bind(('', port))
        sock.listen(1)
        return sock

    def migrate_wait(self, vms_name, srchost, dsthost, start_work=None,
                     check_work=None, mig_mode="fd", params_append=None):
        vms_count = len(vms_name)
        mig_ports = []

        if self.params.get("hostid") == srchost:
            last_port = 5199
            for _ in range(vms_count):
                last_port = utils_misc.find_free_port(last_port + 1, 6000)
                mig_ports.append(last_port)

        sync = SyncData(self.master_id(), self.hostid,
                        self.params.get("hosts"),
                        {'src': srchost, 'dst': dsthost,
                         'port': "ports"}, self.sync_server)

        mig_ports = sync.sync(mig_ports, timeout=120)
        mig_ports = mig_ports[srchost]
        logging.debug("Migration port %s" % (mig_ports))

        if self.params.get("hostid") != srchost:
            sockets = []
            for mig_port in mig_ports:
                sockets.append(self._connect_to_server(srchost, mig_port))
            try:
                fds = {}
                for s, vm_name in zip(sockets, vms_name):
                    fds["migration_fd_%s" % vm_name] = s.fileno()
                logging.debug("File descrtiptors %s used for"
                              " migration." % (fds))

                super_cls = super(MultihostMigrationFd, self)
                super_cls.migrate_wait(vms_name, srchost, dsthost,
                                       start_work=start_work, mig_mode="fd",
                                       params_append=fds)
            finally:
                for s in sockets:
                    s.close()
        else:
            sockets = []
            for mig_port in mig_ports:
                sockets.append(self._create_server(mig_port))
            try:
                conns = []
                for s in sockets:
                    conns.append(s.accept()[0])
                fds = {}
                for conn, vm_name in zip(conns, vms_name):
                    fds["migration_fd_%s" % vm_name] = conn.fileno()
                logging.debug("File descrtiptors %s used for"
                              " migration." % (fds))

                # Prohibits descriptor inheritance.
                for fd in fds.values():
                    flags = fcntl.fcntl(fd, fcntl.F_GETFD)
                    flags |= fcntl.FD_CLOEXEC
                    fcntl.fcntl(fd, fcntl.F_SETFD, flags)

                super_cls = super(MultihostMigrationFd, self)
                super_cls.migrate_wait(vms_name, srchost, dsthost,
                                       start_work=start_work, mig_mode="fd",
                                       params_append=fds)
                for conn in conns:
                    conn.close()
            finally:
                for s in sockets:
                    s.close()


class MultihostMigrationExec(MultihostMigration):

    def __init__(self, test, params, env, preprocess_env=True):
        super(MultihostMigrationExec, self).__init__(test, params, env,
                                                     preprocess_env)

    def post_migration(self, vm, cancel_delay, mig_offline, dsthost,
                       mig_exec_cmd, not_wait_for_migration, fd,
                       mig_data):
        if mig_data.params.get("host_mig_offline") == "yes":
            src_tmp = vm.params.get("migration_sfiles_path")
            dst_tmp = vm.params.get("migration_dfiles_path")
            username = vm.params.get("username")
            password = vm.params.get("password")
            remote.scp_to_remote(dsthost, "22", username, password,
                                 src_tmp, dst_tmp)

    def migrate_vms_src(self, mig_data):
        """
        Migrate vms source.

        :param mig_Data: Data for migration.

        For change way how machine migrates is necessary
        re implement this method.
        """
        def mig_wrapper(vm, cancel_delay, mig_offline, dsthost, mig_exec_cmd,
                        not_wait_for_migration, mig_data):
            vm.migrate(cancel_delay=cancel_delay,
                       offline=mig_offline,
                       dest_host=dsthost,
                       not_wait_for_migration=not_wait_for_migration,
                       protocol="exec",
                       migration_exec_cmd_src=mig_exec_cmd)

            self.post_migration(vm, cancel_delay, mig_offline,
                                dsthost, mig_exec_cmd,
                                not_wait_for_migration, None, mig_data)

        logging.info("Start migrating now...")
        cancel_delay = mig_data.params.get("cancel_delay")
        if cancel_delay is not None:
            cancel_delay = int(cancel_delay)
        not_wait_for_migration = mig_data.params.get("not_wait_for_migration")
        if not_wait_for_migration == "yes":
            not_wait_for_migration = True
        mig_offline = mig_data.params.get("mig_offline")
        if mig_offline == "yes":
            mig_offline = True
        else:
            mig_offline = False

        multi_mig = []
        for vm in mig_data.vms:
            mig_exec_cmd = vm.params.get("migration_exec_cmd_src")
            multi_mig.append((mig_wrapper, (vm, cancel_delay,
                                            mig_offline,
                                            mig_data.dst,
                                            mig_exec_cmd,
                                            not_wait_for_migration,
                                            mig_data)))
        utils_misc.parallel(multi_mig)

    def _check_vms_source(self, mig_data):
        start_mig_tout = mig_data.params.get("start_migration_timeout", None)
        if start_mig_tout is None:
            for vm in mig_data.vms:
                vm.wait_for_login(timeout=self.login_timeout)

        if mig_data.params.get("host_mig_offline") != "yes":
            self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                                'prepare_VMS', 60)

    def _check_vms_dest(self, mig_data):
        if mig_data.params.get("host_mig_offline") != "yes":
            self._hosts_barrier(mig_data.hosts, mig_data.mig_id,
                                'prepare_VMS', 120)

    def migrate_wait(self, vms_name, srchost, dsthost, start_work=None,
                     check_work=None, mig_mode="exec", params_append=None):
        vms_count = len(vms_name)
        mig_ports = []

        host_offline_migration = self.params.get("host_mig_offline")

        sync = SyncData(self.master_id(), self.hostid,
                        self.params.get("hosts"),
                        {'src': srchost, 'dst': dsthost,
                         'port': "ports"}, self.sync_server)

        mig_params = {}

        if host_offline_migration != "yes":
            if self.params.get("hostid") == dsthost:
                last_port = 5199
                for _ in range(vms_count):
                    last_port = utils_misc.find_free_port(last_port + 1, 6000)
                    mig_ports.append(last_port)

            mig_ports = sync.sync(mig_ports, timeout=120)
            mig_ports = mig_ports[dsthost]
            logging.debug("Migration port %s" % (mig_ports))
            mig_cmds = {}
            for mig_port, vm_name in zip(mig_ports, vms_name):
                mig_dst_cmd = "nc -l %s %s" % (dsthost, mig_port)
                mig_src_cmd = "nc %s %s" % (dsthost, mig_port)
                mig_params["migration_exec_cmd_src_%s" %
                           (vm_name)] = mig_src_cmd
                mig_params["migration_exec_cmd_dst_%s" %
                           (vm_name)] = mig_dst_cmd
        else:
            # Generate filenames for migration.
            mig_fnam = {}
            for vm_name in vms_name:
                while True:
                    fnam = ("mig_" + utils.generate_random_string(6) +
                            "." + vm_name)
                    fpath = os.path.join(self.test.tmpdir, fnam)
                    if (not fnam in mig_fnam.values() and
                            not os.path.exists(fnam)):
                        mig_fnam[vm_name] = fpath
                        break
            mig_fs = sync.sync(mig_fnam, timeout=120)
            mig_cmds = {}
            # Prepare cmd and files.
            if self.params.get("hostid") == srchost:
                mig_src_cmd = "gzip -c > %s"
                for vm_name in vms_name:
                    mig_params["migration_sfiles_path_%s" % (vm_name)] = (
                        mig_fs[srchost][vm_name])
                    mig_params["migration_dfiles_path_%s" % (vm_name)] = (
                        mig_fs[dsthost][vm_name])

                    mig_params["migration_exec_cmd_src_%s" % (vm_name)] = (
                        mig_src_cmd % mig_fs[srchost][vm_name])

            if self.params.get("hostid") == dsthost:
                mig_dst_cmd = "gzip -c -d %s"
                for vm_name in vms_name:
                    mig_params["migration_exec_cmd_dst_%s" % (vm_name)] = (
                        mig_dst_cmd % mig_fs[dsthost][vm_name])

        logging.debug("Exec commands %s", mig_cmds)

        super_cls = super(MultihostMigrationExec, self)
        super_cls.migrate_wait(vms_name, srchost, dsthost,
                               start_work=start_work, mig_mode=mig_mode,
                               params_append=mig_params)


def stop_windows_service(session, service, timeout=120):
    """
    Stop a Windows service using sc.
    If the service is already stopped or is not installed, do nothing.

    :param service: The name of the service
    :param timeout: Time duration to wait for service to stop
    :raise error.TestError: Raised if the service can't be stopped
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        o = session.cmd_output("sc stop %s" % service, timeout=60)
        # FAILED 1060 means the service isn't installed.
        # FAILED 1062 means the service hasn't been started.
        if re.search(r"\bFAILED (1060|1062)\b", o, re.I):
            break
        time.sleep(1)
    else:
        raise error.TestError("Could not stop service '%s'" % service)


def start_windows_service(session, service, timeout=120):
    """
    Start a Windows service using sc.
    If the service is already running, do nothing.
    If the service isn't installed, fail.

    :param service: The name of the service
    :param timeout: Time duration to wait for service to start
    :raise error.TestError: Raised if the service can't be started
    """
    end_time = time.time() + timeout
    while time.time() < end_time:
        o = session.cmd_output("sc start %s" % service, timeout=60)
        # FAILED 1060 means the service isn't installed.
        if re.search(r"\bFAILED 1060\b", o, re.I):
            raise error.TestError("Could not start service '%s' "
                                  "(service not installed)" % service)
        # FAILED 1056 means the service is already running.
        if re.search(r"\bFAILED 1056\b", o, re.I):
            break
        time.sleep(1)
    else:
        raise error.TestError("Could not start service '%s'" % service)


def get_windows_file_abs_path(session, filename, extension="exe", tmout=240):
    """
    return file abs path "drive+path" by "wmic datafile"
    """
    cmd_tmp = "wmic datafile where \"Filename='%s' and "
    cmd_tmp += "extension='%s'\" get drive^,path"
    cmd = cmd_tmp % (filename, extension)
    info = session.cmd_output(cmd, timeout=tmout).strip()
    drive_path = re.search(r'(\w):\s+(\S+)', info, re.M)
    if not drive_path:
        raise error.TestError("Not found file %s.%s in your guest"
                              % (filename, extension))
    return ":".join(drive_path.groups())


def get_windows_disk_drive(session, filename, extension="exe", tmout=240):
    """
    Get the windows disk drive number
    """
    return get_windows_file_abs_path(session, filename,
                                     extension).split(":")[0]


def get_time(session, time_command, time_filter_re, time_format):
    """
    Return the host time and guest time.  If the guest time cannot be fetched
    a TestError exception is raised.

    Note that the shell session should be ready to receive commands
    (i.e. should "display" a command prompt and should be done with all
    previous commands).

    :param session: A shell session.
    :param time_command: Command to issue to get the current guest time.
    :param time_filter_re: Regex filter to apply on the output of
            time_command in order to get the current time.
    :param time_format: Format string to pass to time.strptime() with the
            result of the regex filter.
    :return: A tuple containing the host time and guest time.
    """
    if re.findall("ntpdate|w32tm", time_command):
        o = session.cmd(time_command)
        if re.match('ntpdate', time_command):
            offset = re.findall('offset (.*) sec', o)[0]
            host_main, host_mantissa = re.findall(time_filter_re, o)[0]
            host_time = (time.mktime(time.strptime(host_main, time_format)) +
                         float("0.%s" % host_mantissa))
            guest_time = host_time - float(offset)
        else:
            guest_time = re.findall(time_filter_re, o)[0]
            offset = re.findall("o:(.*)s", o)[0]
            if re.match('PM', guest_time):
                hour = re.findall('\d+ (\d+):', guest_time)[0]
                hour = str(int(hour) + 12)
                guest_time = re.sub('\d+\s\d+:', "\d+\s%s:" % hour,
                                    guest_time)[:-3]
            else:
                guest_time = guest_time[:-3]
            guest_time = time.mktime(time.strptime(guest_time, time_format))
            host_time = guest_time + float(offset)
    elif re.findall("hwclock", time_command):
        loc = locale.getlocale(locale.LC_TIME)
        # Get and parse host time
        host_time_out = utils.run(time_command).stdout
        host_time_out, diff = host_time_out.split("  ")
        try:
            try:
                locale.setlocale(locale.LC_TIME, "C")
                host_time = time.mktime(time.strptime(host_time_out, time_format))
                host_time += float(diff.split(" ")[0])
            except Exception, e:
                logging.debug("(time_format, time_string): (%s, %s)",
                              time_format, host_time_out)
                raise e
        finally:
            locale.setlocale(locale.LC_TIME, loc)

        s = session.cmd_output(time_command)

        # Get and parse guest time
        try:
            s = re.findall(time_filter_re, s)[0]
            s, diff = s.split("  ")
        except IndexError:
            logging.debug("The time string from guest is:\n%s", s)
            raise error.TestError("The time string from guest is unexpected.")
        except Exception, e:
            logging.debug("(time_filter_re, time_string): (%s, %s)",
                          time_filter_re, s)
            raise e

        guest_time = None
        try:
            try:
                locale.setlocale(locale.LC_TIME, "C")
                guest_time = time.mktime(time.strptime(s, time_format))
                guest_time += float(diff.split(" ")[0])
            except Exception, e:
                logging.debug("(time_format, time_string): (%s, %s)",
                              time_format, host_time_out)
                raise e
        finally:
            locale.setlocale(locale.LC_TIME, loc)
    else:
        host_time = time.time()
        s = session.cmd_output(time_command)
        n = 0.0
        reo = None

        try:
            reo = re.findall(time_filter_re, s)[0]
            s = reo[0]
            if len(reo) > 1:
                n = float(reo[1])
        except IndexError:
            logging.debug("The time string from guest is:\n%s", s)
            raise error.TestError("The time string from guest is unexpected.")
        except ValueError, e:
            logging.debug("Couldn't create float number from %s" % (reo[1]))
        except Exception, e:
            logging.debug("(time_filter_re, time_string): (%s, %s)",
                          time_filter_re, s)
            raise e

        guest_time = time.mktime(time.strptime(s, time_format)) + n

    return (host_time, guest_time)


def dump_command_output(session, command, filename, timeout=30.0,
                        internal_timeout=1.0, print_func=None):
    """
    :param session: a saved communication between host and guest.
    :param command: will running in guest side.
    :param filename: redirect command output to the specify file
    :param timeout: the duration (in seconds) to wait until a match is found.
    :param internal_timeout: the timeout to pass to read_nonblocking.
    :param print_func: a function to be used to print the data being read.
    :return: Command output(string).
    """

    (status, output) = session.cmd_status_output(command, timeout,
                                                 internal_timeout, print_func)
    if status != 0:
        raise error.TestError("Failed to run command %s in guest." % command)
    try:
        f = open(filename, "w")
    except IOError:
        raise error.TestError("Failed to open file opject: %s" % file)
    f.write(output)
    f.close()


def fix_atest_cmd(atest_basedir, cmd, ip):
    """
    fixes the command "autotest/cli/atest" for the external server tests.

    e.g.
    1. adding -w autotest server argument;
    2. adding autotest/cli/atest prefix/basedir;
    and etc..

    :param atest_basedir: base dir of autotest/cli/atest
    :param cmd: command to fix.
    :param ip: ip of the autotest server to add to the command.
    """
    cmd = os.path.join(atest_basedir, cmd)
    return ''.join([cmd, " -w ", ip])


def get_svr_session(ip, port="22", usrname="root", passwd="123456", prompt=""):
    """
    :param ip: IP address of the server.
    :param port: the port for remote session.
    :param usrname: user name for remote login.
    :param passwd: password.
    :param prompt: shell/session prompt for the connection.
    """
    session = remote.remote_login('ssh', ip, port, usrname, passwd, prompt)
    if not session:
        raise error.TestError("Failed to login to the autotest server.")

    return session


def get_memory_info(lvms):
    """
    Get memory information from host and guests in format:
    Host: memfree = XXXM; Guests memsh = {XXX,XXX,...}

    :params lvms: List of VM objects
    :return: String with memory info report
    """
    if not isinstance(lvms, list):
        raise error.TestError("Invalid list passed to get_stat: %s " % lvms)

    try:
        meminfo = "Host: memfree = "
        meminfo += str(int(utils_memory.freememtotal()) / 1024) + "M; "
        meminfo += "swapfree = "
        mf = int(utils_memory.read_from_meminfo("SwapFree")) / 1024
        meminfo += str(mf) + "M; "
    except Exception, e:
        raise error.TestFail("Could not fetch host free memory info, "
                             "reason: %s" % e)

    meminfo += "Guests memsh = {"
    for vm in lvms:
        shm = vm.get_shared_meminfo()
        if shm is None:
            raise error.TestError("Could not get shared meminfo from "
                                  "VM %s" % vm)
        meminfo += "%dM; " % shm
    meminfo = meminfo[0:-2] + "}"

    return meminfo


def domstat_cgroup_cpuacct_percpu(domain, qemu_path="/libvirt/qemu/"):
    """
    Get a list of domain-specific per CPU stats from cgroup cpuacct controller.

    :param domain: Domain name
    :param qemu_path: Default: "/libvirt/qemu/".
                      Please refer OS doc to pass the correct qemu path.
                      $CGRP_MNTPT/cpuacct/<$qemu_path>/<domain>..
    """
    percpu_act_file = (utils_cgroup.get_cgroup_mountpoint("cpuacct") +
                       qemu_path + domain + "/cpuacct.usage_percpu")
    try:
        f_percpu_act = open(percpu_act_file, "rU")
        cpuacct_usage_percpu = f_percpu_act.readline().split()
        f_percpu_act.close()
        return cpuacct_usage_percpu
    except IOError:
        raise error.TestError("Failed to get per cpu stat from %s" %
                              percpu_act_file)


@error.context_aware
def run_image_copy(test, params, env):
    """
    Copy guest images from nfs server.
    1) Mount the NFS share directory
    2) Check the existence of source image
    3) If it exists, copy the image from NFS

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    if vm is not None:
        vm.destroy()

    src = params.get('images_good')
    asset_name = '%s' % (os.path.split(params['image_name'])[1])
    image = '%s.%s' % (params['image_name'], params['image_format'])
    dst_path = '%s/%s' % (virttest.data_dir.get_data_dir(), image)
    image_dir = os.path.dirname(dst_path)
    if params.get("rename_error_image", "no") == "yes":
        error_image = os.path.basename(params['image_name']) + "-error"
        error_image += '.' + params['image_format']
        error_dst_path = os.path.join(image_dir, error_image)
        mv_cmd = "/bin/mv %s %s" % (dst_path, error_dst_path)
        utils.system(mv_cmd, timeout=360, ignore_status=True)

    if src:
        mount_dest_dir = params.get('dst_dir', '/mnt/images')
        if not os.path.exists(mount_dest_dir):
            try:
                os.makedirs(mount_dest_dir)
            except OSError, err:
                logging.warning('mkdir %s error:\n%s', mount_dest_dir, err)

        if not os.path.exists(mount_dest_dir):
            raise error.TestError('Failed to create NFS share dir %s' %
                                  mount_dest_dir)

        error.context("Mount the NFS share directory")
        if not utils_misc.mount(src, mount_dest_dir, 'nfs', 'ro'):
            raise error.TestError('Could not mount NFS share %s to %s' %
                                  (src, mount_dest_dir))

        error.context("Check the existence of source image")
        src_path = '%s/%s.%s' % (mount_dest_dir, asset_name,
                                 params['image_format'])
        asset_info = virttest.asset.get_file_asset(asset_name, src_path,
                                                   dst_path)
        if asset_info is None:
            raise error.TestError('Could not find %s' % image)
    else:
        asset_info = virttest.asset.get_asset_info(asset_name)

    # Do not force extraction if integrity information is available
    if asset_info['sha1_url']:
        force = params.get("force_copy", "no") == "yes"
    else:
        force = params.get("force_copy", "yes") == "yes"

    try:
        error.context("Copy image '%s'" % image, logging.info)
        if utils.is_url(asset_info['url']):
            virttest.asset.download_file(asset_info, interactive=False,
                                         force=force)
        else:
            utils.get_file(asset_info['url'], asset_info['destination'])

    finally:
        sub_type = params.get("sub_type")
        if sub_type:
            error.context("Run sub test '%s'" % sub_type, logging.info)
            params['image_name'] += "-error"
            params['boot_once'] = "c"
            vm.create(params=params)
            virttest.utils_test.run_virt_sub_test(test, params, env,
                                                  params.get("sub_type"))


@error.context_aware
def run_file_transfer(test, params, env):
    """
    Transfer a file back and forth between host and guest.

    1) Boot up a VM.
    2) Create a large file by dd on host.
    3) Copy this file from host to guest.
    4) Copy this file from guest to host.
    5) Check if file transfers ended good.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    error.context("Login to guest", logging.info)
    session = vm.wait_for_login(timeout=login_timeout)

    dir_name = test.tmpdir
    transfer_timeout = int(params.get("transfer_timeout"))
    transfer_type = params.get("transfer_type")
    tmp_dir = params.get("tmp_dir", "/tmp/")
    clean_cmd = params.get("clean_cmd", "rm -f")
    filesize = int(params.get("filesize", 4000))
    count = int(filesize / 10)
    if count == 0:
        count = 1

    host_path = os.path.join(dir_name, "tmp-%s" %
                             utils_misc.generate_random_string(8))
    host_path2 = host_path + ".2"
    cmd = "dd if=/dev/zero of=%s bs=10M count=%d" % (host_path, count)
    guest_path = (tmp_dir + "file_transfer-%s" %
                  utils_misc.generate_random_string(8))

    try:
        error.context("Creating %dMB file on host" % filesize, logging.info)
        utils.run(cmd)

        if transfer_type != "remote":
            raise error.TestError("Unknown test file transfer mode %s" %
                                  transfer_type)

        error.context("Transferring file host -> guest,"
                      " timeout: %ss" % transfer_timeout, logging.info)
        t_begin = time.time()
        vm.copy_files_to(host_path, guest_path, timeout=transfer_timeout)
        t_end = time.time()
        throughput = filesize / (t_end - t_begin)
        logging.info("File transfer host -> guest succeed, "
                     "estimated throughput: %.2fMB/s", throughput)

        error.context("Transferring file guest -> host,"
                      " timeout: %ss" % transfer_timeout, logging.info)
        t_begin = time.time()
        vm.copy_files_from(guest_path, host_path2, timeout=transfer_timeout)
        t_end = time.time()
        throughput = filesize / (t_end - t_begin)
        logging.info("File transfer guest -> host succeed, "
                     "estimated throughput: %.2fMB/s", throughput)

        error.context("Compare md5sum between original file and"
                      " transferred file", logging.info)
        if (utils.hash_file(host_path, method="md5") !=
                utils.hash_file(host_path2, method="md5")):
            raise error.TestFail("File changed after transfer host -> guest "
                                 "and guest -> host")

    finally:
        logging.info('Cleaning temp file on guest')
        try:
            session.cmd("%s %s" % (clean_cmd, guest_path))
        except aexpect.ShellError, detail:
            logging.warn("Could not remove temp files in guest: '%s'", detail)

        logging.info('Cleaning temp files on host')
        try:
            os.remove(host_path)
            os.remove(host_path2)
        except OSError:
            pass
        session.close()


def run_autotest(vm, session, control_path, timeout,
                 outputdir, params, copy_only=False):
    """
    Run an autotest control file inside a guest (linux only utility).

    :param vm: VM object.
    :param session: A shell session on the VM provided.
    :param control_path: A path to an autotest control file.
    :param timeout: Timeout under which the autotest control file must complete.
    :param outputdir: Path on host where we should copy the guest autotest
            results to.
    :param copy_only: If copy_only is True, copy the autotest to guest and
            return the command which need to run test on guest, without
            executing it.

    The following params is used by the migration
    :param params: Test params used in the migration test
    """
    def copy_if_hash_differs(vm, local_path, remote_path):
        """
        Copy a file to a guest if it doesn't exist or if its MD5sum differs.

        :param vm: VM object.
        :param local_path: Local path.
        :param remote_path: Remote path.

        :return: Whether the hash differs (True) or not (False).
        """
        hash_differs = False
        local_hash = utils.hash_file(local_path)
        basename = os.path.basename(local_path)
        output = session.cmd_output("md5sum %s" % remote_path)
        if "such file" in output:
            remote_hash = "0"
        elif output:
            remote_hash = output.split()[0]
        else:
            logging.warning("MD5 check for remote path %s did not return.",
                            remote_path)
            # Let's be a little more lenient here and see if it wasn't a
            # temporary problem
            remote_hash = "0"
        if remote_hash != local_hash:
            hash_differs = True
            logging.debug("Copying %s to guest "
                          "(remote hash: %s, local hash:%s)",
                          basename, remote_hash, local_hash)
            vm.copy_files_to(local_path, remote_path)
        return hash_differs

    def extract(vm, remote_path, dest_dir):
        """
        Extract the autotest .tar.bz2 file on the guest, ensuring the final
        destination path will be dest_dir.

        :param vm: VM object
        :param remote_path: Remote file path
        :param dest_dir: Destination dir for the contents
        """
        basename = os.path.basename(remote_path)
        logging.debug("Extracting %s on VM %s", basename, vm.name)
        session.cmd("rm -rf %s" % dest_dir, timeout=240)
        dirname = os.path.dirname(remote_path)
        session.cmd("cd %s" % dirname)
        session.cmd("mkdir -p %s" % os.path.dirname(dest_dir))
        e_cmd = "tar xjvf %s -C %s" % (basename, os.path.dirname(dest_dir))
        output = session.cmd(e_cmd, timeout=240)
        autotest_dirname = ""
        for line in output.splitlines()[1:]:
            autotest_dirname = line.split("/")[0]
            break
        if autotest_dirname != os.path.basename(dest_dir):
            session.cmd("cd %s" % os.path.dirname(dest_dir))
            session.cmd("mv %s %s" %
                        (autotest_dirname, os.path.basename(dest_dir)))

    def get_results(base_results_dir):
        """
        Copy autotest results present on the guest back to the host.
        """
        logging.debug("Trying to copy autotest results from guest")
        guest_results_dir = os.path.join(outputdir, "guest_autotest_results")
        try:
            os.mkdir(guest_results_dir)
        except OSError, detail:
            if detail.errno != errno.EEXIST:
                raise
        # result info tarball to host result dir
        session = vm.wait_for_login(timeout=360)
        results_dir = "%s/results/default" % base_results_dir
        results_tarball = "/tmp/results.tgz"
        compress_cmd = "cd %s && " % results_dir
        compress_cmd += "tar cjvf %s ./*" % results_tarball
        compress_cmd += " --exclude=*core*"
        compress_cmd += " --exclude=*crash*"
        session.cmd(compress_cmd, timeout=600)
        vm.copy_files_from(results_tarball, guest_results_dir)
        # cleanup autotest subprocess which not terminated, change PWD to
        # avoid current connection kill by fuser command;
        clean_cmd = "cd /tmp && fuser -k %s" % results_dir
        session.sendline(clean_cmd)
        session.cmd("rm -f %s" % results_tarball, timeout=240)
        results_tarball = os.path.basename(results_tarball)
        results_tarball = os.path.join(guest_results_dir, results_tarball)
        uncompress_cmd = "tar xjvf %s -C %s" % (results_tarball,
                                                guest_results_dir)
        utils.run(uncompress_cmd)
        utils.run("rm -f %s" % results_tarball)

    def get_results_summary():
        """
        Get the status of the tests that were executed on the guest.
        NOTE: This function depends on the results copied to host by
              get_results() function, so call get_results() first.
        """
        base_dir = os.path.join(outputdir, "guest_autotest_results")
        status_paths = glob.glob(os.path.join(base_dir, "*/status"))
        # for control files that do not use job.run_test()
        status_no_job = os.path.join(base_dir, "status")
        if os.path.exists(status_no_job):
            status_paths.append(status_no_job)
        status_path = " ".join(status_paths)

        try:
            output = utils.system_output("cat %s" % status_path)
        except error.CmdError, e:
            logging.error("Error getting guest autotest status file: %s", e)
            return None

        try:
            results = scan_results.parse_results(output)
            # Report test results
            logging.info("Results (test, status, duration, info):")
            for result in results:
                logging.info("\t %s", str(result))
            return results
        except Exception, e:
            logging.error("Error processing guest autotest results: %s", e)
            return None

    if not os.path.isfile(control_path):
        raise error.TestError("Invalid path to autotest control file: %s" %
                              control_path)

    migrate_background = params.get("migrate_background") == "yes"
    if migrate_background:
        mig_timeout = float(params.get("mig_timeout", "3600"))
        mig_protocol = params.get("migration_protocol", "tcp")

    compressed_autotest_path = "/tmp/autotest.tar.bz2"
    destination_autotest_path = "/usr/local/autotest"

    # To avoid problems, let's make the test use the current AUTODIR
    # (autotest client path) location
    from autotest.client import common
    autotest_path = os.path.dirname(common.__file__)
    autotest_local_path = os.path.join(autotest_path, 'autotest-local')
    single_dir_install = os.path.isfile(autotest_local_path)
    if not single_dir_install:
        autotest_local_path = os_dep.command('autotest-local')
    kernel_install_path = os.path.join(autotest_path, 'tests',
                                       'kernelinstall')
    kernel_install_present = os.path.isdir(kernel_install_path)

    autotest_basename = os.path.basename(autotest_path)
    autotest_parentdir = os.path.dirname(autotest_path)

    # tar the contents of bindir/autotest
    cmd = ("cd %s; tar cvjf %s %s/*" %
           (autotest_parentdir, compressed_autotest_path, autotest_basename))
    cmd += " --exclude=%s/results*" % autotest_basename
    cmd += " --exclude=%s/tmp" % autotest_basename
    cmd += " --exclude=%s/control*" % autotest_basename
    cmd += " --exclude=*.pyc"
    cmd += " --exclude=*.svn"
    cmd += " --exclude=*.git"
    cmd += " --exclude=%s/tests/virt/*" % autotest_basename
    utils.run(cmd)

    # Copy autotest.tar.bz2
    update = copy_if_hash_differs(vm, compressed_autotest_path,
                                  compressed_autotest_path)

    # Extract autotest.tar.bz2
    if update:
        extract(vm, compressed_autotest_path, destination_autotest_path)

    g_fd, g_path = tempfile.mkstemp(dir='/tmp/')
    aux_file = os.fdopen(g_fd, 'w')
    config = section_values(('CLIENT', 'COMMON'))
    config.set('CLIENT', 'output_dir', destination_autotest_path)
    config.set('COMMON', 'autotest_top_path', destination_autotest_path)
    destination_test_dir = os.path.join(destination_autotest_path, 'tests')
    config.set('COMMON', 'test_dir', destination_test_dir)
    destination_test_output_dir = os.path.join(destination_autotest_path,
                                               'results')
    config.set('COMMON', 'test_output_dir', destination_test_output_dir)
    config.write(aux_file)
    aux_file.close()
    global_config_guest = os.path.join(destination_autotest_path,
                                       'global_config.ini')
    vm.copy_files_to(g_path, global_config_guest)
    os.unlink(g_path)

    vm.copy_files_to(control_path,
                     os.path.join(destination_autotest_path, 'control'))

    if not single_dir_install:
        vm.copy_files_to(autotest_local_path,
                         os.path.join(destination_autotest_path,
                                      'autotest-local'))
    if not kernel_install_present:
        kernel_install_dir = os.path.join(virttest.data_dir.get_root_dir(),
                                          "shared", "deps",
                                          "test_kernel_install")
        kernel_install_dest = os.path.join(destination_autotest_path, 'tests',
                                           'kernelinstall')
        vm.copy_files_to(kernel_install_dir, kernel_install_dest)
        module_dir = os.path.dirname(virttest.__file__)
        utils_koji_file = os.path.join(module_dir, 'staging', 'utils_koji.py')
        vm.copy_files_to(utils_koji_file, kernel_install_dest)

    # Copy a non crippled boottool and make it executable
    boottool_path = os.path.join(virttest.data_dir.get_root_dir(),
                                 "shared", "deps", "boottool.py")
    boottool_dest = '/usr/local/autotest/tools/boottool.py'
    vm.copy_files_to(boottool_path, boottool_dest)
    session.cmd("chmod +x %s" % boottool_dest)

    # Clean the environment.
    session.cmd("cd %s" % destination_autotest_path)
    try:
        session.cmd("rm -f control.state")
        session.cmd("rm -rf results/*")
        session.cmd("rm -rf tmp/*")
    except aexpect.ShellError:
        pass

    # Check copy_only.
    if copy_only:
        return ("%s/autotest-local --verbose %s/control" %
                (destination_autotest_path, destination_autotest_path))

    # Run the test
    logging.info("Running autotest control file %s on guest, timeout %ss",
                 os.path.basename(control_path), timeout)
    try:
        bg = None
        try:
            logging.info("---------------- Test output ----------------")
            if migrate_background:
                mig_timeout = float(params.get("mig_timeout", "3600"))
                mig_protocol = params.get("migration_protocol", "tcp")

                bg = utils.InterruptedThread(session.cmd_output,
                                             kwargs={
                                                 'cmd': "./autotest control",
                                                 'timeout': timeout,
                                                 'print_func': logging.info})

                bg.start()

                while bg.isAlive():
                    logging.info("Autotest job did not end, start a round of "
                                 "migration")
                    vm.migrate(timeout=mig_timeout, protocol=mig_protocol)
            else:
                session.cmd_output("./autotest-local --verbose control",
                                   timeout=timeout,
                                   print_func=logging.info)
        finally:
            logging.info("------------- End of test output ------------")
            if migrate_background and bg:
                bg.join()
    except aexpect.ShellTimeoutError:
        if vm.is_alive():
            get_results(destination_autotest_path)
            get_results_summary()
            raise error.TestError("Timeout elapsed while waiting for job to "
                                  "complete")
        else:
            raise error.TestError("Autotest job on guest failed "
                                  "(VM terminated during job)")
    except aexpect.ShellProcessTerminatedError:
        get_results(destination_autotest_path)
        raise error.TestError("Autotest job on guest failed "
                              "(Remote session terminated during job)")

    get_results(destination_autotest_path)
    results = get_results_summary()

    if results is not None:
        # Make a list of FAIL/ERROR/ABORT results (make sure FAIL results appear
        # before ERROR results, and ERROR results appear before ABORT results)
        bad_results = [r[0] for r in results if r[1] == "FAIL"]
        bad_results += [r[0] for r in results if r[1] == "ERROR"]
        bad_results += [r[0] for r in results if r[1] == "ABORT"]

    # Fail the test if necessary
    if not results:
        raise error.TestFail("Autotest control file run did not produce any "
                             "recognizable results")
    if bad_results:
        if len(bad_results) == 1:
            e_msg = ("Test %s failed during control file execution" %
                     bad_results[0])
        else:
            e_msg = ("Tests %s failed during control file execution" %
                     " ".join(bad_results))
        raise error.TestFail(e_msg)


def get_loss_ratio(output):
    """
    Get the packet loss ratio from the output of ping
.
    :param output: Ping output.
    """
    try:
        return int(re.findall('(\d+)% packet loss', output)[0])
    except IndexError:
        logging.debug(output)
        return -1


def raw_ping(command, timeout, session, output_func):
    """
    Low-level ping command execution.

    :param command: Ping command.
    :param timeout: Timeout of the ping command.
    :param session: Local executon hint or session to execute the ping command.
    """
    if session is None:
        process = aexpect.run_bg(command, output_func=output_func,
                                 timeout=timeout)

        # Send SIGINT signal to notify the timeout of running ping process,
        # Because ping have the ability to catch the SIGINT signal so we can
        # always get the packet loss ratio even if timeout.
        if process.is_alive():
            utils_misc.kill_process_tree(process.get_pid(), signal.SIGINT)

        status = process.get_status()
        output = process.get_output()

        process.close()
        return status, output
    else:
        output = ""
        try:
            output = session.cmd_output(command, timeout=timeout,
                                        print_func=output_func)
        except aexpect.ShellTimeoutError:
            # Send ctrl+c (SIGINT) through ssh session
            session.send("\003")
            try:
                output2 = session.read_up_to_prompt(print_func=output_func)
                output += output2
            except aexpect.ExpectTimeoutError, e:
                output += e.output
                # We also need to use this session to query the return value
                session.send("\003")

        session.sendline(session.status_test_command)
        try:
            o2 = session.read_up_to_prompt()
        except aexpect.ExpectError:
            status = -1
        else:
            try:
                status = int(re.findall("\d+", o2)[0])
            except Exception:
                status = -1

        return status, output


def ping(dest=None, count=None, interval=None, interface=None,
         packetsize=None, ttl=None, hint=None, adaptive=False,
         broadcast=False, flood=False, timeout=0,
         output_func=logging.debug, session=None):
    """
    Wrapper of ping.

    :param dest: Destination address.
    :param count: Count of icmp packet.
    :param interval: Interval of two icmp echo request.
    :param interface: Specified interface of the source address.
    :param packetsize: Packet size of icmp.
    :param ttl: IP time to live.
    :param hint: Path mtu discovery hint.
    :param adaptive: Adaptive ping flag.
    :param broadcast: Broadcast ping flag.
    :param flood: Flood ping flag.
    :param timeout: Timeout for the ping command.
    :param output_func: Function used to log the result of ping.
    :param session: Local executon hint or session to execute the ping command.
    """
    if dest is not None:
        command = "ping %s " % dest
    else:
        command = "ping localhost "
    if count is not None:
        command += " -c %s" % count
    if interval is not None:
        command += " -i %s" % interval
    if interface is not None:
        command += " -I %s" % interface
    if packetsize is not None:
        command += " -s %s" % packetsize
    if ttl is not None:
        command += " -t %s" % ttl
    if hint is not None:
        command += " -M %s" % hint
    if adaptive:
        command += " -A"
    if broadcast:
        command += " -b"
    if flood:
        command += " -f -q"
        command = "sleep %s && kill -2 `pidof ping` & %s" % (timeout, command)
        output_func = None
        timeout += 1

    return raw_ping(command, timeout, session, output_func)


def run_virt_sub_test(test, params, env, sub_type=None, tag=None):
    """
    Call another test script in one test script.
    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    :param sub_type: Type of called test script.
    :param tag:    Tag for get the sub_test params
    """
    if sub_type is None:
        raise error.TestError("No sub test is found")
    virt_dir = os.path.dirname(test.virtdir)
    subtest_dir_virt = os.path.join(virt_dir, "tests")
    subtest_dir_specific = os.path.join(test.bindir, params.get('vm_type'),
                                        "tests")
    subtest_dir = None
    for d in [subtest_dir_specific, subtest_dir_virt]:
        module_path = os.path.join(d, "%s.py" % sub_type)
        if os.path.isfile(module_path):
            subtest_dir = d
            break
    if subtest_dir is None:
        raise error.TestError("Could not find test file %s.py "
                              "on either %s or %s directory" % (sub_type,
                                                                subtest_dir_specific, subtest_dir_virt))

    f, p, d = imp.find_module(sub_type, [subtest_dir])
    test_module = imp.load_module(sub_type, f, p, d)
    f.close()
    # Run the test function
    run_func = getattr(test_module, "run_%s" % sub_type)
    if tag is not None:
        params = params.object_params(tag)
    run_func(test, params, env)


def get_readable_cdroms(params, session):
    """
    Get the cdrom list which contain media in guest.

    :param params: Dictionary with the test parameters.
    :param session: A shell session on the VM provided.
    """
    get_cdrom_cmd = params.get("cdrom_get_cdrom_cmd")
    check_cdrom_patttern = params.get("cdrom_check_cdrom_pattern")
    o = session.get_command_output(get_cdrom_cmd)
    cdrom_list = re.findall(check_cdrom_patttern, o)
    logging.debug("Found cdroms on guest: %s" % cdrom_list)

    readable_cdroms = []
    test_cmd = params.get("cdrom_test_cmd")
    for d in cdrom_list:
        s, o = session.cmd_status_output(test_cmd % d)
        if s == 0:
            readable_cdroms.append(d)
            break

    if readable_cdroms:
        return readable_cdroms

    raise error.TestFail("Could not find a cdrom device with media inserted")


def pin_vm_threads(vm, node):
    """
    Pin VM threads to single cpu of a numa node
    :param vm: VM object
    :param node: NumaNode object
    """
    for i in vm.vhost_threads:
        logging.info("pin vhost thread(%s) to cpu(%s)" % (i, node.pin_cpu(i)))
    for i in vm.vcpu_threads:
        logging.info("pin vcpu thread(%s) to cpu(%s)" % (i, node.pin_cpu(i)))


def get_qemu_numa_status(numa_node_info, qemu_pid, debug=True):
    """
    Get the qemu process memory use status and the cpu list in each node.

    :param numa_node_info: Host numa node information
    :type numa_node_info: NumaInfo object
    :param qemu_pid: process id of qemu
    :type numa_node_info: string
    :param debug: Print the debug info or not
    :type debug: bool
    :return: memory and cpu list in each node
    :rtype: tuple
    """
    node_list = numa_node_info.online_nodes
    qemu_memory = []
    qemu_cpu = []
    cpus = utils_misc.get_pid_cpu(qemu_pid)
    for node_id in node_list:
        qemu_memory_status = utils_memory.read_from_numa_maps(qemu_pid,
                                                              "N%d" % node_id)
        memory = sum([int(_) for _ in qemu_memory_status.values()])
        qemu_memory.append(memory)
        cpu = [_ for _ in cpus if _ in numa_node_info.nodes[node_id].cpus]
        qemu_cpu.append(cpu)
        if debug:
            logging.debug("qemu-kvm process using %s pages and cpu %s in "
                          "node %s" % (memory, " ".join(cpu), node_id))
    return (qemu_memory, qemu_cpu)


def max_mem_map_node(host_numa_node, qemu_pid):
    """
    Find the numa node which qemu process memory maps to it the most.

    :param numa_node_info: Host numa node information
    :type numa_node_info: NumaInfo object
    :param qemu_pid: process id of qemu
    :type numa_node_info: string
    :return: The node id and how many pages are mapped to it
    :rtype: tuple
    """
    node_list = host_numa_node.online_nodes
    memory_status, _ = get_qemu_numa_status(host_numa_node, qemu_pid)
    node_map_most = 0
    memory_sz_map_most = 0
    for index in range(len(node_list)):
        if memory_sz_map_most < memory_status[index]:
            memory_sz_map_most = memory_status[index]
            node_map_most = node_list[index]
    return (node_map_most, memory_sz_map_most)


def service_setup(vm, session, directory):

    params = vm.get_params()
    rh_perf_envsetup_script = params.get("rh_perf_envsetup_script")
    rebooted = params.get("rebooted", "rebooted")

    if rh_perf_envsetup_script:
        src = os.path.join(directory, rh_perf_envsetup_script)
        vm.copy_files_to(src, "/tmp/rh_perf_envsetup.sh")
        logging.info("setup perf environment for host")
        commands.getoutput("bash %s host %s" % (src, rebooted))
        logging.info("setup perf environment for guest")
        session.cmd("bash /tmp/rh_perf_envsetup.sh guest %s" % rebooted)


def cmd_runner_monitor(vm, monitor_cmd, test_cmd, guest_path, timeout=300):
    """
    For record the env information such as cpu utilization, meminfo while
    run guest test in guest.
    @vm: Guest Object
    @monitor_cmd: monitor command running in backgroud
    @test_cmd: test suit run command
    @guest_path: path in guest to store the test result and monitor data
    @timeout: longest time for monitor running
    Return: tag the suffix of the results
    """
    def thread_kill(cmd, p_file):
        fd = shelve.open(p_file)
        o = commands.getoutput("pstree -p %s" % fd["pid"])
        tmp = re.split("\s+", cmd)[0]
        pid = re.findall("%s.(\d+)" % tmp, o)[0]
        s, o = commands.getstatusoutput("kill -9 %s" % pid)
        fd.close()
        return (s, o)

    def monitor_thread(m_cmd, p_file, r_file):
        fd = shelve.open(p_file)
        fd["pid"] = os.getpid()
        fd.close()
        os.system("%s &> %s" % (m_cmd, r_file))

    def test_thread(session, m_cmd, t_cmd, p_file, flag, timeout):
        flag.put(True)
        s, o = session.cmd_status_output(t_cmd, timeout)
        if s != 0:
            raise error.TestFail("Test failed or timeout: %s" % o)
        if not flag.empty():
            flag.get()
            thread_kill(m_cmd, p_file)

    kill_thread_flag = Queue(1)
    session = wait_for_login(vm, 0, 300, 0, 2)
    tag = vm.instance
    pid_file = "/tmp/monitor_pid_%s" % tag
    result_file = "/tmp/host_monitor_result_%s" % tag

    monitor = threading.Thread(target=monitor_thread, args=(monitor_cmd,
                                                            pid_file, result_file))
    test_runner = threading.Thread(target=test_thread, args=(session,
                                   monitor_cmd, test_cmd, pid_file,
                                   kill_thread_flag, timeout))
    monitor.start()
    test_runner.start()
    monitor.join(int(timeout))
    if not kill_thread_flag.empty():
        kill_thread_flag.get()
        thread_kill(monitor_cmd, pid_file)
        thread_kill("sh", pid_file)

    guest_result_file = "/tmp/guest_result_%s" % tag
    guest_monitor_result_file = "/tmp/guest_monitor_result_%s" % tag
    vm.copy_files_from(guest_path, guest_result_file)
    vm.copy_files_from("%s_monitor" % guest_path, guest_monitor_result_file)
    return tag


def aton(sr):
    """
    Transform a string to a number(include float and int). If the string is
    not in the form of number, just return false.

    @str: string to transfrom
    Return: float, int or False for failed transform
    """
    try:
        return int(sr)
    except ValueError:
        try:
            return float(sr)
        except ValueError:
            return False


def summary_up_result(result_file, ignore, row_head, column_mark):
    """
    Use to summary the monitor or other kinds of results. Now it calculates
    the average value for each item in the results. It fits to the records
    that are in matrix form.

    @result_file: files which need to calculate
    @ignore: pattern for the comment in results which need to through away
    @row_head: pattern for the items in row
    @column_mark: pattern for the first line in matrix which used to generate
    the items in column
    Return: A dictionary with the average value of results
    """
    head_flag = False
    result_dict = {}
    column_list = {}
    row_list = []
    fd = open(result_file, "r")
    for eachLine in fd:
        if len(re.findall(ignore, eachLine)) == 0:
            if len(re.findall(column_mark, eachLine)) != 0 and not head_flag:
                column = 0
                _, row, eachLine = re.split(row_head, eachLine)
                for i in re.split("\s+", eachLine):
                    if i:
                        result_dict[i] = {}
                        column_list[column] = i
                        column += 1
                head_flag = True
            elif len(re.findall(column_mark, eachLine)) == 0:
                column = 0
                _, row, eachLine = re.split(row_head, eachLine)
                row_flag = False
                for i in row_list:
                    if row == i:
                        row_flag = True
                if row_flag is False:
                    row_list.append(row)
                    for i in result_dict:
                        result_dict[i][row] = []
                for i in re.split("\s+", eachLine):
                    if i:
                        result_dict[column_list[column]][row].append(i)
                        column += 1
    fd.close()
    # Calculate the average value
    average_list = {}
    for i in column_list:
        average_list[column_list[i]] = {}
        for j in row_list:
            average_list[column_list[i]][j] = {}
            check = result_dict[column_list[i]][j][0]
            if aton(check) or aton(check) == 0.0:
                count = 0
                for k in result_dict[column_list[i]][j]:
                    count += aton(k)
                average_list[column_list[i]][j] = "%.2f" % (count /
                                                            len(result_dict[column_list[i]][j]))

    return average_list


def find_substring(string, pattern1, pattern2=None):
    """
    Return the match of pattern1 in string. Or return the match of pattern2
    if pattern is not matched.

    @string: string
    @pattern1: first pattern want to match in string, must set.
    @pattern2: second pattern, it will be used if pattern1 not match, optional.

    Return: Match substing or None
    """
    if not pattern1:
        logging.debug("pattern1: get empty string.")
        return None
    pattern = pattern1
    if pattern2:
        pattern += "|%s" % pattern2
    ret = re.findall(pattern, string)
    if not ret:
        logging.debug("Could not find matched string with pattern: %s",
                      pattern)
        return None
    return ret[0]


def get_driver_hardware_id(driver_path, mount_point="/tmp/mnt-virtio",
                           storage_path="/tmp/prewhql.iso",
                           re_hw_id="(PCI.{14,50})", run_cmd=True):
    """
    Get windows driver's hardware id from inf files.

    :param dirver: Configurable driver name.
    :param mount_point: Mount point for the driver storage
    :param storage_path: The path of the virtio driver storage
    :param re_hw_id: the pattern for getting hardware id from inf files
    :param run_cmd:  Use hardware id in windows cmd command or not

    Return: Windows driver's hardware id
    """
    if not os.path.exists(mount_point):
        os.mkdir(mount_point)

    if not os.path.ismount(mount_point):
        utils.system("mount %s %s -o loop" % (storage_path, mount_point),
                     timeout=60)
    driver_link = os.path.join(mount_point, driver_path)
    txt_file = ""
    try:
        txt_file = open(driver_link, "r")
        txt = txt_file.read()
        hwid = re.findall(re_hw_id, txt)[-1].rstrip()
        if run_cmd:
            hwid = '^&'.join(hwid.split('&'))
        txt_file.close()
        utils.system("umount %s" % mount_point)
        return hwid
    except Exception, e:
        logging.error("Fail to get hardware id with exception: %s" % e)
        if txt_file:
            txt_file.close()
        utils.system("umount %s" % mount_point, ignore_status=True)
        return ""


def recovery_from_snapshot(vmxml, snap_name_list):
    """
    Do recovery after snapshot

    :param vmxml: VMXML object with recovery xml in it
    :param snap_name_list: The list of snapshot name you want to remove
    """
    vmxml.undefine("--snapshots-metadata")
    vmxml.define()
    logging.debug("xml is %s", vmxml.dict_get('xml'))

    # Delete useless disk snapshot file
    dom_xml = vmxml.dict_get('xml')
    disk_path = dom_xml.find('devices/disk/source').get('file')
    for name in snap_name_list:
        snap_disk_path = disk_path.split(".")[0] + "." + name
        os.system('rm -f %s' % snap_disk_path)


class BackgroundTest(object):

    """
    This class would run a test in background through a dedicated thread.
    """

    def __init__(self, func, params, kwargs={}):
        """
        Initialize the object and set a few attributes.
        """
        self.thread = threading.Thread(target=self.launch,
                                       args=(func, params, kwargs))
        self.exception = None

    def launch(self, func, params, kwargs):
        """
        Catch and record the exception.
        """
        try:
            func(*params, **kwargs)
        except Exception, e:
            self.exception = e

    def start(self):
        """
        Run func(params) in a dedicated thread
        """
        self.thread.start()

    def join(self, timeout=600):
        """
        Wait for the join of thread and raise its exception if any.
        """
        self.thread.join(timeout)
        # pylint: disable=E0702
        if self.exception:
            raise self.exception

    def is_alive(self):
        """
        Check whether the test is still alive.
        """
        return self.thread.isAlive()


class GuestSuspend(object):

    """
    Suspend guest, supports both Linux and Windows.

    """
    SUSPEND_TYPE_MEM = "mem"
    SUSPEND_TYPE_DISK = "disk"

    def __init__(self, params, vm):
        if not params or not vm:
            raise error.TestError("Missing 'params' or 'vm' parameters")

        self._open_session_list = []
        self.vm = vm
        self.params = params
        self.login_timeout = float(self.params.get("login_timeout", 360))
        self.services_up_timeout = float(self.params.get("services_up_timeout",
                                                         30))
        self.os_type = self.params.get("os_type")

    def _get_session(self):
        self.vm.verify_alive()
        session = self.vm.wait_for_login(timeout=self.login_timeout)
        return session

    def _session_cmd_close(self, session, cmd):
        try:
            return session.cmd_status_output(cmd)
        finally:
            try:
                session.close()
            except Exception:
                pass

    def _cleanup_open_session(self):
        try:
            for s in self._open_session_list:
                if s:
                    s.close()
        except Exception:
            pass

    @error.context_aware
    def setup_bg_program(self, **args):
        """
        Start up a program as a flag in guest.
        """
        suspend_bg_program_setup_cmd = args.get("suspend_bg_program_setup_cmd")

        error.context("Run a background program as a flag", logging.info)
        session = self._get_session()
        self._open_session_list.append(session)

        logging.debug("Waiting all services in guest are fully started.")
        time.sleep(self.services_up_timeout)

        session.sendline(suspend_bg_program_setup_cmd)

    @error.context_aware
    def check_bg_program(self, **args):
        """
        Make sure the background program is running as expected
        """
        suspend_bg_program_chk_cmd = args.get("suspend_bg_program_chk_cmd")

        error.context("Verify background program is running", logging.info)
        session = self._get_session()
        s, _ = self._session_cmd_close(session, suspend_bg_program_chk_cmd)
        if s:
            raise error.TestFail("Background program is dead. Suspend failed.")

    @error.context_aware
    def kill_bg_program(self, **args):
        error.context("Kill background program after resume")
        suspend_bg_program_kill_cmd = args.get("suspend_bg_program_kill_cmd")

        try:
            session = self._get_session()
            self._session_cmd_close(session, suspend_bg_program_kill_cmd)
        except Exception, e:
            logging.warn("Could not stop background program: '%s'", e)
            pass

    @error.context_aware
    def _check_guest_suspend_log(self, **args):
        error.context("Check whether guest supports suspend",
                      logging.info)
        suspend_support_chk_cmd = args.get("suspend_support_chk_cmd")

        session = self._get_session()
        s, o = self._session_cmd_close(session, suspend_support_chk_cmd)

        return s, o

    def verify_guest_support_suspend(self, **args):
        s, _ = self._check_guest_suspend_log(**args)
        if s:
            raise error.TestError("Guest doesn't support suspend.")

    @error.context_aware
    def start_suspend(self, **args):
        supend_cmd = args.get("suspend_start_cmd")
        error.context("Start suspend [%s]" % (supend_cmd), logging.info)
        suspend_start_cmd = args.get("suspend_start_cmd")

        session = self._get_session()
        self._open_session_list.append(session)

        # Suspend to disk
        session.sendline(suspend_start_cmd)

    @error.context_aware
    def verify_guest_down(self, **args):
        # Make sure the VM goes down
        error.context("Wait for guest goes down after suspend")
        suspend_timeout = 240 + int(self.params.get("smp")) * 60
        if not utils_misc.wait_for(self.vm.is_dead, suspend_timeout, 2, 2):
            raise error.TestFail("VM refuses to go down. Suspend failed.")

    @error.context_aware
    def resume_guest_mem(self, **args):
        error.context("Resume suspended VM from memory")
        self.vm.monitor.system_wakeup()

    @error.context_aware
    def resume_guest_disk(self, **args):
        error.context("Resume suspended VM from disk")
        self.vm.create()

    @error.context_aware
    def verify_guest_up(self, **args):
        error.context("Verify guest system log", logging.info)
        suspend_log_chk_cmd = args.get("suspend_log_chk_cmd")

        session = self._get_session()
        s, o = self._session_cmd_close(session, suspend_log_chk_cmd)
        if s:
            raise error.TestError("Could not find suspend log. [%s]" % (o))

    @error.context_aware
    def action_before_suspend(self, **args):
        error.context("Actions before suspend")
        pass

    @error.context_aware
    def action_during_suspend(self, **args):
        error.context("Sleep a while before resuming guest", logging.info)

        time.sleep(10)
        if self.os_type == "windows":
            # Due to WinXP/2003 won't suspend immediately after issue S3 cmd,
            # delay 10~60 secs here, maybe there's a bug in windows os.
            logging.info("WinXP/2003 need more time to suspend, sleep 50s.")
            time.sleep(50)

    @error.context_aware
    def action_after_suspend(self, **args):
        error.context("Actions after suspend")
        pass


def cpus_parser(cpulist):
    """
    Parse a list of cpu list, its syntax is a comma separated list,
    with '-' for ranges and '^' denotes exclusive.
    :param cpulist: a list of physical CPU numbers
    """
    hyphens = []
    carets = []
    commas = []
    others = []

    if cpulist is None:
        return None

    else:
        if "," in cpulist:
            cpulist_list = re.split(",", cpulist)
            for cpulist in cpulist_list:
                if "-" in cpulist:
                    tmp = re.split("-", cpulist)
                    hyphens = hyphens + range(int(tmp[0]), int(tmp[-1]) + 1)
                elif "^" in cpulist:
                    tmp = re.split("\^", cpulist)[-1]
                    carets.append(int(tmp))
                else:
                    try:
                        commas.append(int(cpulist))
                    except ValueError:
                        logging.error("The cpulist has to be an "
                                      "integer. (%s)", cpulist)
        elif "-" in cpulist:
            tmp = re.split("-", cpulist)
            hyphens = range(int(tmp[0]), int(tmp[-1]) + 1)
        elif "^" in cpulist:
            tmp = re.split("^", cpulist)[-1]
            carets.append(int(tmp))
        else:
            try:
                others.append(int(cpulist))
                return others
            except ValueError:
                logging.error("The cpulist has to be an "
                              "integer. (%s)", cpulist)

        cpus_set = set(hyphens).union(set(commas)).difference(set(carets))

        return sorted(list(cpus_set))


def cpus_string_to_affinity_list(cpus_string, num_cpus):
    """
    Parse the cpus_string string to a affinity list.

    e.g
    host_cpu_count = 4
    0       -->     [y,-,-,-]
    0,1     -->     [y,y,-,-]
    0-2     -->     [y,y,y,-]
    0-2,^2  -->     [y,y,-,-]
    r       -->     [y,y,y,y]
    """
    # Check the input string.
    single_pattern = r"\d+"
    between_pattern = r"\d+-\d+"
    exclude_pattern = r"\^\d+"
    sub_pattern = r"(%s)|(%s)|(%s)" % (exclude_pattern,
                  single_pattern, between_pattern)
    pattern = r"^((%s),)*(%s)$" % (sub_pattern, sub_pattern)
    if not re.match(pattern, cpus_string):
        logging.debug("Cpus_string=%s is not a supported format for cpu_list."
                      % cpus_string)
    # Init a list for result.
    affinity = []
    for i in range(int(num_cpus)):
        affinity.append('-')
    # Letter 'r' means all cpus.
    if cpus_string == "r":
        for i in range(len(affinity)):
            affinity[i] = "y"
        return affinity
    # Split the string with ','.
    sub_cpus = cpus_string.split(",")
    # Parse each sub_cpus.
    for cpus in sub_cpus:
        if "-" in cpus:
            minmum = cpus.split("-")[0]
            maxmum = cpus.split("-")[-1]
            for i in range(int(minmum), int(maxmum) + 1):
                affinity[i] = "y"
        elif "^" in cpus:
            affinity[int(cpus.strip("^"))] = "-"
        else:
            affinity[int(cpus)] = "y"
    return affinity


def cpu_allowed_list_by_task(pid, tid):
    """
    Get the Cpus_allowed_list in status of task.
    """
    cmd = "cat /proc/%s/task/%s/status|grep Cpus_allowed_list:| awk '{print $2}'" % (pid, tid)
    result = utils.run(cmd, ignore_status=True)
    if result.exit_status:
        return None
    return result.stdout.strip()
