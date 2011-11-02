"""
High-level KVM test utility functions.

This module is meant to reduce code size by performing common test procedures.
Generally, code here should look like test code.
More specifically:
    - Functions in this module should raise exceptions if things go wrong
      (unlike functions in kvm_utils.py and kvm_vm.py which report failure via
      their returned values).
    - Functions in this module may use logging.info(), in addition to
      logging.debug() and logging.error(), to log messages the user may be
      interested in (unlike kvm_utils.py and kvm_vm.py which use
      logging.debug() for anything that isn't an error).
    - Functions in this module typically use functions and classes from
      lower-level modules (e.g. kvm_utils.py, kvm_vm.py, kvm_subprocess.py).
    - Functions in this module should not be used by lower-level modules.
    - Functions in this module should be used in the right context.
      For example, a function should not be used where it may display
      misleading or inaccurate info or debug messages.

@copyright: 2008-2009 Red Hat Inc.
"""

import time, os, logging, re, signal, threading, shelve, commands, string, imp
from Queue import Queue
from distutils import version
from autotest_lib.client.common_lib import error
from autotest_lib.client.bin import utils
from autotest_lib.client.tools import scan_results
import aexpect, virt_utils, virt_vm


def get_living_vm(env, vm_name):
    """
    Get a VM object from the environment and make sure it's alive.

    @param env: Dictionary with test environment.
    @param vm_name: Name of the desired VM object.
    @return: A VM object.
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

    @param vm: VM object.
    @param nic_index: Index of NIC to access in the VM.
    @param timeout: Time to wait before giving up.
    @param serial: Whether to use a serial connection instead of a remote
            (ssh, rss) one.

    @return: A shell session object.
    """
    login_type = 'remote'
    end_time = time.time() + timeout
    session = None
    if serial:
        login_type = 'serial'
        logging.info("Trying to log into guest %s using serial connection,"
                     " timeout %ds", vm.name, timeout)
        time.sleep(start)
        while time.time() < end_time:
            try:
                session = vm.serial_login()
                break
            except virt_utils.LoginError, e:
                logging.debug(e)
            time.sleep(step)
    else:
        type = 'remote'
        logging.info("Trying to log into guest %s using remote connection,"
                     " timeout %ds", vm.name, timeout)
        time.sleep(start)
        while time.time() < end_time:
            try:
                session = vm.login(nic_index=nic_index)
                break
            except (virt_utils.LoginError, virt_vm.VMError), e:
                logging.debug(e)
            time.sleep(step)
        if not session and vm.get_params().get("try_serial_login") == "yes":
            login_type = "serial"
            logging.info("Remote login failed, trying to login '%s' with "
                         "serial, timeout %ds", vm.name, timeout)
            time.sleep(start)
            while time.time() < end_time:
                try:
                    session = vm.serial_login()
                    break
                except virt_utils.LoginError, e:
                    logging.debug(e)
                time.sleep(step)
    if not session:
        raise error.TestFail("Could not log into guest %s using %s connection" %
                             (vm.name, login_type))
    logging.info("Logged into guest %s using %s connection", vm.name,
                 login_type)
    return session


def reboot(vm, session, method="shell", sleep_before_reset=10, nic_index=0,
           timeout=240):
    """
    Reboot the VM and wait for it to come back up by trying to log in until
    timeout expires.

    @param vm: VM object.
    @param session: A shell session object.
    @param method: Reboot method.  Can be "shell" (send a shell reboot
            command) or "system_reset" (send a system_reset monitor command).
    @param nic_index: Index of NIC to access in the VM, when logging in after
            rebooting.
    @param timeout: Time to wait before giving up (after rebooting).
    @return: A new shell session object.
    """
    if method == "shell":
        # Send a reboot command to the guest's shell
        session.sendline(vm.get_params().get("reboot_command"))
        logging.info("Reboot command sent. Waiting for guest to go down...")
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
                     "go down...")
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
    if not virt_utils.wait_for(lambda: not session.is_responsive(),
                              timeout, 0, 1):
        raise error.TestFail("Guest refuses to go down")
    session.close()

    # Try logging into the guest until timeout expires
    logging.info("Guest is down. Waiting for it to go up again, timeout %ds",
                 timeout)
    session = vm.wait_for_login(nic_index, timeout=timeout)
    logging.info("Guest is up again")
    return session

