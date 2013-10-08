"""
Virtualization test utility functions.

:copyright: 2008-2009 Red Hat Inc.
"""

import time
import string
import random
import socket
import os
import signal
import re
import logging
import commands
import fcntl
import sys
import inspect
import tarfile
import shutil
import getpass
from autotest.client import utils, os_dep
from autotest.client.shared import error, logging_config
from autotest.client.shared import git
import data_dir
try:
    from staging import utils_koji
except ImportError:
    from autotest.client.shared import utils_koji


import platform
ARCH = platform.machine()


class UnsupportedCPU(error.TestError):
    pass

# TODO: remove this import when log_last_traceback is moved to autotest
import traceback

# TODO: this function is being moved into autotest. For compatibility
# reasons keep it here too but new code should use the one from base_utils.


def log_last_traceback(msg=None, log=logging.error):
    """
    @warning: This function is being moved into autotest and your code should
              use autotest.client.shared.base_utils function instead.
    Writes last traceback into specified log.
    :param msg: Override the default message. ["Original traceback"]
    :param log: Where to log the traceback [logging.error]
    """
    if not log:
        log = logging.error
    if msg:
        log(msg)
    exc_type, exc_value, exc_traceback = sys.exc_info()
    if not exc_traceback:
        log('Requested log_last_traceback but no exception was raised.')
        return
    log("Original " +
        "".join(traceback.format_exception(exc_type, exc_value,
                                           exc_traceback)))


def lock_file(filename, mode=fcntl.LOCK_EX):
    f = open(filename, "w")
    fcntl.lockf(f, mode)
    return f


def unlock_file(f):
    fcntl.lockf(f, fcntl.LOCK_UN)
    f.close()


# Utility functions for dealing with external processes


def unique(llist):
    """
    Return a list of the elements in list, but without duplicates.

    :param list: List with values.
    :return: List with non duplicate elements.
    """
    n = len(llist)
    if n == 0:
        return []
    u = {}
    try:
        for x in llist:
            u[x] = 1
    except TypeError:
        return None
    else:
        return u.keys()


def find_command(cmd):
    """
    Try to find a command in the PATH, paranoid version.

    :param cmd: Command to be found.
    :raise: ValueError in case the command was not found.
    """
    common_bin_paths = ["/usr/libexec", "/usr/local/sbin", "/usr/local/bin",
                        "/usr/sbin", "/usr/bin", "/sbin", "/bin"]
    try:
        path_paths = os.environ['PATH'].split(":")
    except IndexError:
        path_paths = []
    path_paths = unique(common_bin_paths + path_paths)

    for dir_path in path_paths:
        cmd_path = os.path.join(dir_path, cmd)
        if os.path.isfile(cmd_path):
            return os.path.abspath(cmd_path)

    raise ValueError('Missing command: %s' % cmd)


def pid_exists(pid):
    """
    Return True if a given PID exists.

    :param pid: Process ID number.
    """
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def safe_kill(pid, signal):
    """
    Attempt to send a signal to a given process that may or may not exist.

    :param signal: Signal number.
    """
    try:
        os.kill(pid, signal)
        return True
    except Exception:
        return False


def kill_process_tree(pid, sig=signal.SIGKILL):
    """Signal a process and all of its children.

    If the process does not exist -- return.

    :param pid: The pid of the process to signal.
    :param sig: The signal to send to the processes.
    """
    if not safe_kill(pid, signal.SIGSTOP):
        return
    children = commands.getoutput("ps --ppid=%d -o pid=" % pid).split()
    for child in children:
        kill_process_tree(int(child), sig)
    safe_kill(pid, sig)
    safe_kill(pid, signal.SIGCONT)


# The following are utility functions related to ports.

def is_port_free(port, address):
    """
    Return True if the given port is available for use.

    :param port: Port number
    """
    try:
        s = socket.socket()
        #s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if address == "localhost":
            s.bind(("localhost", port))
            free = True
        else:
            s.connect((address, port))
            free = False
    except socket.error:
        if address == "localhost":
            free = False
        else:
            free = True
    s.close()
    return free


def find_free_port(start_port, end_port, address="localhost"):
    """
    Return a host free port in the range [start_port, end_port].

    :param start_port: First port that will be checked.
    :param end_port: Port immediately after the last one that will be checked.
    """
    for i in range(start_port, end_port):
        if is_port_free(i, address):
            return i
    return None


def find_free_ports(start_port, end_port, count, address="localhost"):
    """
    Return count of host free ports in the range [start_port, end_port].

    @count: Initial number of ports known to be free in the range.
    :param start_port: First port that will be checked.
    :param end_port: Port immediately after the last one that will be checked.
    """
    ports = []
    i = start_port
    while i < end_port and count > 0:
        if is_port_free(i, address):
            ports.append(i)
            count -= 1
        i += 1
    return ports


# An easy way to log lines to files when the logging system can't be used

_open_log_files = {}
_log_file_dir = "/tmp"


def log_line(filename, line):
    """
    Write a line to a file.  '\n' is appended to the line.

    :param filename: Path of file to write to, either absolute or relative to
            the dir set by set_log_file_dir().
    :param line: Line to write.
    """
    global _open_log_files, _log_file_dir

    path = get_path(_log_file_dir, filename)
    if path not in _open_log_files:
        # First, let's close the log files opened in old directories
        close_log_file(filename)
        # Then, let's open the new file
        try:
            os.makedirs(os.path.dirname(path))
        except OSError:
            pass
        _open_log_files[path] = open(path, "w")
    timestr = time.strftime("%Y-%m-%d %H:%M:%S")
    _open_log_files[path].write("%s: %s\n" % (timestr, line))
    _open_log_files[path].flush()


def set_log_file_dir(directory):
    """
    Set the base directory for log files created by log_line().

    :param dir: Directory for log files.
    """
    global _log_file_dir
    _log_file_dir = directory


def close_log_file(filename):
    global _open_log_files, _log_file_dir
    remove = []
    for k in _open_log_files:
        if os.path.basename(k) == filename:
            f = _open_log_files[k]
            f.close()
            remove.append(k)
    if remove:
        for key_to_remove in remove:
            _open_log_files.pop(key_to_remove)


# The following are miscellaneous utility functions.

def get_path(base_path, user_path):
    """
    Translate a user specified path to a real path.
    If user_path is relative, append it to base_path.
    If user_path is absolute, return it as is.

    :param base_path: The base path of relative user specified paths.
    :param user_path: The user specified path.
    """
    if os.path.isabs(user_path):
        return user_path
    else:
        return os.path.join(base_path, user_path)


def generate_random_string(length, ignore_str=string.punctuation,
                           convert_str=""):
    """
    Return a random string using alphanumeric characters.

    :param length: Length of the string that will be generated.
    :param ignore_str: Characters that will not include in generated string.
    :param convert_str: Characters that need to be escaped (prepend "\\").

    :return: The generated random string.
    """
    r = random.SystemRandom()
    sr = ""
    chars = string.letters + string.digits + string.punctuation
    if not ignore_str:
        ignore_str = ""
    for i in ignore_str:
        chars = chars.replace(i, "")

    while length > 0:
        tmp = r.choice(chars)
        if convert_str and (tmp in convert_str):
            tmp = "\\%s" % tmp
        sr += tmp
        length -= 1
    return sr


