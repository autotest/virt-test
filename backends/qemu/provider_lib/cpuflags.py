"""
Shared code for tests that make use of cpuflags
"""
import os
from virttest import data_dir


def install_cpuflags_util_on_vm(test, vm, dst_dir, extra_flags=None):
    """
    Install stress to vm.

    :param vm: virtual machine.
    :param dst_dir: Installation path.
    :param extra_flags: Extraflags for gcc compiler.
    """
    if not extra_flags:
        extra_flags = ""

    cpuflags_src = os.path.join(data_dir.get_deps_dir(), "cpu_flags")
    cpuflags_dst = os.path.join(dst_dir, "cpu_flags")
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