def update_boot_option(vm, args_removed=None, args_added=None,
                       need_reboot=True):
    """
    Update guest default kernel option.
    """
    if re.findall("win", vm.params.get("guest_name"), re.I):
        # this function is only for linux, if we need to change
        # windows guest's boot option, we can use a function like:
        # update_win_bootloader(args_removed, args_added, reboot)
        # (this function is not implement.)
        # here we just:
        return

    login_timeout = int(vm.params.get("login_timeout"))
    session = vm.wait_for_login(timeout=login_timeout)

    logging.info("Update the kernel cmdline ...")
    cmd = "grubby --update-kernel=`grubby --default-kernel` "
    if args_removed:
        cmd += '--remove-args="%s" ' % args_removed
    if args_added:
        cmd += '--args="%s"' % args_added
    s, o = session.cmd_status_output(cmd)
    if s != 0:
        logging.error(o)
        raise error.TestError("Fail to modify the kernel cmdline")

    if need_reboot:
        logging.info("Rebooting ...")
        vm.reboot(session=session, timeout=login_timeout)

def migrate(vm, env=None, mig_timeout=3600, mig_protocol="tcp",
            mig_cancel=False, offline=False, stable_check=False,
            clean=False, save_path=None, dest_host='localhost', mig_port=None):
    """
    Migrate a VM locally and re-register it in the environment.

    @param vm: The VM to migrate.
    @param env: The environment dictionary.  If omitted, the migrated VM will
            not be registered.
    @param mig_timeout: timeout value for migration.
    @param mig_protocol: migration protocol
    @param mig_cancel: Test migrate_cancel or not when protocol is tcp.
    @param dest_host: Destination host (defaults to 'localhost').
    @param mig_port: Port that will be used for migration.
    @return: The post-migration VM, in case of same host migration, True in
            case of multi-host migration.
    """
    def mig_finished():
        try:
            o = vm.monitor.info("migrate")
            logging.debug("%s", o)
            if isinstance(o, str):
                return "status: active" not in o
            else:
                return o.get("status") != "active"
        except:
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
        if not virt_utils.wait_for(mig_finished, mig_timeout, 2, 2,
                                  "Waiting for migration to finish..."):
            raise error.TestFail("Timeout expired while waiting for migration "
                                 "to finish")

    if dest_host == 'localhost':
        dest_vm = vm.clone()

    if (dest_host == 'localhost') and stable_check:
        # Pause the dest vm after creation
        dest_vm.params['extra_params'] = (dest_vm.params.get('extra_params','')
                                          + ' -S')

    if dest_host == 'localhost':
        dest_vm.create(migration_mode=mig_protocol, mac_source=vm)

    try:
        try:
            if mig_protocol == "tcp":
                if dest_host == 'localhost':
                    uri = "tcp:localhost:%d" % dest_vm.migration_port
                else:
                    uri = 'tcp:%s:%d' % (dest_host, mig_port)
            elif mig_protocol == "unix":
                uri = "unix:%s" % dest_vm.migration_file
            elif mig_protocol == "exec":
                uri = 'exec:nc localhost %s' % dest_vm.migration_port

            if offline:
                vm.monitor.cmd("stop")
            vm.monitor.migrate(uri)

            if mig_cancel:
                time.sleep(2)
                vm.monitor.cmd("migrate_cancel")
                if not virt_utils.wait_for(mig_cancelled, 60, 2, 2,
                                          "Waiting for migration "
                                          "cancellation"):
                    raise error.TestFail("Failed to cancel migration")
                if offline:
                    vm.monitor.cmd("cont")
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
                    dest_vm.monitor.cmd("cont")
        except:
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
        raise error.TestFail("Migration end with stauts: %s" % status)

    if dest_host == 'localhost':
        if "paused" in dest_vm.monitor.info("status"):
            logging.debug("Destination VM is paused, resuming it...")
            dest_vm.monitor.cmd("cont")

    # Kill the source VM
    vm.destroy(gracefully=False, free_mac_addresses=False)

    # Replace the source VM with the new cloned VM
    if (dest_host == 'localhost') and (env is not None):
        env.register_vm(vm.name, dest_vm)

    # Return the new cloned VM
    if dest_host == 'localhost':
        return dest_vm
    else:
        return vm


