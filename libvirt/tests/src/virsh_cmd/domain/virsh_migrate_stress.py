import re
import logging
import threading
import time
from autotest.client import utils
from autotest.client.shared import error, utils_memory
from virttest import libvirt_vm, data_dir, utils_misc, virt_vm
from virttest import aexpect, remote
from virttest.libvirt_xml import vm_xml


# To get result in thread, using global parameters
# Result of virsh migrate command
global RET_MIGRATION
# A lock for threads
global RET_LOCK
# True means command executed successfully
RET_MIGRATION = True
RET_LOCK = threading.RLock()


def cleanup_dest(vm, srcuri, desturi):
    """
    Cleanup migrated vm on remote host.
    """
    vm.connect_uri = desturi
    if vm.exists():
        if vm.is_persistent():
            vm.undefine()
        if vm.is_alive():
            vm.destroy()
    # Set connect uri back to local uri
    vm.connect_uri = srcuri


def set_cpu_memory(vm_name, cpu, memory):
    """
    Change vms' cpu and memory.
    """
    vmxml = vm_xml.VMXML.new_from_dumpxml(vm_name)
    vmxml.vcpu = cpu
    # To avoid exceeded current memory
    vmxml.max_mem = memory
    vmxml.current_mem = memory
    logging.debug("VMXML info:\n%s", vmxml.get('xml'))
    vmxml.undefine()
    vmxml.define()


class StressError(Exception):
    pass


class HostStress(object):

    """class for stress tool on host"""

    def __init__(self, params):
        self.params = params
        self.link = self.params.get("download_link")
        self.md5sum = self.params.get("md5sum")
        self.tmp_dir = data_dir.get_download_dir()
        self.install_cmd = self.params.get("install_cmd") % self.tmp_dir
        self.config_cmd = self.params.get("config_cmd")
        self.vm_bytes = self.params.get("stress_vm_bytes", "128M")
        # One vm's memory size
        vm_memory = int(self.params.get("vm_memory", 1048576))
        # Memory needs to be reserved for vms.
        self.vm_reserved = len(self.params.get("vms").split()) * vm_memory
        # Set consumed memory for host stress tool
        self.count_vm_bytes()
        self.start_cmd = self.params.get("start_cmd")
        if re.search("--vm-bytes", self.start_cmd):
            self.start_cmd = self.start_cmd % self.vm_bytes
        self.stop_cmd = self.params.get("stop_cmd")
        self.check_cmd = self.params.get("check_cmd")
        self.app_check_cmd = self.params.get("app_check_cmd")

    def count_vm_bytes(self):
        mem_total = utils_memory.memtotal()
        if self.vm_bytes == "half":
            self.vm_bytes = (mem_total - self.vm_reserved) / 2
        elif self.vm_bytes == "shortage":
            self.vm_bytes = mem_total - self.vm_reserved + 524288

    @error.context_aware
    def install_stress_app(self):
        error.context("install stress app on host")
        output = utils.run(self.app_check_cmd, ignore_status=True).stdout
        installed = re.search("Usage:", output)
        if installed:
            logging.debug("Stress has been installed.")
            return

        try:
            pkg = utils.unmap_url_cache(self.tmp_dir, self.link, self.md5sum)
        except Exception, detail:
            raise StressError(str(detail))
        result = utils.run(self.install_cmd, timeout=60, ignore_status=True)
        if result.exit_status != 0:
            raise StressError("Fail to install stress app(%s)" % result.stdout)

    @error.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memory stress in guest;
        """
        self.install_stress_app()
        if self.app_running():
            logging.info("Stress app is already running.")
            return
        error.context("launch stress app on host", logging.info)
        utils.run(self.start_cmd, ignore_status=True)
        logging.info("Command: %s", self.start_cmd)
        running = utils_misc.wait_for(self.app_running, first=0.5, timeout=60)
        if not running:
            raise StressError("stress app isn't running")

    @error.context_aware
    def unload_stress(self):
        """
        stop stress app
        """
        def _unload_stress():
            utils.run(self.stop_cmd, ignore_status=True)
            if not self.app_running():
                return True
            return False

        error.context("stop stress app on host", logging.info)
        utils_misc.wait_for(_unload_stress, first=2.0,
                            text="wait stress app quit", step=1.0, timeout=60)

    def app_running(self):
        """
        check stress app really run in background;
        """
        result = utils.run(self.check_cmd, timeout=60, ignore_status=True)
        return result.exit_status == 0


class VMStress(object):

    """class for stress tool in vm."""

    def __init__(self, vm):
        self.vm = vm
        self.params = vm.params
        self.link = self.params.get("stress_download_link")
        self.md5sum = self.params.get("stress_md5sum")
        self.tmp_dir = self.params.get("stress_tmp_dir")
        self.install_cmd = self.params.get("stress_install_cmd") % self.tmp_dir
        self.config_cmd = self.params.get("stress_config_cmd")
        self.vm_bytes = self.params.get("stress_vm_bytes", "128M")
        self.start_cmd = self.params.get("stress_start_cmd")
        if re.search("--vm-bytes", self.start_cmd):
            self.start_cmd = self.start_cmd % self.vm_bytes
        self.stop_cmd = self.params.get("stress_stop_cmd")
        self.check_cmd = self.params.get("stress_check_cmd")
        self.app_check_cmd = self.params.get("stress_app_check_cmd")

    def get_session(self):
        try:
            session = self.vm.wait_for_login()
            return session
        except aexpect.ShellError, detail:
            raise StressError("Login %s failed:\n%s", self.vm.name, detail)

    @error.context_aware
    def install_stress_app(self):
        error.context("install stress app in guest")
        session = self.get_session()
        _, output = session.cmd_status_output(self.app_check_cmd)
        installed = re.search("Usage:", output)
        if installed:
            logging.debug("Stress has been installed.")
            return

        try:
            pkg = utils.unmap_url_cache(data_dir.get_download_dir(),
                                        self.link, self.md5sum)
        except Exception, detail:
            raise StressError(str(detail))
        self.vm.copy_files_to(pkg, self.tmp_dir)
        status, output = session.cmd_status_output(self.install_cmd,
                                                   timeout=60)
        if status:
            raise StressError("Fail to install stress app(%s)" % output)

    @error.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memory stress in guest;
        """
        self.install_stress_app()
        if self.app_running():
            logging.info("Stress app is already running.")
            return
        session = self.get_session()
        error.context("launch stress app in guest", logging.info)
        session.sendline(self.start_cmd)
        logging.info("Command: %s", self.start_cmd)
        running = utils_misc.wait_for(self.app_running, first=0.5, timeout=60)
        if not running:
            raise StressError("stress app isn't running")

    @error.context_aware
    def unload_stress(self):
        """
        stop stress app
        """
        def _unload_stress():
            session = self.get_session()
            session.sendline(self.stop_cmd)
            if not self.app_running():
                return True
            return False

        error.context("stop stress app in guest", logging.info)
        utils_misc.wait_for(_unload_stress, first=2.0,
                            text="wait stress app quit", step=1.0, timeout=60)

    def app_running(self):
        """
        check stress app really run in background;
        """
        session = self.get_session()
        status = session.cmd_status(self.check_cmd, timeout=60)
        return status == 0