def generate_random_id():
    """
    Return a random string suitable for use as a qemu id.
    """
    return "id" + generate_random_string(6)


def generate_tmp_file_name(file_name, ext=None, directory='/tmp/'):
    """
    Returns a temporary file name. The file is not created.
    """
    while True:
        file_name = (file_name + '-' + time.strftime("%Y%m%d-%H%M%S-") +
                     generate_random_string(4))
        if ext:
            file_name += '.' + ext
        file_name = os.path.join(directory, file_name)
        if not os.path.exists(file_name):
            break

    return file_name


def format_str_for_message(sr):
    """
    Format str so that it can be appended to a message.
    If str consists of one line, prefix it with a space.
    If str consists of multiple lines, prefix it with a newline.

    :param str: string that will be formatted.
    """
    lines = str.splitlines()
    num_lines = len(lines)
    sr = "\n".join(lines)
    if num_lines == 0:
        return ""
    elif num_lines == 1:
        return " " + sr
    else:
        return "\n" + sr


def wait_for(func, timeout, first=0.0, step=1.0, text=None):
    """
    If func() evaluates to True before timeout expires, return the
    value of func(). Otherwise return None.

    @brief: Wait until func() evaluates to True.

    :param timeout: Timeout in seconds
    :param first: Time to sleep before first attempt
    :param steps: Time to sleep between attempts in seconds
    :param text: Text to print while waiting, for debug purposes
    """
    start_time = time.time()
    end_time = time.time() + timeout

    time.sleep(first)

    while time.time() < end_time:
        if text:
            logging.debug("%s (%f secs)", text, (time.time() - start_time))

        output = func()
        if output:
            return output

        time.sleep(step)

    return None


def get_hash_from_file(hash_path, dvd_basename):
    """
    Get the a hash from a given DVD image from a hash file
    (Hash files are usually named MD5SUM or SHA1SUM and are located inside the
    download directories of the DVDs)

    :param hash_path: Local path to a hash file.
    :param cd_image: Basename of a CD image
    """
    hash_file = open(hash_path, 'r')
    for line in hash_file.readlines():
        if dvd_basename in line:
            return line.split()[0]


def run_tests(parser, job):
    """
    Runs the sequence of KVM tests based on the list of dictionaries
    generated by the configuration system, handling dependencies.

    :param parser: Config parser object.
    :param job: Autotest job object.

    :return: True, if all tests ran passed, False if any of them failed.
    """
    last_index = -1
    for i, d in enumerate(parser.get_dicts()):
        logging.info("Test %4d:  %s" % (i + 1, d["shortname"]))
        last_index += 1

    status_dict = {}
    failed = False
    # Add the parameter decide if setup host env in the test case
    # For some special tests we only setup host in the first and last case
    # When we need to setup host env we need the host_setup_flag as following:
    #    0(00): do nothing
    #    1(01): setup env
    #    2(10): cleanup env
    #    3(11): setup and cleanup env
    index = 0
    setup_flag = 1
    cleanup_flag = 2
    for param_dict in parser.get_dicts():
        if param_dict.get("host_setup_flag", None) is not None:
            flag = int(param_dict["host_setup_flag"])
            if index == 0:
                param_dict["host_setup_flag"] = flag | setup_flag
            elif index == last_index:
                param_dict["host_setup_flag"] = flag | cleanup_flag
            else:
                param_dict["host_setup_flag"] = flag
        else:
            if index == 0:
                param_dict["host_setup_flag"] = setup_flag
            elif index == last_index:
                param_dict["host_setup_flag"] = cleanup_flag
        index += 1

        # Add kvm module status
        sysfs_dir = param_dict.get("sysfs_dir", "/sys")
        param_dict["kvm_default"] = get_module_params(sysfs_dir, 'kvm')

        if param_dict.get("skip") == "yes":
            continue
        dependencies_satisfied = True
        for dep in param_dict.get("dep"):
            for test_name in status_dict.keys():
                if not dep in test_name:
                    continue
                # So the only really non-fatal state is WARN,
                # All the others make it not safe to proceed with dependency
                # execution
                if status_dict[test_name] not in ['GOOD', 'WARN']:
                    dependencies_satisfied = False
                    break
        test_iterations = int(param_dict.get("iterations", 1))
        test_tag = param_dict.get(
            "vm_type") + "." + param_dict.get("shortname")

        if dependencies_satisfied:
            # Setting up profilers during test execution.
            profilers = param_dict.get("profilers", "").split()
            for profiler in profilers:
                job.profilers.add(profiler, **param_dict)
            # We need only one execution, profiled, hence we're passing
            # the profile_only parameter to job.run_test().
            profile_only = bool(profilers) or None
            test_timeout = int(param_dict.get("test_timeout", 14400))
            current_status = job.run_test_detail("virt",
                                                 params=param_dict,
                                                 tag=test_tag,
                                                 iterations=test_iterations,
                                                 profile_only=profile_only,
                                                 timeout=test_timeout)
            for profiler in profilers:
                job.profilers.delete(profiler)
        else:
            # We will force the test to fail as TestNA during preprocessing
            param_dict['dependency_failed'] = 'yes'
            current_status = job.run_test_detail("virt",
                                                 params=param_dict,
                                                 tag=test_tag,
                                                 iterations=test_iterations)

        if not current_status:
            failed = True
        status_dict[param_dict.get("name")] = current_status

    return not failed


def display_attributes(instance):
    """
    Inspects a given class instance attributes and displays them, convenient
    for debugging.
    """
    logging.debug("Attributes set:")
    for member in inspect.getmembers(instance):
        name, value = member
        attribute = getattr(instance, name)
        if not (name.startswith("__") or callable(attribute) or not value):
            logging.debug("    %s: %s", name, value)


def get_full_pci_id(pci_id):
    """
    Get full PCI ID of pci_id.

    :param pci_id: PCI ID of a device.
    """
    cmd = "lspci -D | awk '/%s/ {print $1}'" % pci_id
    status, full_id = commands.getstatusoutput(cmd)
    if status != 0:
        return None
    return full_id


def get_vendor_from_pci_id(pci_id):
    """
    Check out the device vendor ID according to pci_id.

    :param pci_id: PCI ID of a device.
    """
    cmd = "lspci -n | awk '/%s/ {print $3}'" % pci_id
    return re.sub(":", " ", commands.getoutput(cmd))