def stop_windows_service(session, service, timeout=120):
    """
    Stop a Windows service using sc.
    If the service is already stopped or is not installed, do nothing.

    @param service: The name of the service
    @param timeout: Time duration to wait for service to stop
    @raise error.TestError: Raised if the service can't be stopped
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

    @param service: The name of the service
    @param timeout: Time duration to wait for service to start
    @raise error.TestError: Raised if the service can't be started
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

def get_time(session, time_command, time_filter_re, time_format):
    """
    Return the host time and guest time.  If the guest time cannot be fetched
    a TestError exception is raised.

    Note that the shell session should be ready to receive commands
    (i.e. should "display" a command prompt and should be done with all
    previous commands).

    Add ntp service way to get the time of guest. In this method, host_time is
    the time of ntp server.

    @param session: A shell session.
    @param time_command: Command to issue to get the current guest time.
    @param time_filter_re: Regex filter to apply on the output of
            time_command in order to get the current time.
    @param time_format: Format string to pass to time.strptime() with the
            result of the regex filter.
    @return: A tuple containing the host time and guest time.
    """
    if len(re.findall("ntpdate|w32tm", time_command)) == 0:
        host_time = time.time()
        s = session.cmd_output(time_command)

        try:
            s = re.findall(time_filter_re, s)[0]
        except IndexError:
            logging.debug("The time string from guest is:\n%s", s)
            raise error.TestError("The time string from guest is unexpected.")
        except Exception, e:
            logging.debug("(time_filter_re, time_string): (%s, %s)",
                          time_filter_re, s)
            raise e

        guest_time = time.mktime(time.strptime(s, time_format))
    else:
        o = session.cmd(time_command)
        if re.match('ntpdate', time_command):
            offset = re.findall('offset (.*) sec', o)[0]
            host_main, host_mantissa = re.findall(time_filter_re, o)[0]
            host_time = (time.mktime(time.strptime(host_main, time_format)) +
                         float("0.%s" % host_mantissa))
            guest_time = host_time - float(offset)
        else:
            guest_time =  re.findall(time_filter_re, o)[0]
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

    return (host_time, guest_time)

def dump_command_output(session, command, file, timeout=30.0,
                        internal_timeout=1.0, print_func=None):
    """
    @param session: a saved communication between host and guest.
    @param command: will running in guest side.
    @param file: redirect command output to the specify file
    @param timeout: the duration (in seconds) to wait until a match is found.
    @param internal_timeout: the timeout to pass to read_nonblocking.
    @param print_func: a function to be used to print the data being read.
    @return: Command output(string).
    """

    (status, output) = session.get_command_status_output(command, timeout,
                                                internal_timeout, print_func)
    if status != 0:
        raise error.TestError("Failed to run command %s in guest." % command)
    try:
        f = open(file, "w")
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

    @param atest_basedir: base dir of autotest/cli/atest
    @param cmd: command to fix.
    @param ip: ip of the autotest server to add to the command.
    """
    cmd = os.path.join(atest_basedir, cmd)
    return ''.join([cmd, " -w ", ip])


def get_svr_tm_lst(session, cmd, timeout=1200):
    """
    get the test machine (IP) list in the autotest server.

    @param session: session to the autotest server.
    @param cmd: command to get the list.
    """
    (s, o)= session.get_command_status_output(cmd, timeout=timeout)
    if s != 0:
        raise error.TestError("Cannot get test machine list info.")

    # since we just need to get the ip address from the output,
    # we do not need a general ip filter here.
    return re.findall("\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", o)


def get_svr_session(ip, port="22", usrname="root", passwd="123456", prompt=""):
    """
    @param ip: IP address of the server.
    @param port: the port for remote session.
    @param usrname: user name for remote login.
    @param passwd: password.
    @param prompt: shell/session prompt for the connection.
    """
    session = virt_utils.remote_login("ssh", ip, port, usrname, passwd, prompt)
    if not session:
        raise error.TestError("Failed to login to the autotest server.")

    return session


def get_memory_info(lvms):
    """
    Get memory information from host and guests in format:
    Host: memfree = XXXM; Guests memsh = {XXX,XXX,...}

    @params lvms: List of VM objects
    @return: String with memory info report
    """
    if not isinstance(lvms, list):
        raise error.TestError("Invalid list passed to get_stat: %s " % lvms)

    try:
        meminfo = "Host: memfree = "
        meminfo += str(int(utils.freememtotal()) / 1024) + "M; "
        meminfo += "swapfree = "
        mf = int(utils.read_from_meminfo("SwapFree")) / 1024
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