def thread_func_migration(vm, desturi):
    """
    Thread for virsh migrate command.

    :param vm: A libvirt vm instance(local or remote).
    :param desturi: remote host uri.
    """
    # Judge result for main_func with a global variable.
    global RET_MIGRATION
    global RET_LOCK
    # Migrate the domain.
    try:
        vm.migrate(desturi, ignore_status=False, debug=True)
    except error.CmdError, detail:
        logging.error("Migration to %s failed:\n%s", desturi, detail)
        RET_LOCK.acquire()
        RET_MIGRATION = False
        RET_LOCK.release()


def do_migration(vms, srcuri, desturi, load_vms, stress_type,
                 migration_type, thread_timeout=60):
    """
    Migrate vms with stress.

    :param vms: migrated vms.
    :param load_vms: provided for stress.
    """
    global RET_MIGRATION
    fail_info = []
    for vm in vms:
        if stress_type == "load_vm_booting":
            if len(load_vms):
                try:
                    if not load_vms[0].is_alive:
                        load_vms[0].start()
                except virt_vm.VMStartError:
                    fail_info.append("Start load vm %s failed." % vm.name)
                    break
            else:
                logging.warn("No load vm provided.")
        elif stress_type == "load_vms_booting":
            for load_vm in load_vms:
                try:
                    if not load_vm.is_alive:
                        load_vm.start()
                except virt_vm.VMStartError:
                    fail_info.append("Start load vm %s failed." % vm.name)
                    break
        elif stress_type == "stress_in_vms":
            try:
                vstress = VMStress(vm)
                vstress.load_stress()
            except StressError, detail:
                fail_info.append("Launch stress failed:%s" % detail)
                break
        elif stress_type == "stress_on_host":
            try:
                hstress = HostStress(vm.params)
                hstress.load_stress()
            except StressError, detail:
                fail_info.append("Launch stress failed:%s" % detail)
                break
        elif stress_type == "migration_vms_booting":
            try:
                vm.start()
            except virt_vm.VMStartError:
                fail_info.append("Start migration vms failed.")
                break

    if migration_type == "orderly":
        for vm in vms:
            migration_thread = threading.Thread(target=thread_func_migration,
                                                args=(vm, desturi))
            migration_thread.start()
            migration_thread.join(thread_timeout)
            if migration_thread.isAlive():
                logging.error("Migrate %s timeout.", migration_thread)
                RET_LOCK.acquire()
                RET_MIGRATION = False
                RET_LOCK.release()
    elif migration_type == "cross":
        # Migrate a vm to remote first,
        # then migrate another to remote with the first vm back
        vm_remote = vms.pop()
        for vm in vms:
            thread1 = threading.Thread(target=thread_func_migration,
                                       args=(vm_remote, srcuri))
            thread2 = threading.Thread(target=thread_func_migration,
                                       args=(vm, desturi))
            thread1.start()
            thread2.start()
            thread1.join(thread_timeout)
            thread2.join(thread_timeout)
            vm_remote = vm
            if thread1.isAlive() or thread1.isAlive():
                logging.error("Cross migrate timeout.")
                RET_LOCK.acquire()
                RET_MIGRATION = False
                RET_LOCK.release()
    elif migration_type == "simultaneous":
        migration_threads = []
        for vm in vms:
            migration_threads.append(threading.Thread(
                                     target=thread_func_migration,
                                     args=(vm, desturi)))
        # let all migration going first
        for thread in migration_threads:
            thread.start()

        # listen threads until they end
        for thread in migration_threads:
            thread.join(thread_timeout)
            if thread.isAlive():
                logging.error("Migrate %s timeout.", thread)
                RET_LOCK.acquire()
                RET_MIGRATION = False
                RET_LOCK.release()

    # Clean up loads
    for load_vm in load_vms:
        load_vm.destroy()
    if stress_type == "stress_on_host":
        hstress.unload_stress()

    if len(fail_info):
        logging.warning("Add stress for migration failed:%s", fail_info)
    if not RET_MIGRATION:
        raise error.TestFail()


