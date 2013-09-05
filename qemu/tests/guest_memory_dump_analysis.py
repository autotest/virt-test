"""
Integrity test of a big guest vmcore, using the dump-guest-memory QMP
command and the "crash" utility.

:copyright: 2013 Red Hat, Inc.
:author: Laszlo Ersek <lersek@redhat.com>

Related RHBZ: https://bugzilla.redhat.com/show_bug.cgi?id=990118
"""

import logging
from virttest.aexpect import ShellCmdError
from autotest.client.shared import error
import string
import os
import gzip
import threading

REQ_GUEST_MEM    = 4096        # exact size of guest RAM required
REQ_GUEST_ARCH   = "x86_64"    # the only supported guest arch
REQ_GUEST_DF     = 6144        # minimum guest disk space required
                               #     after package installation
LONG_TIMEOUT     = 10*60       # timeout for long operations
VMCORE_BASE      = "vmcore"    # basename of the host-side file the
                               #     guest vmcore is written to, .gz
                               #     suffix will be appended. No
                               #     metacharacters or leading dashes
                               #     please.
VMCORE_FD_NAME   = "vmcore_fd" # fd identifier used in the monitor
CRASH_SCRIPT     = "crash.cmd" # guest-side filename of the minimal
                               # crash script

def run_guest_memory_dump_analysis(test, params, env):
    """
    Verify the vmcore written by dump-guest-memory by a big guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def check_requirements(vm, session):
        """
        Check guest RAM size and guest architecture.

        :param vm: virtual machine.
        :param session: login shell session.
        :raise: error.TestError if the test is misconfigured.
        """
        mem_size = vm.get_memory_size()
        if (mem_size != REQ_GUEST_MEM):
            raise error.TestError("the guest must have %d MB RAM exactly "
                                  "(current: %d MB)" % (REQ_GUEST_MEM,
                                                        mem_size))
        arch = session.cmd("uname -m").rstrip()
        if (arch != REQ_GUEST_ARCH):
            raise error.TestError("this test only supports %s guests "
                                  "(current: %s)" % (REQ_GUEST_ARCH, arch))

    def install_kernel_debuginfo(vm, session, login_timeout):
        """
        In the guest, install a kernel debuginfo package that matches
        the running kernel.

        Debuginfo packages are available for the most recent kernels
        only, so this step may need a kernel upgrade and a corresponding
        VM reboot. Also, the "debuginfo-install" yum utility is not good
        enough for this, because its exit status doesn't seem to reflect
        any failure to find a matching debuginfo package. Only "yum
        install" seems to do that, and only if an individual package is
        requested.

        :param vm: virtual machine. Can be None if the caller demands a
                debuginfo package for the running kernel.
        :param session: login shell session.
        :param login_timeout: passed to vm.reboot() as timeout. Can be
                None if vm is None.
        :return: If the debuginfo package has been successfully
                installed, None is returned. If no debuginfo package
                matching the running guest kernel is available.
                If vm is None, an exception is raised; otherwise, the
                guest kernel is upgraded, and a new session is returned
                for the rebooted guest. In this case the next call to
                this function should succeed, using the new session and
                with vm=None.
        :raise: error.TestError (guest uname command failed),
                ShellCmdError (unexpected guest yum command failure),
                exceptions from vm.reboot().
        """
        def install_matching_debuginfo(session):
            try:
                guest_kernel = session.cmd("uname -r").rstrip()
            except ShellCmdError, details:
                raise error.TestError("guest uname command failed: %s" %
                                      details)
            return session.cmd("yum -y install --enablerepo='*debuginfo' "
                               "kernel-debuginfo-%s" % guest_kernel,
                               timeout=LONG_TIMEOUT)

        try:
            output = install_matching_debuginfo(session)
            logging.debug("%s", output)
            new_sess = None
        except ShellCmdError, details:
            if (vm is None):
                raise
            logging.info("failed to install matching debuginfo, "
                         "upgrading kernel")
            logging.debug("shell error was: %s", details)
            output = session.cmd("yum -y upgrade kernel",
                                 timeout=LONG_TIMEOUT)
            logging.debug("%s", output)
            new_sess = vm.reboot(session, timeout=login_timeout)
        return new_sess

    def install_crash(session):
        """
        Install the "crash" utility in the guest.

        :param session: login shell session.
        :raise: exceptions from session.cmd().
        """
        output = session.cmd("yum -y install crash")
        logging.debug("%s", output)

    def check_disk_space(session):
        """
        Check free disk space in the guest before uploading,
        uncompressing and analyzing the vmcore.

        :param session: login shell session.
        :raise: exceptions from session.cmd(); error.TestError if free
                space is insufficient.
        """
        output = session.cmd("rm -f -v %s %s.gz" % (VMCORE_BASE, VMCORE_BASE))
        logging.debug("%s", output)
        output = session.cmd("yum clean all")
        logging.debug("%s", output)
        output = session.cmd("LC_ALL=C df --portability --block-size=1M .")
        logging.debug("%s", output)
        df_megs = int(string.split(output)[10])
        if (df_megs < REQ_GUEST_DF):
            raise error.TestError("insufficient free disk space: %d < %d" %
                                  (df_megs, REQ_GUEST_DF))

    def dump_and_compress(qmp_monitor, vmcore_host):
        """
        Dump the guest vmcore on the host side and compress it.

        Use the "dump-guest-memory" QMP command with paging=false. Start
        a new Python thread that compresses data from a file descriptor
        to a host file. Create a pipe and pass its writeable end to qemu
        for vmcore dumping. Pass the pipe's readable end (with full
        ownership) to the compressor thread. Track references to the
        file descriptions underlying the pipe end fds carefully.

        Compressing the vmcore on the fly, then copying it to the guest,
        then decompressing it inside the guest should be much faster
        than dumping and copying a huge plaintext vmcore, especially on
        rotational media.

        :param qmp_monitor: QMP monitor for the guest.
        :param vmcore_host: absolute pathname of gzipped destination
                file.
        :raise: all sorts of exceptions. No resources should be leaked.
        """
        def compress_from_fd(input_fd, gzfile):
            # Run in a separate thread, take ownership of input_fd.
            try:
                buf = os.read(input_fd, 4096)
                while (buf):
                    gzfile.write(buf)
                    buf = os.read(input_fd, 4096)
            finally:
                # If we've run into a problem, this causes an EPIPE in
                # the qemu process, preventing it from blocking in
                # write() forever.
                os.close(input_fd)

        def dump_vmcore(qmp_monitor, vmcore_fd):
            # Temporarily create another reference to vmcore_fd, in the
            # qemu process. We own the duplicate.
            qmp_monitor.cmd(cmd="getfd",
                            args={"fdname": "%s" % VMCORE_FD_NAME},
                            fd=vmcore_fd)
            try:
                # Includes ownership transfer on success, no need to
                # call the "closefd" command then.
                qmp_monitor.cmd(cmd="dump-guest-memory",
                                args={"paging": False,
                                      "protocol": "fd:%s" % VMCORE_FD_NAME},
                                timeout=LONG_TIMEOUT)
            except:
                qmp_monitor.cmd(cmd="closefd",
                                args={"fdname": "%s" % VMCORE_FD_NAME})
                raise

        gzfile = gzip.open(vmcore_host, "wb", 1)
        try:
            try:
                (read_by_gzip, written_by_qemu) = os.pipe()
                try:
                    compressor = threading.Thread(target=compress_from_fd,
                                                  name="compressor",
                                                  args=(read_by_gzip, gzfile))
                    compressor.start()
                    # Compressor running, ownership of readable end has
                    # been transferred.
                    read_by_gzip = -1
                    try:
                        dump_vmcore(qmp_monitor, written_by_qemu)
                    finally:
                        # Close Python's own reference to the writeable
                        # end as well, so that the compressor can
                        # experience EOF before we try to join it.
                        os.close(written_by_qemu)
                        written_by_qemu = -1
                        compressor.join()
                finally:
                    if (read_by_gzip != -1):
                        os.close(read_by_gzip)
                    if (written_by_qemu != -1):
                        os.close(written_by_qemu)
            finally:
                # Close the gzipped file first, *then* delete it if
                # there was an error.
                gzfile.close()
        except:
            os.unlink(vmcore_host)
            raise

    def verify_vmcore(vm, session, host_compr, guest_compr, guest_plain):
        """
        Verify the vmcore with the "crash" utility in the guest.

        Standard output needs to be searched for "crash:" and "WARNING:"
        strings; the test is successful iff there are no matches and
        "crash" exits successfully.

        :param vm: virtual machine.
        :param session: login shell session.
        :param host_compr: absolute pathname of gzipped vmcore on host,
                source file.
        :param guest_compr: single-component filename of gzipped vmcore
                on guest, destination file.
        :param guest_plain: single-component filename of gunzipped
                vmcore on guest that guest-side gunzip is expected to
                create.
        :raise: vm.copy_files_to() and session.cmd() exceptions;
                error.TestFail if "crash" meets trouble in the vmcore.
        """
        vm.copy_files_to(host_compr, guest_compr)
        output = session.cmd("gzip -d -v %s" % guest_compr,
                             timeout=LONG_TIMEOUT)
        logging.debug("%s", output)

        session.cmd("{ echo bt; echo quit; } > %s" % CRASH_SCRIPT)
        output = session.cmd("crash -i %s "
                             "/usr/lib/debug/lib/modules/$(uname -r)/vmlinux "
                             "%s" % (CRASH_SCRIPT, guest_plain))
        logging.debug("%s", output)
        if (string.find(output, "crash:") >= 0 or
            string.find(output, "WARNING:") >= 0):
            raise error.TestFail("vmcore corrupt")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    qmp_monitor = vm.get_monitors_by_type("qmp")
    if qmp_monitor:
        qmp_monitor = qmp_monitor[0]
    else:
        raise error.TestError('Could not find a QMP monitor, aborting test')

    login_timeout = int(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=login_timeout)
    try:
        check_requirements(vm, session)

        new_sess = install_kernel_debuginfo(vm, session, login_timeout)
        if (new_sess is not None):
            session = new_sess
            install_kernel_debuginfo(None, session, None)

        install_crash(session)
        check_disk_space(session)

        vmcore_compr = "%s.gz" % VMCORE_BASE
        vmcore_host = os.path.join(test.tmpdir, vmcore_compr)
        dump_and_compress(qmp_monitor, vmcore_host)
        try:
            verify_vmcore(vm, session, vmcore_host, vmcore_compr, VMCORE_BASE)
        finally:
            os.unlink(vmcore_host)
    finally:
        session.close()