def run_autotest(vm, session, control_path, timeout, outputdir, params,
                 kvm_test=False):
    """
    Run an autotest control file inside a guest (linux only utility).
    This function can start autotest on host or guest.

    @param vm: machine object, can be VM, RemoteVM, RemoteHost.
    @param session: A shell session on the VM provided.
    @param control_path: A path to an autotest control file.
    @param timeout: Timeout under which the autotest control file must complete.
    @param outputdir: Path on host where we should copy the guest autotest
            results to.
    @param kvm_test: whether include kvm test files in autotest package.

    The following params is used by the migration
    @param params: Test params used in the migration test
    """
    def copy_if_hash_differs(vm, local_path, remote_path):
        """
        Copy a file to a guest if it doesn't exist or if its MD5sum differs.

        @param vm: VM object.
        @param local_path: Local path.
        @param remote_path: Remote path.
        """
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
            logging.debug("Copying %s to guest", basename)
            vm.copy_files_to(local_path, remote_path)


    def extract(vm, remote_path, dest_dir="."):
        """
        Extract a .tar.bz2 file on the guest.

        @param vm: VM object
        @param remote_path: Remote file path
        @param dest_dir: Destination dir for the contents
        """
        basename = os.path.basename(remote_path)
        logging.info("Extracting %s...", basename)
        e_cmd = "tar xjvf %s -C %s" % (remote_path, dest_dir)
        session.cmd(e_cmd, timeout=120)


    def generate_test_cfg(params):
        guest_name = params.get("guest_name")
        guest_name = '-'.join(guest_name.split('-')[0:-1])
        if guest_name == '':
            guest_name = params.get("guest_name")

        drive_format = params.get("drive_format")
        if drive_format == "virtio":
            drive_format = "virtio_blk"

        nic_model = params.get("nic_model")
        if nic_model == "virtio":
            nic_model = "virtio_nic"

        fullname = params.get("name")
        pages = "smallpages"
        name = params.get("test_name")
        if fullname:
            p = re.compile(".*full\.(\w+)\..*%s\.(.+)\.%s"
                            % (drive_format, params.get("image_format")))
            m = p.match(fullname)
            if m:
                pages = m.group(1)
                name = m.group(2)
        test_cfg  = "include virtlab_tests.cfg\n"
        test_cfg += "include cdkeys.cfg\n"
        test_cfg += "nic_script = %s\n" % params.get("nic_script")
        test_cfg += "pci_assignable = %s\n" % params.get("pci_assignable")
        test_cfg += "display = %s\n" % params.get("display")
        test_cfg += "hosttype = %s\n" % params.get("hosttype")
        test_cfg += "image_name = %s\n" % params.get("image_name")
        test_cfg += "image_boot = %s\n" % params.get("image_boot")
        test_cfg += "dsthost = %s\n" % params.get("srchost")
        test_cfg += "bridge = %s\n" % params.get("bridge")
        test_cfg += "use_storage = %s\n" % params.get("use_storage")
        test_cfg += "mig_timeout = %s\n" % params.get("mig_timeout")
        test_cfg += "login_timeout = %s\n" % params.get("login_timeout")
        test_cfg += "wait_augment_ratio = %s\n" % params.get("wait_augment_ratio")
        test_cfg += "install_timeout = %s\n" % params.get("install_timeout")
        test_cfg += "smp = %s\n" % params.get("smp")
        test_cfg += "vcpu_cores = %s\n" % params.get("vcpu_cores")
        test_cfg += "vcpu_threads = %s\n" % params.get("vcpu_threads")
        test_cfg += "mem = %s\n" % params.get("mem")
        test_cfg += "iterations = %s\n" % params.get("iterations")
        test_cfg += "iscsi_dev = %s\n" % params.get("iscsi_dev")
        test_cfg += "iscsi_number = %s\n" % params.get("iscsi_number")
        # These params needs by cross_host test.
        ## disable remote test.
        test_cfg += "slaver_peer = yes\n"
        ## don't start vms before images are ready.
        test_cfg += "start_vm = no\n"
        ## port for XMLRPC server.
        if params.get("listen_port"):
            test_cfg += "listen_port = %s\n" % params.get("listen_port")
        test_cfg += "only %s\n" % pages
        test_cfg += "only %s\n" % guest_name
        test_cfg += "only %s\n" % params.get("platform")
        test_cfg += "only %s\n" % drive_format
        test_cfg += "only %s\n" % nic_model
        test_cfg += "only %s\n" % params.get("image_format")
        test_cfg += "only full\n"
        if params.get("test_name"):
            test_cfg += "only %s\n" % params.get("test_name")
        else:
            test_cfg += "only %s\n" % name
        test_cfg += "variants:\n"
        test_cfg += "    - repeat1:\n"
        test_cfg += "pre_test:\n"
        test_cfg += "    only repeat1\n"
        test_cfg += "    iterations = 1\n"

        return test_cfg


    def build_config_file(autotest_path, config_string,
                        config_filename= "tests.cfg"):
        kvm_dir = os.path.join(autotest_path, 'tests/kvm')
        kvm_tests = os.path.join(kvm_dir, config_filename)
        try:
            file = open(kvm_tests, 'w')
        except IOError:
            raise error.TestError("Failed to create config file kvm_tests.cfg")
        file.write(config_string)
        file.close()


    def get_results():
        """
        Copy autotest results present on the guest back to the host.
        """
        logging.info("Trying to copy autotest results from guest")
        guest_results_dir = os.path.join(outputdir, "guest_autotest_results")
        if not os.path.exists(guest_results_dir):
            try:
                os.mkdir(guest_results_dir)
            except OSError:
                logging.warn("Directory %s existed already!", guest_results_dir)
        vm.copy_files_from("%s/results/default/*" % autotest_path,
                           guest_results_dir)


    def get_results_summary():
        """
        Get the status of the tests that were executed on the host and close
        the session where autotest was being executed.
        """
        output = session.cmd_output("cat results/*/status")
        try:
            results = scan_results.parse_results(output)
            # Report test results
            logging.info("Results (test, status, duration, info):")
            for result in results:
                logging.info(str(result))
            session.close()
            return results
        except Exception, e:
            logging.error("Error processing guest autotest results: %s", e)
            return None

    if (not kvm_test) and (not os.path.isfile(control_path)):
        raise error.TestError("Invalid path to autotest control file: %s" %
                              control_path)

    migrate_background = (params.get("migrate_background") == "yes")
    if migrate_background:
        mig_timeout = float(params.get("mig_timeout", "3600"))
        mig_protocol = params.get("migration_protocol", "tcp")

    compressed_autotest_path = "/tmp/autotest.tar.bz2"

    # To avoid problems, let's make the test use the current AUTODIR
    # (autotest client path) location
    autotest_path = os.environ['AUTODIR']
    if kvm_test:
        test_cfg = generate_test_cfg(vm.params)
        build_config_file(autotest_path, test_cfg,
                        config_filename="tests.cfg.remote")
        logging.info("Running kvm autotest on remote machine, timeout %ss",
                    timeout)

    # tar the contents of bindir/autotest
    cmd = "tar cvjf %s %s/*" % (compressed_autotest_path, autotest_path)
    # yes, we need kvm test in host's autotest.
    if not kvm_test:
        cmd += " --exclude=%s/tests/kvm" % autotest_path
    else:
        cmd += " --exclude=%s/tests/kvm/env" % autotest_path
        cmd += " --exclude=%s/tests/kvm/isos" % autotest_path
        cmd += " --exclude=%s/tests/kvm/images" % autotest_path
    cmd += " --exclude=%s/results" % autotest_path
    cmd += " --exclude=%s/tmp" % autotest_path
    cmd += " --exclude=%s/control*" % autotest_path
    cmd += " --exclude=*.pyc"
    cmd += " --exclude=*.svn"
    cmd += " --exclude=*.git"
    logging.info("Trying to package autotest.")
    utils.run(cmd)

    # Copy autotest.tar.bz2
    copy_if_hash_differs(vm, compressed_autotest_path,
                        compressed_autotest_path)

    # Extract autotest.tar.bz2
    extract(vm, compressed_autotest_path, "/")


    if not kvm_test:
        vm.copy_files_to(control_path,
                                os.path.join(autotest_path, 'control'))
        # Run the test
        logging.info("Running autotest control file %s on guest, timeout %ss",
                     os.path.basename(control_path), timeout)
    session.cmd("cd %s" % autotest_path)
    try:
        session.cmd("rm -f control.state")
        session.cmd("rm -rf results/*")
        session.cmd("rm -rf tmp/*")
        if kvm_test:
            session.cmd("mv -f tests/kvm/tests.cfg.remote tests/kvm/tests.cfg")
    except aexpect.ShellError:
        pass
    try:
        bg = None
        try:
            logging.info("---------------- Test output ----------------")
            if migrate_background:
                mig_timeout = float(params.get("mig_timeout", "3600"))
                mig_protocol = params.get("migration_protocol", "tcp")
                if kvm_test:
                    bg = virt_utils.Thread(session.cmd_output,
                              kwargs={'cmd': "bin/autotest tests/kvm/control",
                                     'timeout': timeout,
                                     'print_func': logging.info})
                else:
                    bg = virt_utils.Thread(session.cmd_output,
                                      kwargs={'cmd': "bin/autotest control",
                                              'timeout': timeout,
                                              'print_func': logging.info})

                bg.start()

                while bg.is_alive():
                    logging.info("Tests is not ended, start a round of"
                                 "migration ...")
                    vm.migrate(timeout=mig_timeout, protocol=mig_protocol)
            else:
                if kvm_test:
                    session.cmd_output("bin/autotest tests/kvm/control",
                                       timeout=timeout, print_func=logging.info)
                else:
                    session.cmd_output("bin/autotest control", timeout=timeout,
                                       print_func=logging.info)
        finally:
            logging.info("------------- End of test output ------------")
            if migrate_background and bg:
                bg.join()
    except aexpect.ShellTimeoutError:
        if vm.is_alive():
            get_results()
            get_results_summary()
            raise error.TestError("Timeout elapsed while waiting for job to "
                                  "complete")
        else:
            raise error.TestError("Autotest job on guest failed "
                                  "(VM terminated during job)")
    except aexpect.ShellProcessTerminatedError:
        get_results()
        raise error.TestError("Autotest job on guest failed "
                              "(Remote session terminated during job)")

    results = get_results_summary()
    get_results()

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


    def join(self):
        """
        Wait for the join of thread and raise its exception if any.
        """
        self.thread.join()
        if self.exception:
            raise self.exception


    def is_alive(self):
        """
        Check whether the test is still alive.
        """
        return self.thread.isAlive()