def check_dest_vm_network(vm, remote_host, username, password,
                          shell_prompt):
    """
    Ping migrated vms on remote host.
    """
    session = remote.remote_login("ssh", remote_host, 22, username,
                                  password, shell_prompt)
    # Timeout to wait vm's network
    logging.debug("Getting vm's IP...")
    timeout = 60
    while timeout > 0:
        try:
            ping_cmd = "ping -c 4 %s" % vm.get_address()
            break
        except virt_vm.VMAddressError:
            time.sleep(5)
            timeout -= 5
    if timeout <= 0:
        raise error.TestFail("Can not get remote vm's IP.")
    status, output = session.cmd_status_output(ping_cmd)
    if status:
        raise error.TestFail("Check %s IP failed:%s" % (vm.name, output))


def run_virsh_migrate_stress(test, params, env):
    """
    Test migration under stress.
    """
    vm_names = params.get("migration_vms").split()
    if len(vm_names) < 2:
        raise error.TestNAError("Provide enough vms for migration first.")

    # Migrated vms' instance
    vms = []
    for vm_name in vm_names:
        vms.append(libvirt_vm.VM(vm_name, params, test.bindir,
                                 env.get("address_cache")))

    load_vm_names = params.get("load_vms").split()
    # vms for load
    load_vms = []
    for vm_name in load_vm_names:
        load_vms.append(libvirt_vm.VM(vm_name, params, test.bindir,
                        env.get("address_cache")))

    cpu = int(params.get("smp", 1))
    memory = int(params.get("mem")) * 1024
    stress_type = params.get("migration_stress_type")
    migration_type = params.get("migration_type")
    start_migration_vms = "yes" == params.get("start_migration_vms", "yes")
    dest_uri = params.get("migrate_dest_uri", "qemu+ssh://EXAMPLE/system")
    src_uri = params.get("migrate_src_uri", "qemu+ssh://EXAMPLE/system")
    thread_timeout = int(params.get("thread_timeout", 120))
    remote_host = params.get("remote_ip")
    username = params.get("remote_user", "root")
    password = params.get("remote_pwd")
    prompt = params.get("shell_prompt", r"[\#\$]")

    for vm in vms:
        # Keep vm dead for edit
        if vm.is_alive():
            vm.destroy()
        set_cpu_memory(vm.name, cpu, memory)

    try:
        if start_migration_vms:
            for vm in vms:
                vm.start()
                vm.wait_for_login()
                # TODO: recover vm if start failed?
        # TODO: set ssh-autologin automatically
        do_migration(vms, src_uri, dest_uri, load_vms, stress_type,
                     migration_type, thread_timeout)
        # Check network of vms on destination
        for vm in vms:
            check_dest_vm_network(vm, remote_host, username, password, prompt)
    finally:
        for vm in vms:
            cleanup_dest(vm, None, dest_uri)
            if vm.is_alive():
                vm.destroy()