class Flag(str):

    """
    Class for easy merge cpuflags.
    """
    aliases = {}

    def __new__(cls, flag):
        if flag in Flag.aliases:
            flag = Flag.aliases[flag]
        return str.__new__(cls, flag)

    def __eq__(self, other):
        s = set(self.split("|"))
        o = set(other.split("|"))
        if s & o:
            return True
        else:
            return False

    def __str__(self):
        return self.split("|")[0]

    def __repr__(self):
        return self.split("|")[0]

    def __hash__(self, *args, **kwargs):
        return 0


kvm_map_flags_to_test = {
    Flag('avx'): set(['avx']),
    Flag('sse3|pni'): set(['sse3']),
    Flag('ssse3'): set(['ssse3']),
    Flag('sse4.1|sse4_1|sse4.2|sse4_2'): set(['sse4']),
    Flag('aes'): set(['aes', 'pclmul']),
    Flag('pclmuldq'): set(['pclmul']),
    Flag('pclmulqdq'): set(['pclmul']),
    Flag('rdrand'): set(['rdrand']),
    Flag('sse4a'): set(['sse4a']),
    Flag('fma4'): set(['fma4']),
    Flag('xop'): set(['xop']),
}


kvm_map_flags_aliases = {
    'sse4_1': 'sse4.1',
    'sse4_2': 'sse4.2',
    'pclmuldq': 'pclmulqdq',
    'sse3': 'pni',
    'ffxsr': 'fxsr_opt',
    'xd': 'nx',
    'i64': 'lm',
           'psn': 'pn',
           'clfsh': 'clflush',
           'dts': 'ds',
           'htt': 'ht',
           'CMPXCHG8B': 'cx8',
           'Page1GB': 'pdpe1gb',
           'LahfSahf': 'lahf_lm',
           'ExtApicSpace': 'extapic',
           'AltMovCr8': 'cr8_legacy',
           'cr8legacy': 'cr8_legacy'
}


def kvm_flags_to_stresstests(flags):
    """
    Covert [cpu flags] to [tests]

    :param cpuflags: list of cpuflags
    :return: Return tests like string.
    """
    tests = set([])
    for f in flags:
        tests |= kvm_map_flags_to_test[f]
    param = ""
    for f in tests:
        param += "," + f
    return param


def get_cpu_flags():
    """
    Returns a list of the CPU flags
    """
    flags_re = re.compile(r'^flags\s*:(.*)')
    for line in open('/proc/cpuinfo').readlines():
        match = flags_re.match(line)
        if match:
            return match.groups()[0].split()
    return []


def get_cpu_vendor(cpu_flags=[], verbose=True):
    """
    Returns the name of the CPU vendor, either intel, amd or unknown
    """
    if not cpu_flags:
        cpu_flags = get_cpu_flags()

    if 'vmx' in cpu_flags:
        vendor = 'intel'
    elif 'svm' in cpu_flags:
        vendor = 'amd'
    elif ARCH == 'ppc64':
        vendor = 'ibm'
    else:
        vendor = 'unknown'

    if verbose:
        logging.debug("Detected CPU vendor as '%s'", vendor)
    return vendor


def get_support_machine_type(qemu_binary="/usr/libexec/qemu-kvm"):
    """
    Get the machine type the host support,return a list of machine type
    """
    o = utils.system_output("%s -M ?" % qemu_binary)
    s = re.findall("(\S*)\s*RHEL\s", o)
    c = re.findall("(RHEL.*PC)", o)
    return (s, c)


def get_cpu_model():
    """
    Get cpu model from host cpuinfo
    """
    def _make_up_pattern(flags):
        """
        Update the check pattern to a certain order and format
        """
        pattern_list = re.split(",", flags.strip())
        pattern_list.sort()
        pattern = r"(\b%s\b)" % pattern_list[0]
        for i in pattern_list[1:]:
            pattern += r".+(\b%s\b)" % i
        return pattern

    cpu_types = {"amd": ["Opteron_G5", "Opteron_G4", "Opteron_G3",
                         "Opteron_G2", "Opteron_G1"],
                 "intel": ["Haswell", "SandyBridge", "Westmere",
                           "Nehalem", "Penryn", "Conroe"]}
    cpu_type_re = {"Opteron_G5":
                   "f16c,fma,tbm",
                   "Opteron_G4":
                   "avx,xsave,aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3,sse4a",
                   "Opteron_G3": "cx16,sse4a",
                   "Opteron_G2": "cx16",
                   "Opteron_G1": "",
                   "Haswell":
                   "fsgsbase,bmi1,hle,avx2,smep,bmi2,erms,invpcid,rtm",
                   "SandyBridge":
                   "avx,xsave,aes,sse4_2|sse4.2,sse4.1|sse4_1,cx16,ssse3",
                   "Westmere": "aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Nehalem": "sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Penryn": "sse4.1|sse4_1,cx16,ssse3",
                   "Conroe": "ssse3"}

    flags = get_cpu_flags()
    flags.sort()
    cpu_flags = " ".join(flags)
    vendor = get_cpu_vendor(flags)

    cpu_model = ""
    if cpu_flags:
        for cpu_type in cpu_types.get(vendor):
            pattern = _make_up_pattern(cpu_type_re.get(cpu_type))
            if re.findall(pattern, cpu_flags):
                cpu_model = cpu_type
                break
    else:
        logging.warn("Can not get cpu flags from cpuinfo")

    if cpu_model:
        cpu_type_list = cpu_types.get(vendor)
        cpu_support_model = cpu_type_list[cpu_type_list.index(cpu_model):]
        cpu_model = ",".join(cpu_support_model)

    return cpu_model


def get_archive_tarball_name(source_dir, tarball_name, compression):
    '''
    Get the name for a tarball file, based on source, name and compression
    '''
    if tarball_name is None:
        tarball_name = os.path.basename(source_dir)

    if not tarball_name.endswith('.tar'):
        tarball_name = '%s.tar' % tarball_name

    if compression and not tarball_name.endswith('.%s' % compression):
        tarball_name = '%s.%s' % (tarball_name, compression)

    return tarball_name


def archive_as_tarball(source_dir, dest_dir, tarball_name=None,
                       compression='bz2', verbose=True):
    '''
    Saves the given source directory to the given destination as a tarball

    If the name of the archive is omitted, it will be taken from the
    source_dir. If it is an absolute path, dest_dir will be ignored. But,
    if both the destination directory and tarball anem is given, and the
    latter is not an absolute path, they will be combined.

    For archiving directory '/tmp' in '/net/server/backup' as file
    'tmp.tar.bz2', simply use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup')

    To save the file it with a different name, say 'host1-tmp.tar.bz2'
    and save it under '/net/server/backup', use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup',
                                      'host1-tmp')

    To save with gzip compression instead (resulting in the file
    '/net/server/backup/host1-tmp.tar.gz'), use:

    >>> utils_misc.archive_as_tarball('/tmp', '/net/server/backup',
                                      'host1-tmp', 'gz')
    '''
    tarball_name = get_archive_tarball_name(source_dir,
                                            tarball_name,
                                            compression)
    if not os.path.isabs(tarball_name):
        tarball_path = os.path.join(dest_dir, tarball_name)
    else:
        tarball_path = tarball_name

    if verbose:
        logging.debug('Archiving %s as %s' % (source_dir,
                                              tarball_path))

    os.chdir(os.path.dirname(source_dir))
    tarball = tarfile.TarFile(name=tarball_path, mode='w')
    tarball = tarball.open(name=tarball_path, mode='w:%s' % compression)
    tarball.add(os.path.basename(source_dir))
    tarball.close()