def get_loss_ratio(output):
    """
    Get the packet loss ratio from the output of ping
.
    @param output: Ping output.
    """
    try:
        return int(re.findall('(\d+)% packet loss', output)[0])
    except IndexError:
        logging.debug(output)
        return -1


def raw_ping(command, timeout, session, output_func):
    """
    Low-level ping command execution.

    @param command: Ping command.
    @param timeout: Timeout of the ping command.
    @param session: Local executon hint or session to execute the ping command.
    """
    if session is None:
        process = aexpect.run_bg(command, output_func=output_func,
                                        timeout=timeout)

        # Send SIGINT signal to notify the timeout of running ping process,
        # Because ping have the ability to catch the SIGINT signal so we can
        # always get the packet loss ratio even if timeout.
        if process.is_alive():
            virt_utils.kill_process_tree(process.get_pid(), signal.SIGINT)

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
            except:
                status = -1

        return status, output


def ping(dest=None, count=None, interval=None, interface=None,
         packetsize=None, ttl=None, hint=None, adaptive=False,
         broadcast=False, flood=False, timeout=0,
         output_func=logging.debug, session=None):
    """
    Wrapper of ping.

    @param dest: Destination address.
    @param count: Count of icmp packet.
    @param interval: Interval of two icmp echo request.
    @param interface: Specified interface of the source address.
    @param packetsize: Packet size of icmp.
    @param ttl: IP time to live.
    @param hint: Path mtu discovery hint.
    @param adaptive: Adaptive ping flag.
    @param broadcast: Broadcast ping flag.
    @param flood: Flood ping flag.
    @param timeout: Timeout for the ping command.
    @param output_func: Function used to log the result of ping.
    @param session: Local executon hint or session to execute the ping command.
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
        output_func = None

    return raw_ping(command, timeout, session, output_func)


def get_linux_ifname(session, mac_address):
    """
    Get the interface name through the mac address.

    @param session: session to the virtual machine
    @mac_address: the macaddress of nic
    """

    output = session.cmd_output("ifconfig -a")

    try:
        ethname = re.findall("(\w+)\s+Link.*%s" % mac_address, output,
                             re.IGNORECASE)[0]
        return ethname
    except:
        return None


def restart_guest_network(session, nic_name=None):
    """
    Restart guest's network via serial console.

    @param session: session to virtual machine
    @nic_name: nic card name in guest to restart
    """
    if_list = []
    if not nic_name:
        # initiate all interfaces on guest.
        o = session.cmd_output("ip link")
        if_list = re.findall(r"\d+: (eth\d+):", o)
    else:
        if_list.append(nic_name)

    if if_list:
        session.sendline("killall dhclient && "
                         "dhclient %s &" % ' '.join(if_list))

def  vm_runner_monitor(vm, monitor_cmd, test_cmd, guest_path, timeout = 300):
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
        s, o = commands.getstatusoutput("pstree -p %s" % fd["pid"])
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
    result_file = "/tmp/monitor_result_%s" % tag

    monitor = threading.Thread(target=monitor_thread,args=(monitor_cmd,
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

    guest_result_file = "/tmp/guest_test_result_%s" % tag
    guest_monitor_result_file = "/tmp/guest_test_monitor_result_%s" % tag
    vm.copy_files_from(guest_path, guest_result_file)
    vm.copy_files_from("%s_monitor" % guest_path, guest_monitor_result_file)
    return tag

def aton(str):
    """
    Transform a string to a number(include float and int). If the string is
    not in the form of number, just return false.
    @str: string to transfrom
    Return: float, int or False for failed transform
    """
    substring = re.split("\.", str)
    if len(substring) == 1:
        if substring[0].isdigit():
            return string.atoi(str)
    elif len(substring) == 2:
        if substring[0].isdigit() and substring[1].isdigit():
            return string.atof(str)
    return False

def summary_up_result(result_file, ignore, row_head, column_mark):
    """
    Use to summary the monitor or other kinds of results. Now it calculate
    the average value for each item in the results. It fit to the records that
    in matrix form.
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
                empty, row, eachLine = re.split(row_head, eachLine)
                for i in re.split("\s+", eachLine):
                    if i:
                        result_dict[i] = {}
                        column_list[column] = i
                        column += 1
                head_flag = True
            elif len(re.findall(column_mark, eachLine)) == 0:
                column = 0
                empty, row, eachLine = re.split(row_head, eachLine)
                row_flag = False
                for i in row_list:
                    if row == i:
                        row_flag = True
                if row_flag == False:
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
                average_list[column_list[i]][j] = "%.2f" % (count / len(result_dict[column_list[i]][j]))

    return average_list

