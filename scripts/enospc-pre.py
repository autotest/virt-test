#!/usr/bin/python
"""
Simple script to setup enospc test environment
"""
import os, commands, sys

SCRIPT_DIR = os.path.dirname(sys.modules[__name__].__file__)
KVM_TEST_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

class SetupError(Exception):
    """
    Simple wrapper for the builtin Exception class.
    """
    pass


def find_command(cmd):
    """
    Searches for a command on common paths, error if it can't find it.

    @param cmd: Command to be found.
    """
    if os.path.exists(cmd):
        return cmd
    for dir in ["/usr/local/sbin", "/usr/local/bin",
                "/usr/sbin", "/usr/bin", "/sbin", "/bin"]:
        file = os.path.join(dir, cmd)
        if os.path.exists(file):
            return file
    raise ValueError('Missing command: %s' % cmd)


def run(cmd, info=None):
    """
    Run a command and throw an exception if it fails.
    Optionally, you can provide additional contextual info.

    @param cmd: Command string.
    @param reason: Optional string that explains the context of the failure.

    @raise: SetupError if command fails.
    """
    print "Running '%s'" % cmd
    cmd_name = cmd.split(' ')[0]
    find_command(cmd_name)
    status, output = commands.getstatusoutput(cmd)
    if status:
        e_msg = ('Command %s failed.\nStatus:%s\nOutput:%s' %
                 (cmd, status, output))
        if info is not None:
            e_msg += '\nAdditional Info:%s' % info
        raise SetupError(e_msg)

    return (status, output.strip())


if __name__ == "__main__":
    qemu_img_binary = os.environ['KVM_TEST_qemu_img_binary']
    if not os.path.isabs(qemu_img_binary):
        qemu_img_binary = os.path.join(KVM_TEST_DIR, qemu_img_binary)
    if not os.path.exists(qemu_img_binary):
        raise SetupError('The qemu-img binary that is supposed to be used '
                         '(%s) does not exist. Please verify your '
                         'configuration' % qemu_img_binary)

    run("%s create -f raw /tmp/enospc.raw 10G" % qemu_img_binary)
    status, loopback_device = run("losetup -f")
    run("losetup -f /tmp/enospc.raw")
    run("pvcreate %s" % loopback_device)
    run("vgcreate vgtest %s" % loopback_device)
    run("lvcreate -L200M -n lvtest vgtest")
    run("%s create -f qcow2 /dev/vgtest/lvtest 10G" % qemu_img_binary)

    kvm_dir = os.path.join(os.environ['AUTODIR'], 'tests/kvm')

    run("ln -s /dev/vgtest/lvtest %s.%s" % (
        os.path.join(kvm_dir, os.environ['KVM_TEST_image_name_stg']),
        os.environ['KVM_TEST_image_format_stg']))