def parallel(targets):
    """
    Run multiple functions in parallel.

    :param targets: A sequence of tuples or functions.  If it's a sequence of
            tuples, each tuple will be interpreted as (target, args, kwargs) or
            (target, args) or (target,) depending on its length.  If it's a
            sequence of functions, the functions will be called without
            arguments.
    :return: A list of the values returned by the functions called.
    """
    threads = []
    for target in targets:
        if isinstance(target, tuple) or isinstance(target, list):
            t = utils.InterruptedThread(*target)
        else:
            t = utils.InterruptedThread(target)
        threads.append(t)
        t.start()
    return [t.join() for t in threads]


class VirtLoggingConfig(logging_config.LoggingConfig):

    """
    Used with the sole purpose of providing convenient logging setup
    for the KVM test auxiliary programs.
    """

    def configure_logging(self, results_dir=None, verbose=False):
        super(VirtLoggingConfig, self).configure_logging(use_console=True,
                                                         verbose=verbose)


def umount(src, mount_point, fstype):
    """
    Umount the src mounted in mount_point.

    @src: mount source
    @mount_point: mount point
    :type: file system type
    """
    mount_string = "%s %s %s" % (src, mount_point, fstype)
    if is_mounted(src, mount_point, fstype):
        umount_cmd = "umount %s" % mount_point
        try:
            utils.system(umount_cmd)
            return True
        except error.CmdError:
            return False
    else:
        logging.debug("%s is not mounted under %s", src, mount_point)
        return True


def mount(src, mount_point, fstype, perm="rw"):
    """
    Mount the src into mount_point of the host.

    @src: mount source
    @mount_point: mount point
    @fstype: file system type
    @perm: mount permission
    """
    umount(src, mount_point, fstype)
    mount_string = "%s %s %s %s" % (src, mount_point, fstype, perm)

    if is_mounted(src, mount_point, fstype, perm):
        logging.debug("%s is already mounted in %s with %s",
                      src, mount_point, perm)
        return True

    mount_cmd = "mount -t %s %s %s -o %s" % (fstype, src, mount_point, perm)
    try:
        utils.system(mount_cmd)
    except error.CmdError:
        return False

    return is_mounted(src, mount_point, fstype, perm)


def is_mounted(src, mount_point, fstype, perm=""):
    """
    Check mount status from /etc/mtab

    :param src: mount source
    :type src: string
    :param mount_point: mount point
    :type mount_point: string
    :param fstype: file system type
    :type fstype: string
    :param perm: mount permission
    :type perm: string
    :return: if the src is mounted as expect
    :rtype: Boolean
    """
    mount_point = os.path.realpath(mount_point)
    src = os.path.realpath(src)
    mount_string = "%s %s %s %s" % (src, mount_point, fstype, perm)
    if mount_string.strip() in file("/etc/mtab").read():
        logging.debug("%s is successfully mounted", src)
        return True
    else:
        logging.error("Can't find mounted NFS share - /etc/mtab contents \n%s",
                      file("/etc/mtab").read())
        return False


def install_host_kernel(job, params):
    """
    Install a host kernel, given the appropriate params.

    :param job: Job object.
    :param params: Dict with host kernel install params.
    """
    install_type = params.get('host_kernel_install_type')

    if install_type == 'rpm':
        logging.info('Installing host kernel through rpm')

        rpm_url = params.get('host_kernel_rpm_url')
        k_basename = os.path.basename(rpm_url)
        dst = os.path.join("/var/tmp", k_basename)
        k = utils.get_file(rpm_url, dst)
        host_kernel = job.kernel(k)
        host_kernel.install(install_vmlinux=False)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': k_basename})
        host_kernel.boot()

    elif install_type in ['koji', 'brew']:
        logging.info('Installing host kernel through koji/brew')

        koji_cmd = params.get('host_kernel_koji_cmd')
        koji_build = params.get('host_kernel_koji_build')
        koji_tag = params.get('host_kernel_koji_tag')

        k_deps = utils_koji.KojiPkgSpec(tag=koji_tag, build=koji_build,
                                        package='kernel',
                                        subpackages=['kernel-devel', 'kernel-firmware'])
        k = utils_koji.KojiPkgSpec(tag=koji_tag, build=koji_build,
                                   package='kernel', subpackages=['kernel'])

        c = utils_koji.KojiClient(koji_cmd)
        logging.info('Fetching kernel dependencies (-devel, -firmware)')
        c.get_pkgs(k_deps, job.tmpdir)
        logging.info('Installing kernel dependencies (-devel, -firmware) '
                     'through %s', install_type)
        k_deps_rpm_file_names = [os.path.join(job.tmpdir, rpm_file_name) for
                                 rpm_file_name in c.get_pkg_rpm_file_names(k_deps)]
        utils.run('rpm -U --force %s' % " ".join(k_deps_rpm_file_names))

        c.get_pkgs(k, job.tmpdir)
        k_rpm = os.path.join(job.tmpdir,
                             c.get_pkg_rpm_file_names(k)[0])
        host_kernel = job.kernel(k_rpm)
        host_kernel.install(install_vmlinux=False)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel':
                            " ".join(c.get_pkg_rpm_file_names(k_deps))})
        host_kernel.boot()

    elif install_type == 'git':
        logging.info('Chose to install host kernel through git, proceeding')

        repo = params.get('host_kernel_git_repo')
        repo_base = params.get('host_kernel_git_repo_base', None)
        branch = params.get('host_kernel_git_branch')
        commit = params.get('host_kernel_git_commit')
        patch_list = params.get('host_kernel_patch_list')
        if patch_list:
            patch_list = patch_list.split()
        kernel_config = params.get('host_kernel_config', None)

        repodir = os.path.join("/tmp", 'kernel_src')
        r = git.GitRepoHelper(uri=repo, branch=branch, destination_dir=repodir,
                              commit=commit, base_uri=repo_base)
        r.execute()
        host_kernel = job.kernel(r.destination_dir)
        if patch_list:
            host_kernel.patch(patch_list)
        if kernel_config:
            host_kernel.config(kernel_config)
        host_kernel.build()
        host_kernel.install()
        git_repo_version = '%s:%s:%s' % (r.uri, r.branch, r.get_top_commit())
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': git_repo_version})
        host_kernel.boot()

    else:
        logging.info('Chose %s, using the current kernel for the host',
                     install_type)
        k_version = utils.system_output('uname -r', ignore_status=True)
        utils.write_keyval(job.resultdir,
                           {'software_version_kernel': k_version})