def create_image(cmd, img_name, img_fmt, base_img=None, base_fmt=None,
       img_size=None, encrypted=None, preallocated=None, cluster_size=None):
    """
    Create image
    @img_name: the name of the image to be created
    @img_fmt: the format of the image to be created
    @base_img: the base image name when create snapshot
    @base_fmt: the format of base image
    @img_size: image size
    @encrypted: there are two value "off" and "on", default value is "off"
    @preallocated: there are two value "metadata" and "off", default is "off"
    @cluster_size: the qcow2 cluster size
    """
    cmd += " create"
    if encrypted == "yes":
        cmd += " -o encryption=on"
    if base_img:
        cmd += " -b %s" % base_img
        if base_fmt:
            cmd += " -F %s" % base_fmt
    cmd += " -f %s" % img_fmt
    cmd += " %s" % img_name
    if img_size:
        cmd += " %s" % img_size
    if preallocated == "yes":
        cmd += " -o preallocation=metadata"
    if cluster_size is not None:
        cmd += " -o cluster_size=%s" % cluster_size

    try:
        utils.system(cmd)
    except error.CmdError, e:
        raise error.TestFail("Could not create image:\n%s", str(e))
        return None
    return img_name

def convert_image(cmd, img_name, img_fmt, convert_name, convert_fmt,
                  compressed=None, encrypted=None):
    """
    Convert image:
    @cmd: qemu-img cmd
    @img_name: the name of the image to be converted
    @img_fmt: the format of the image to be converted
    @convert_name: the name of the image after convert
    @convert_fmt: the format after convert
    @compressed: indicates that target image must be compressed
    @encrypted: there are two value "off" and "on", default value is "off"
    """
    cmd += " convert"
    if compressed == "yes":
        cmd += " -c"
    if encrypted == "yes":
        cmd += " -o encryption=on"
    if img_fmt:
        cmd += " -f %s" % img_fmt
    cmd += " -O %s" % convert_fmt
    cmd += " %s %s" % (img_name, convert_name)
    logging.info("Convert image %s from %s to %s", img_name, img_fmt,
                  convert_fmt)
    try:
        utils.system(cmd)
    except error.CmdError, e:
        raise error.TestFail("Could not convert image:\n%s", str(e))
        return None
    return convert_name