def install_cpuflags_util_on_vm(test, vm, dst_dir, extra_flags=None):
    """
    Install stress to vm.

    :param vm: virtual machine.
    :param dst_dir: Installation path.
    :param extra_flags: Extraflags for gcc compiler.
    """
    if not extra_flags:
        extra_flags = ""

    cpuflags_src = os.path.join(test.virtdir, "deps", "test_cpu_flags")
    cpuflags_dst = os.path.join(dst_dir, "test_cpu_flags")
    session = vm.wait_for_login()
    session.cmd("rm -rf %s" %
                (cpuflags_dst))
    session.cmd("sync")
    vm.copy_files_to(cpuflags_src, dst_dir)
    session.cmd("sync")
    session.cmd("cd %s; make EXTRA_FLAGS='%s';" %
               (cpuflags_dst, extra_flags))
    session.cmd("sync")
    session.close()


def install_disktest_on_vm(test, vm, src_dir, dst_dir):
    """
    Install stress to vm.

    :param vm: virtual machine.
    :param src_dir: Source path.
    :param dst_dir: Instaltation path.
    """
    disktest_src = src_dir
    disktest_dst = os.path.join(dst_dir, "disktest")
    session = vm.wait_for_login()
    session.cmd("rm -rf %s" % (disktest_dst))
    session.cmd("mkdir -p %s" % (disktest_dst))
    session.cmd("sync")
    vm.copy_files_to(disktest_src, disktest_dst)
    session.cmd("sync")
    session.cmd("cd %s; make;" %
               (os.path.join(disktest_dst, "src")))
    session.cmd("sync")
    session.close()


def qemu_has_option(option, qemu_path="/usr/bin/qemu-kvm"):
    """
    Helper function for command line option wrappers

    :param option: Option need check.
    :param qemu_path: Path for qemu-kvm.
    """
    hlp = commands.getoutput("%s -help" % qemu_path)
    return bool(re.search(r"^-%s(\s|$)" % option, hlp, re.MULTILINE))


def bitlist_to_string(data):
    """
    Transform from bit list to ASCII string.

    :param data: Bit list to be transformed
    """
    result = []
    pos = 0
    c = 0
    while pos < len(data):
        c += data[pos] << (7 - (pos % 8))
        if (pos % 8) == 7:
            result.append(c)
            c = 0
        pos += 1
    return ''.join([chr(c) for c in result])


def string_to_bitlist(data):
    """
    Transform from ASCII string to bit list.

    :param data: String to be transformed
    """
    data = [ord(c) for c in data]
    result = []
    for ch in data:
        i = 7
        while i >= 0:
            if ch & (1 << i) != 0:
                result.append(1)
            else:
                result.append(0)
            i -= 1
    return result


def get_module_params(sys_path, module_name):
    """
    Get the kvm module params
    :param sys_path: sysfs path for modules info
    :param module_name: module to check
    """
    dir_params = os.path.join(sys_path, "module", module_name, "parameters")
    module_params = {}
    if os.path.isdir(dir_params):
        for filename in os.listdir(dir_params):
            full_dir = os.path.join(dir_params, filename)
            tmp = open(full_dir, 'r').read().strip()
            module_params[full_dir] = tmp
    else:
        return None
    return module_params


def create_x509_dir(path, cacert_subj, server_subj, passphrase,
                    secure=False, bits=1024, days=1095):
    """
    Creates directory with freshly generated:
    ca-cart.pem, ca-key.pem, server-cert.pem, server-key.pem,

    :param path: defines path to directory which will be created
    :param cacert_subj: ca-cert.pem subject
    :param server_key.csr subject
    :param passphrase - passphrase to ca-key.pem
    :param secure = False - defines if the server-key.pem will use a passphrase
    :param bits = 1024: bit length of keys
    :param days = 1095: cert expiration

    :raise ValueError: openssl not found or rc != 0
    :raise OSError: if os.makedirs() fails
    """

    ssl_cmd = os_dep.command("openssl")
    path = path + os.path.sep  # Add separator to the path
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path)

    server_key = "server-key.pem.secure"
    if secure:
        server_key = "server-key.pem"

    cmd_set = [
        ('%s genrsa -des3 -passout pass:%s -out %sca-key.pem %d' %
         (ssl_cmd, passphrase, path, bits)),
        ('%s req -new -x509 -days %d -key %sca-key.pem -passin pass:%s -out '
         '%sca-cert.pem -subj "%s"' %
         (ssl_cmd, days, path, passphrase, path, cacert_subj)),
        ('%s genrsa -out %s %d' % (ssl_cmd, path + server_key, bits)),
        ('%s req -new -key %s -out %s/server-key.csr -subj "%s"' %
         (ssl_cmd, path + server_key, path, server_subj)),
        ('%s x509 -req -passin pass:%s -days %d -in %sserver-key.csr -CA '
         '%sca-cert.pem -CAkey %sca-key.pem -set_serial 01 -out %sserver-cert.pem' %
         (ssl_cmd, passphrase, days, path, path, path, path))
    ]

    if not secure:
        cmd_set.append('%s rsa -in %s -out %sserver-key.pem' %
                       (ssl_cmd, path + server_key, path))

    for cmd in cmd_set:
        utils.run(cmd)
        logging.info(cmd)


def convert_ipv4_to_ipv6(ipv4):
    """
    Translates a passed in string of an ipv4 address to an ipv6 address.

    :param ipv4: a string of an ipv4 address
    """

    converted_ip = "::ffff:"
    split_ipaddress = ipv4.split('.')
    try:
        socket.inet_aton(ipv4)
    except socket.error:
        raise ValueError("ipv4 to be converted is invalid")
    if (len(split_ipaddress) != 4):
        raise ValueError("ipv4 address is not in dotted quad format")

    for index, string in enumerate(split_ipaddress):
        if index != 1:
            test = str(hex(int(string)).split('x')[1])
            if len(test) == 1:
                final = "0"
                final += test
                test = final
        else:
            test = str(hex(int(string)).split('x')[1])
            if len(test) == 1:
                final = "0"
                final += test + ":"
                test = final
            else:
                test += ":"
        converted_ip += test
    return converted_ip


def get_thread_cpu(thread):
    """
    Get the light weight process(thread) used cpus.

    :param thread: thread checked
    :type thread: string
    :return: A list include all cpus the thread used
    :rtype: list
    """
    cmd = "ps -o cpuid,lwp -eL | grep -w %s$" % thread
    cpu_thread = utils.system_output(cmd)
    if not cpu_thread:
        return []
    return list(set([_.strip().split()[0] for _ in cpu_thread.splitlines()]))


def get_pid_cpu(pid):
    """
    Get the process used cpus.

    :param pid: process id
    :type thread: string
    :return: A list include all cpus the process used
    :rtype: list
    """
    cmd = "ps -o cpuid -L -p %s" % pid
    cpu_pid = utils.system_output(cmd)
    if not cpu_pid:
        return []
    return list(set([_.strip() for _ in cpu_pid.splitlines()]))


def get_node_count():
    """
    Get the number of nodes of current host.

    :return: the number of nodes
    :rtype: string
    """
    cmd = utils.run("numactl --hardware")
    return int(re.findall("available: (\d+) nodes", cmd.stdout)[0])


def cpu_str_to_list(origin_str):
    """
    Convert the cpu string to a list. The string may include comma and
    hyphen.

    :param origin_str: the cpu info string read from system
    :type origin_str: string
    :return: A list of the cpu ids
    :rtype: list
    """
    if isinstance(origin_str, str):
        cpu_list = []
        for cpu in origin_str.strip().split(","):
            if "-" in cpu:
                start, end = cpu.split("-")
                for cpu_id in range(int(start), int(end) + 1):
                    cpu_list.append(cpu_id)
            else:
                try:
                    cpu_id = int(cpu)
                    cpu_list.append(cpu_id)
                except ValueError:
                    logging.error("Illegimate string in cpu "
                                  "informations: %s" % cpu)
                    cpu_list = []
                    break
        cpu_list.sort()
        return cpu_list


class NumaInfo(object):

    """
    Numa topology for host. Also provide the function for check the memory status
    of the node.
    """

    def __init__(self):
        self.numa_sys_path = "/sys/devices/system/node"
        self.all_nodes = self.get_all_nodes()
        self.online_nodes = self.get_online_nodes()
        self.nodes = {}
        self.distances = {}
        for node_id in self.online_nodes:
            self.nodes[node_id] = NumaNode(node_id + 1)
            self.distances[node_id] = self.get_node_distance(node_id)

    def get_all_nodes(self):
        """
        Get all node ids in host.

        :return: All node ids in host
        :rtype: list
        """
        all_nodes = get_path(self.numa_sys_path, "possible")
        all_nodes_file = open(all_nodes, "r")
        nodes_info = all_nodes_file.read()
        all_nodes_file.close()

        return cpu_str_to_list(nodes_info)

    def get_online_nodes(self):
        """
        Get node ids online in host

        :return: The ids of node which is online
        :rtype: list
        """
        online_nodes = get_path(self.numa_sys_path, "online")
        online_nodes_file = open(online_nodes, "r")
        nodes_info = online_nodes_file.read()
        online_nodes_file.close()

        return cpu_str_to_list(nodes_info)

    def get_node_distance(self, node_id):
        """
        Get the distance from the give node to other nodes include itself.

        :param node_id: Node that you want to check
        :type node_id: string
        :return: A list in of distance for the node in positive-sequence
        :rtype: list
        """
        cmd = utils.run("numactl --hardware")
        node_distances = cmd.stdout.split("node distances:")[-1].strip()
        node_distance = node_distances.splitlines()[node_id + 1]
        if "%s:" % node_id not in node_distance:
            logging.warn("Get wrong unexpect information from numctl")
            numa_sys_path = self.numa_sys_path
            distance_path = get_path(numa_sys_path,
                                     "node%s/distance" % node_id)
            if not os.path.isfile(distance_path):
                logging.error("Can not get distance information for"
                              " node %s" % node_id)
                return []
            node_distance_file = open(distance_path, 'r')
            node_distance = node_distance_file.read()
            node_distance_file.close()
        else:
            node_distance = node_distance.split(":")[-1]

        return node_distance.strip().split()

    def read_from_node_meminfo(self, node_id, key):
        """
        Get specific value of a given node from memoinfo file

        :param node_id: The node you want to check
        :type node_id: string
        :param key: The value you want to check such as MemTotal etc.
        :type key: string
        :return: The value in KB
        :rtype: string
        """
        memory_path = os.path.join(self.numa_sys_path,
                                   "node%s/meminfo" % node_id)
        memory_file = open(memory_path, "r")
        memory_info = memory_file.read()
        memory_file.close()

        return re.findall("%s:\s+(\d+)" % key, memory_info)[0]


class NumaNode(object):

    """
    Numa node to control processes and shared memory.
    """

    def __init__(self, i=-1):
        self.num = get_node_count()
        if i < 0:
            self.cpus = self.get_node_cpus(int(self.num) + i).split()
            self.node_id = self.num + i
        else:
            self.cpus = self.get_node_cpus(i - 1).split()
            self.node_id = i - 1
        self.dict = {}
        for i in self.cpus:
            self.dict[i] = "free"

    def get_node_cpus(self, i):
        """
        Get cpus of a specific node

        :param i: Index of the CPU inside the node.
        """
        cmd = utils.run("numactl --hardware")
        cpus = re.findall("node %s cpus: (.*)" % i, cmd.stdout)
        if cpus:
            cpus = cpus[0]
        else:
            break_flag = False
            cpulist_path = "/sys/devices/system/node/node%s/cpulist" % i
            try:
                cpulist_file = open(cpulist_path, 'r')
                cpus = cpulist_file.read()
                cpulist_file.close()
            except IOError:
                logging.warn("Can not find the cpu list information from both"
                             "numactl and sysfs. Please check your system.")
                break_flag = True
            if not break_flag:
                # Try to expand the numbers with '-' to a string of numbers
                # separated by blank. There number of '-' in the list depends
                # on the physical architecture of the hardware.
                try:
                    convert_list = re.findall("\d+-\d+", cpus)
                    for cstr in convert_list:
                        _ = " "
                        start = min(int(cstr.split("-")[0]),
                                    int(cstr.split("-")[1]))
                        end = max(int(cstr.split("-")[0]),
                                  int(cstr.split("-")[1]))
                        for n in range(start, end + 1, 1):
                            _ += "%s " % str(n)
                        cpus = re.sub(cstr, _, cpus)
                except (IndexError, ValueError):
                    logging.warn("The format of cpu list is not the same as"
                                 " expected.")
                    break_flag = False
            if break_flag:
                cpus = ""

        return cpus

    def free_cpu(self, i):
        """
        Release pin of one node.

        :param i: Index of the node.
        """
        self.dict[i] = "free"

    def _flush_pin(self):
        """
        Flush pin dict, remove the record of exited process.
        """
        cmd = utils.run("ps -eLf | awk '{print $4}'")
        all_pids = cmd.stdout
        for i in self.cpus:
            if self.dict[i] != "free" and self.dict[i] not in all_pids:
                self.free_cpu(i)

    @error.context_aware
    def pin_cpu(self, process):
        """
        Pin one process to a single cpu.

        :param process: Process ID.
        """
        self._flush_pin()
        error.context("Pinning process %s to the CPU" % process)
        for i in self.cpus:
            if self.dict[i] == "free":
                self.dict[i] = str(process)
                cmd = "taskset -p %s %s" % (hex(2 ** int(i)), process)
                logging.debug("NumaNode (%s): " % i + cmd)
                utils.run(cmd)
                return i

    def show(self):
        """
        Display the record dict in a convenient way.
        """
        logging.info("Numa Node record dict:")
        for i in self.cpus:
            logging.info("    %s: %s" % (i, self.dict[i]))