def rebase_image(cmd, snapshot_img, base_img, base_fmt, snapshot_fmt=None,
                 mode=None):
    """
    Rebase image
    @cmd: qemu-img cmd
    @snapshot_img: the snapshot name
    @base_img: base image name
    @base_fmt: base image format
    @snapshot_fmt: the snapshot format
    @mode: there are two value, "safe" and "unsafe", devault is "safe"
    """
    cmd += " rebase"
    if snapshot_fmt:
        cmd += " -f %s" % snapshot_fmt
    if mode == "unsafe":
        cmd += " -u"
    cmd += " -b %s -F %s %s" % (base_img, base_fmt, snapshot_img)
    logging.info("Rebase snapshot %s to %s..." % (snapshot_img, base_img))
    try:
        utils.system(cmd)
    except error.CmdError, e:
        raise error.TestFail("Could not rebase snapshot:\n%s", str(e))
        return None
    return base_img

def commit_image(cmd, snapshot_img, snapshot_fmt):
    """
    Commit image
    @cmd: qemu-img cmd
    @snapshot_img: the name of the snapshot to be commited
    @snapshot_fmt: the format of the snapshot
    """
    cmd += " commit"
    cmd += " -f %s %s" % (snapshot_fmt, snapshot_img)
    logging.info("Commit snapshot %s" % snapshot_img)
    try:
        utils.system(cmd)
    except error.CmdError, e:
        raise error.TestFail("Commit image failed\n%s", str(e))
        return None

    logging.info("commit %s to backing file" % snapshot_img)
    return snapshot_img