def get_host_cpu_models():
    """
    Get cpu model from host cpuinfo
    """
    def _cpu_flags_sort(cpu_flags):
        """
        Update the cpu flags get from host to a certain order and format
        """
        flag_list = re.split("\s+", cpu_flags.strip())
        flag_list.sort()
        cpu_flags = " ".join(flag_list)
        return cpu_flags

    def _make_up_pattern(flags):
        """
        Update the check pattern to a certain order and format
        """
        pattern_list = re.split(",", flags.strip())
        pattern_list.sort()
        pattern = r"(\b%s\b)" % pattern_list[0]
        for i in pattern_list[1:]:
            pattern += r".+(\b%s\b)" % i
        return pattern

    if ARCH == 'ppc64':
        return ['POWER7']

    vendor_re = "vendor_id\s+:\s+(\w+)"
    cpu_flags_re = "flags\s+:\s+([\w\s]+)\n"

    cpu_types = {"AuthenticAMD": ["Opteron_G5", "Opteron_G4", "Opteron_G3",
                                  "Opteron_G2", "Opteron_G1"],
                 "GenuineIntel": ["SandyBridge", "Westmere", "Nehalem",
                                  "Penryn", "Conroe"]}
    cpu_type_re = {"Opteron_G5": "f16c,fma,tbm",
                   "Opteron_G4":
                   "avx,xsave,aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3,sse4a",
                   "Opteron_G3": "cx16,sse4a",
                   "Opteron_G2": "cx16",
                   "Opteron_G1": "",
                   "SandyBridge":
                   "avx,xsave,aes,sse4_2|sse4.2,sse4.1|sse4_1,cx16,ssse3",
                   "Westmere": "aes,sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Nehalem": "sse4.2|sse4_2,sse4.1|sse4_1,cx16,ssse3",
                   "Penryn": "sse4.1|sse4_1,cx16,ssse3",
                   "Conroe": "ssse3"}

    fd = open("/proc/cpuinfo")
    cpu_info = fd.read()
    fd.close()

    vendor = re.findall(vendor_re, cpu_info)[0]
    cpu_flags = re.findall(cpu_flags_re, cpu_info)

    cpu_model = None
    cpu_support_model = []
    if cpu_flags:
        cpu_flags = _cpu_flags_sort(cpu_flags[0])
        for cpu_type in cpu_types.get(vendor):
            pattern = _make_up_pattern(cpu_type_re.get(cpu_type))
            if re.findall(pattern, cpu_flags):
                cpu_model = cpu_type
                break
    else:
        logging.warn("Can not Get cpu flags from cpuinfo")

    if cpu_model:
        cpu_type_list = cpu_types.get(vendor)
        cpu_support_model = cpu_type_list[cpu_type_list.index(cpu_model):]

    return cpu_support_model


def extract_qemu_cpu_models(qemu_cpu_help_text):
    """
    Get all cpu models from qemu -cpu help text.

    :param qemu_cpu_help_text: text produced by <qemu> -cpu '?'
    :return: list of cpu models
    """
    def check_model_list(pattern):
        cpu_re = re.compile(pattern)
        qemu_cpu_model_list = cpu_re.findall(qemu_cpu_help_text)
        if qemu_cpu_model_list:
            return qemu_cpu_model_list
        else:
            return None

    x86_pattern_list = "x86\s+\[?([a-zA-Z0-9_-]+)\]?.*\n"
    ppc64_pattern_list = "PowerPC\s+\[?([a-zA-Z0-9_-]+\.?[0-9]?)\]?.*\n"

    for pattern_list in [x86_pattern_list, ppc64_pattern_list]:
        model_list = check_model_list(pattern_list)
        if model_list is not None:
            return model_list

    e_msg = ("CPU models reported by qemu -cpu ? not supported by virt-tests. "
             "Please work with us to add support for it")
    logging.error(e_msg)
    for line in qemu_cpu_help_text.splitlines():
        logging.error(line)
    raise UnsupportedCPU(e_msg)


def get_qemu_cpu_models(qemu_binary):
    """Get listing of CPU models supported by QEMU

    Get list of CPU models by parsing the output of <qemu> -cpu '?'
    """
    cmd = qemu_binary + " -cpu '?'"
    result = utils.run(cmd)
    return extract_qemu_cpu_models(result.stdout)


def get_qemu_binary(params):
    """
    Get the path to the qemu binary currently in use.
    """
    # Update LD_LIBRARY_PATH for built libraries (libspice-server)
    qemu_binary_path = get_path(os.path.join(data_dir.get_root_dir(),
                                             params.get("vm_type")),
                                params.get("qemu_binary", "qemu"))

    library_path = os.path.join(
        data_dir.get_root_dir(), params.get('vm_type'), 'install_root', 'lib')
    if os.path.isdir(library_path):
        library_path = os.path.abspath(library_path)
        qemu_binary = "LD_LIBRARY_PATH=%s %s" % (
            library_path, qemu_binary_path)
    else:
        qemu_binary = qemu_binary_path

    return qemu_binary


def get_qemu_img_binary(params):
    """
    Get the path to the qemu-img binary currently in use.
    """
    return get_path(os.path.join(data_dir.get_root_dir(),
                                 params.get("vm_type")),
                    params.get("qemu_img_binary", "qemu"))


def get_qemu_io_binary(params):
    """
    Get the path to the qemu-img binary currently in use.
    """
    return get_path(os.path.join(data_dir.get_root_dir(),
                                 params.get("vm_type")),
                    params.get("qemu_io_binary", "qemu"))


def get_qemu_best_cpu_model(params):
    """
    Try to find out the best CPU model available for qemu.

    This function can't be in qemu_vm, because it is used in env_process,
    where there's no vm object available yet, and env content is synchronized
    in multi host testing.

    1) Get host CPU model
    2) Verify if host CPU model is in the list of supported qemu cpu models
    3) If so, return host CPU model
    4) If not, return the default cpu model set in params, if none defined,
        return 'qemu64'.
    """
    host_cpu_models = get_host_cpu_models()
    qemu_binary = get_qemu_binary(params)
    qemu_cpu_models = get_qemu_cpu_models(qemu_binary)
    # Let's try to find a suitable model on the qemu list
    for host_cpu_model in host_cpu_models:
        if host_cpu_model in qemu_cpu_models:
            return host_cpu_model
    # If no host cpu model can be found on qemu_cpu_models, choose the default
    return params.get("default_cpu_model", "qemu64")


def check_if_vm_vcpu_match(vcpu_desire, vm):
    """
    This checks whether the VM vCPU quantity matches
    the value desired.
    """
    vcpu_actual = vm.get_cpu_count()
    if vcpu_desire != vcpu_actual:
        logging.debug("CPU quantity mismatched !!! guest said it got %s "
                      "but we assigned %s" % (vcpu_actual, vcpu_desire))
        return False
    logging.info("CPU quantity matched: %s" % vcpu_actual)
    return True