def run_sub_test(test, params, env, sub_type=None, tag=None):
    """
    Call another test script in one test script.
    @param test:   KVM test object.
    @param params: Dictionary with the test parameters.
    @param env:    Dictionary with test environment.
    @sub_type: type of called test script.
    @param tag:  tag for get the sub_test params
    """
    if sub_type is None:
        raise error.TestError("No sub test is found")
    virt_dir = os.path.dirname(virt_utils.__file__)
    subtest_dir_virt = os.path.join(virt_dir, "tests")
    subtest_dir_kvm = os.path.join(test.bindir, "tests")
    subtest_dir = None
    for d in [subtest_dir_kvm, subtest_dir_virt]:
        module_path = os.path.join(d, "%s.py" % sub_type)
        if os.path.isfile(module_path):
            subtest_dir = d
            break
    if subtest_dir is None:
        raise error.TestError("Could not find test file %s.py "
                              "on either %s or %s directory" % (sub_type,
                              subtest_dir_kvm, subtest_dir_virt))

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

    @param params: Dictionary with the test parameters.
    @param session: A shell session on the VM provided.
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

    raise error.TestFail("Could not find a cdrom device contain media.")
def update_mac_ip_address(vm, params):
    """
    Get mac and ip address from guest and update the mac pool and 
    address cache
    @param vm: VM object
    @param params: Dictionary with the test parameters.
    """
    network_query = params.get("network_query", "ifconfig")
    mac_ip_filter = params.get("mac_ip_filter")
    session = vm.wait_for_serial_login(timeout=360)
    s, o = session.cmd_status_output(network_query)
    macs_ips = re.findall(mac_ip_filter, o)
    # Get nics number
    if params.get("devices_requested") is not None:
        nic_minimum = int(params.get("devices_requested"))
    else:
        nics =  params.get("nics")
        nic_minimum = len(re.split("\s+", nics.strip()))

    if len(macs_ips) < nic_minimum:
        logging.warn("Not all nics get ip address")

    for (mac, ip) in macs_ips:
        vlan = macs_ips.index((mac, ip))
        vm.address_cache[mac.lower()] = ip
        virt_utils.set_mac_address(vm.instance, vlan, mac)