class ForAll(list):

    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            return map(lambda o: o.__getattribute__(name)(*args, **kargs), self)
        return wrapper


class ForAllP(list):

    """
    Parallel version of ForAll
    """

    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            threads = []
            for o in self:
                threads.append(
                    utils.InterruptedThread(o.__getattribute__(name),
                                            args=args, kwargs=kargs))
            for t in threads:
                t.start()
            return map(lambda t: t.join(), threads)
        return wrapper


class ForAllPSE(list):

    """
    Parallel version of and suppress exception.
    """

    def __getattr__(self, name):
        def wrapper(*args, **kargs):
            threads = []
            for o in self:
                threads.append(
                    utils.InterruptedThread(o.__getattribute__(name),
                                            args=args, kwargs=kargs))
            for t in threads:
                t.start()

            result = []
            for t in threads:
                ret = {}
                try:
                    ret["return"] = t.join()
                except Exception:
                    ret["exception"] = sys.exc_info()
                    ret["args"] = args
                    ret["kargs"] = kargs
                result.append(ret)
            return result
        return wrapper


def get_pid_path(program_name, pid_files_dir=None):
    if not pid_files_dir:
        base_dir = os.path.dirname(__file__)
        pid_path = os.path.abspath(os.path.join(base_dir, "..", "..",
                                                "%s.pid" % program_name))
    else:
        pid_path = os.path.join(pid_files_dir, "%s.pid" % program_name)

    return pid_path


def write_pid(program_name, pid_files_dir=None):
    """
    Try to drop <program_name>.pid in the main autotest directory.

    Args:
      program_name: prefix for file name
    """
    pidfile = open(get_pid_path(program_name, pid_files_dir), "w")
    try:
        pidfile.write("%s\n" % os.getpid())
    finally:
        pidfile.close()


def delete_pid_file_if_exists(program_name, pid_files_dir=None):
    """
    Tries to remove <program_name>.pid from the main autotest directory.
    """
    pidfile_path = get_pid_path(program_name, pid_files_dir)

    try:
        os.remove(pidfile_path)
    except OSError:
        if not os.path.exists(pidfile_path):
            return
        raise


def get_pid_from_file(program_name, pid_files_dir=None):
    """
    Reads the pid from <program_name>.pid in the autotest directory.

    :param program_name the name of the program
    :return: the pid if the file exists, None otherwise.
    """
    pidfile_path = get_pid_path(program_name, pid_files_dir)
    if not os.path.exists(pidfile_path):
        return None

    pidfile = open(get_pid_path(program_name, pid_files_dir), 'r')

    try:
        try:
            pid = int(pidfile.readline())
        except IOError:
            if not os.path.exists(pidfile_path):
                return None
            raise
    finally:
        pidfile.close()

    return pid


def program_is_alive(program_name, pid_files_dir=None):
    """
    Checks if the process is alive and not in Zombie state.

    :param program_name the name of the program
    :return: True if still alive, False otherwise
    """
    pid = get_pid_from_file(program_name, pid_files_dir)
    if pid is None:
        return False
    return utils.pid_is_alive(pid)


def signal_program(program_name, sig=signal.SIGTERM, pid_files_dir=None):
    """
    Sends a signal to the process listed in <program_name>.pid

    :param program_name the name of the program
    :param sig signal to send
    """
    pid = get_pid_from_file(program_name, pid_files_dir)
    if pid:
        utils.signal_pid(pid, sig)


def normalize_data_size(value_str, order_magnitude="M", factor="1024"):
    """
    Normalize a data size in one order of magnitude to another (MB to GB,
    for example).

    :param value_str: a string include the data and unit
    :param order_magnitude: the magnitude order of result
    :param factor: the factor between two relative order of magnitude.
                   Normally could be 1024 or 1000
    """
    def _get_magnitude_index(magnitude_list, magnitude_value):
        for i in magnitude_list:
            order_magnitude = re.findall("[\s\d](%s)" % i,
                                         str(magnitude_value), re.I)
            if order_magnitude:
                return magnitude_list.index(order_magnitude[0].upper())
        return -1

    magnitude_list = ['B', 'K', 'M', 'G', 'T']
    try:
        data = float(re.findall("[\d\.]+", value_str)[0])
    except IndexError:
        logging.error("Incorrect data size format. Please check %s"
                      " has both data and unit." % value_str)
        return ""

    magnitude_index = _get_magnitude_index(magnitude_list, value_str)
    order_magnitude_index = _get_magnitude_index(magnitude_list,
                                                 " %s" % order_magnitude)

    if magnitude_index < 0 or order_magnitude_index < 0:
        logging.error("Unknown input order of magnitude. Please check your"
                      "value '%s' and desired order of magnitude"
                      " '%s'." % (value_str, order_magnitude))
        return ""

    if magnitude_index > order_magnitude_index:
        multiple = float(factor)
    else:
        multiple = float(factor) ** -1

    for _ in range(abs(magnitude_index - order_magnitude_index)):
        data *= multiple

    return str(data)


def verify_running_as_root():
    """
    Verifies whether we're running under UID 0 (root).

    :raise: error.TestNAError
    """
    if os.getuid() != 0:
        raise error.TestNAError("This test requires root privileges "
                                "(currently running with user %s)" %
                                getpass.getuser())


def selinux_enforcing():
    """
    Returns True if SELinux is in enforcing mode, False if permissive/disabled
    """
    cmdresult = utils.run('getenforce', ignore_status=True, verbose=False)
    mobj = re.search('Enforcing', cmdresult.stdout)
    return mobj is not None


def get_winutils_vol(session, label="WIN_UTILS"):
    """
    Return Volum ID of winutils CDROM;ISO file should be create via command:
    mkisofs -V $label -o winutils.iso

    @parm session: session Object
    @parm label:volum ID of WIN_UTILS.iso

    :return: volum ID
    """
    cmd = "wmic logicaldisk where (VolumeName='%s') get DeviceID" % label
    output = session.cmd(cmd, timeout=120)
    device = re.search(r'(\w):', output, re.M)
    if not device:
        return ""
    return device.group(1)


def valued_option_dict(options, split_pattern, start_count=0, dict_split=None):
    """
    Divide the valued options into key and value

    :param options: the valued options get from cfg
    :param split_pattern: patten used to split options
    :param dict_split: patten used to split sub options and insert into dict
    :param start_count: the start_count to insert option_dict
    :return: dict include option and its value
    """
    option_dict = {}
    if options.strip() is not None:
        pat = re.compile(split_pattern)
        option_list = pat.split(options.lstrip(split_pattern))
        logging.debug("option_list is %s", option_list)

        for match in option_list[start_count:]:
            match_list = match.split(dict_split)
            if len(match_list) == 2:
                key = match_list[0]
                value = match_list[1]
                if not key in option_dict:
                    option_dict[key] = value
                else:
                    logging.debug("key %s in option_dict", key)
                    option_dict[key] = option_dict[key].split()
                    option_dict[key].append(value)

    return option_dict
