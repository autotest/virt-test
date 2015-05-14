"""
Virt-v2v test utility functions.

:copyright: 2008-2012 Red Hat Inc.
"""

import os
import re
import time
import logging

import ovirt
import aexpect
from autotest.client import os_dep, utils
from autotest.client.shared import ssh_key

import libvirt_vm as lvirt

DEBUG = False

try:
    V2V_EXEC = os_dep.command('virt-v2v')
except ValueError:
    V2V_EXEC = None


class Uri(object):

    """
    This class is used for generating uri.
    """

    def __init__(self, hypervisor):
        if hypervisor is None:
            # kvm is a default hypervisor
            hypervisor = "kvm"
        self.hyper = hypervisor

    def get_uri(self, hostname, vpx_dc=None, esx_ip=None):
        """
        Uri dispatcher.

        :param hostname: String with host name.
        """
        uri_func = getattr(self, "_get_%s_uri" % self.hyper)
        self.host = hostname
        self.vpx_dc = vpx_dc
        self.esx_ip = esx_ip
        return uri_func()

    def _get_kvm_uri(self):
        """
        Return kvm uri.
        """
        uri = "qemu:///system"
        return uri

    def _get_xen_uri(self):
        """
        Return xen uri.
        """
        uri = "xen+ssh://" + self.host + "/"
        return uri

    def _get_esx_uri(self):
        """
        Return esx uri.
        """
        uri = "vpx://root@%s/%s/%s/?no_verify=1" % (self.host,
                                                    self.vpx_dc,
                                                    self.esx_ip)
        return uri

    # add new hypervisor in here.


class Target(object):

    """
    This class is used for generating command options.
    """

    def __init__(self, target, uri):
        if target is None:
            # libvirt is a default target
            target = "libvirt"
        self.tgt = target
        self.uri = uri

    def get_cmd_options(self, params):
        """
        Target dispatcher.
        """
        opts_func = getattr(self, "_get_%s_options" % self.tgt)
        self.params = params
        self.input = self.params.get('input')
        self.files = self.params.get('files')
        self.vm_name = self.params.get('main_vm')
        self.bridge = self.params.get('bridge')
        self.network = self.params.get('network')
        self.storage = self.params.get('storage')
        self.format = self.params.get('output_format', 'raw')
        self.net_vm_opts = ""

        if self.bridge:
            self.net_vm_opts += " -b %s" % self.bridge

        if self.network:
            self.net_vm_opts += " -n %s" % self.network

        self.net_vm_opts += " %s" % self.vm_name

        options = opts_func()

        if self.files is not None:
            # add files as its sequence
            file_list = self.files.split().reverse()
            for file in file_list:
                options = " -f %s %s " % (file, options)
        if self.input is not None:
            options = " -i %s %s" % (self.input, options)
        return options

    def _get_libvirt_options(self):
        """
        Return command options.
        """
        options = " -ic %s -os %s -of %s" % (self.uri,
                                             self.storage,
                                             self.format)
        options = options + self.net_vm_opts

        return options

    def _get_libvirtxml_options(self):
        """
        Return command options.
        """
        options = " -os %s" % self.storage
        options = options + self.net_vm_opts

        return options

    def _get_ovirt_options(self):
        """
        Return command options.
        """
        options = " -ic %s -o rhev -os %s -of %s" % (self.uri,
                                                     self.storage,
                                                     self.format)
        options = options + self.net_vm_opts

        return options

    # add new target in here.


class VMCheck(object):

    """
    This is VM check class dispatcher.
    """

    def __new__(cls, test, params, env):
        # 'linux' is default os type
        os_type = params.get('os_type', 'linux')

        if cls is VMCheck:
            class_name = eval(os_type.capitalize() + str(cls.__name__))
            return super(VMCheck, cls).__new__(class_name)
        else:
            return super(VMCheck, cls).__new__(cls, test, params, env)

    def __init__(self, test, params, env):
        self.vm = None
        self.test = test
        self.env = env
        self.params = params
        self.name = params.get('main_vm')
        self.target = params.get('target')
        self.username = params.get('vm_user', 'root')
        self.password = params.get('vm_pwd')
        self.timeout = params.get('timeout', 480)
        self.nic_index = params.get('nic_index', 0)
        self.export_name = params.get('export_name')
        self.delete_vm = 'yes' == params.get('vm_cleanup', 'yes')

        if self.name is None:
            logging.error("vm name not exist")

        # libvirt is a default target
        if self.target == "libvirt" or self.target is None:
            self.vm = lvirt.VM(self.name, self.params, self.test.bindir,
                               self.env.get("address_cache"))
        elif self.target == "ovirt":
            self.vm = ovirt.VMManager(self.params, self.test.bindir,
                                      self.env.get("address_cache"))
        else:
            raise ValueError("Doesn't support %s target now" % self.target)

        if self.vm.is_alive():
            self.vm.shutdown()
            self.vm.start()
        else:
            self.vm.start()

        logging.debug("Succeed to start '%s'", self.name)
        self.session = self.vm.wait_for_login(nic_index=self.nic_index,
                                              timeout=self.timeout,
                                              username=self.username,
                                              password=self.password)

    def vm_cleanup(self):
        """
        Cleanup VM including remove all storage files about guest
        """
        if self.vm.is_alive():
            self.vm.destroy()
            time.sleep(5)
        self.vm.delete()
        if self.target == "ovirt":
            self.vm.delete_from_export_domain(self.export_name)

    def __del__(self):
        """
        Cleanup test environment
        """
        if self.delete_vm:
            self.vm_cleanup()

        if self.session:
            self.session.close()


class LinuxVMCheck(VMCheck):

    """
    This class handles all basic linux VM check operations.
    """

    def get_vm_kernel(self):
        """
        Get vm kernel info.
        """
        cmd = "uname -r"
        kernel_version = self.session.cmd(cmd)
        logging.debug("The kernel of VM '%s' is: %s" %
                      (self.vm.name, kernel_version))
        return kernel_version

    def get_vm_os_info(self):
        """
        Get vm os info.
        """
        cmd = "cat /etc/os-release"
        try:
            output = self.session.cmd(cmd)
            output = output.split('\n')[5].split('=')[1]
        except aexpect.ShellError, e:
            cmd = "cat /etc/issue"
            output = self.session.cmd(cmd).split('\n', 1)[0]
        logging.debug("The os info is: %s" % output)
        return output

    def get_vm_os_vendor(self):
        """
        Get vm os vendor.
        """
        os_info = self.get_vm_os_info()
        if re.search('Red Hat', os_info):
            vendor = 'Red Hat'
        elif re.search('Fedora', os_info):
            vendor = 'Fedora Core'
        elif re.search('SUSE', os_info):
            vendor = 'SUSE'
        elif re.search('Ubuntu', os_info):
            vendor = 'Ubuntu'
        elif re.search('Debian', os_info):
            vendor = 'Debian'
        else:
            vendor = 'Unknown'
        logging.debug("The os vendor of VM '%s' is: %s" %
                      (self.vm.name, vendor))
        return vendor

    def get_vm_parted(self):
        """
        Get vm parted info.
        """
        cmd = "parted -l"
        parted_output = self.session.cmd(cmd)
        logging.debug("The parted output is:\n %s" % parted_output)
        return parted_output

    def get_vm_modprobe_conf(self):
        """
        Get /etc/modprobe.conf info.
        """
        cmd = "cat /etc/modprobe.conf"
        modprobe_output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("modprobe conf is:\n %s" % modprobe_output)
        return modprobe_output

    def get_vm_modules(self):
        """
        Get vm modules list.
        """
        cmd = "lsmod"
        modules = self.session.cmd(cmd)
        logging.debug("VM modules list is:\n %s" % modules)
        return modules

    def get_vm_pci_list(self):
        """
        Get vm pci list.
        """
        cmd = "lspci"
        lspci_output = self.session.cmd(cmd)
        logging.debug("VM pci devices list is:\n %s" % lspci_output)
        return lspci_output

    def get_vm_rc_local(self):
        """
        Get vm /etc/rc.local output.
        """
        cmd = "cat /etc/rc.local"
        rc_output = self.session.cmd(cmd, ok_status=[0, 1])
        return rc_output

    def has_vmware_tools(self):
        """
        Check vmware tools.
        """
        rpm_cmd = "rpm -q VMwareTools"
        ls_cmd = "ls /usr/bin/vmware-uninstall-tools.pl"
        rpm_cmd_status = self.session.cmd_status(rpm_cmd)
        ls_cmd_status = self.session.cmd_status(ls_cmd)

        if (rpm_cmd_status == 0 or ls_cmd_status == 0):
            return True
        else:
            return False

    def get_vm_tty(self):
        """
        Get vm tty config.
        """
        confs = ('/etc/securetty', '/etc/inittab', '/boot/grub/grub.conf',
                 '/etc/default/grub')
        tty = ''
        for conf in confs:
            cmd = "cat " + conf
            tty += self.session.cmd(cmd, ok_status=[0, 1])
        return tty

    def get_vm_video(self):
        """
        Get vm video config.
        """
        cmd = "cat /etc/X11/xorg.conf /var/log/Xorg.0.log"
        xorg_output = self.session.cmd(cmd, ok_status=[0, 1])
        return xorg_output

    def is_net_virtio(self):
        """
        Check whether vm's interface is virtio
        """
        cmd = "ls -l /sys/class/net/eth%s/device" % self.nic_index
        driver_output = self.session.cmd(cmd, ok_status=[0, 1])

        if re.search("virtio", driver_output.split('/')[-1]):
            return True
        return False

    def is_disk_virtio(self, disk="/dev/vda"):
        """
        Check whether disk is virtio.
        """
        cmd = "fdisk -l %s" % disk
        disk_output = self.session.cmd(cmd, ok_status=[0, 1])

        if re.search(disk, disk_output):
            return True
        return False

    def get_grub_device(self, dev_map="/boot/grub2/device.map"):
        """
        Check whether vd[a-z] device is in device map.
        """
        cmd = "grep -E '(sda|hda)' %s" % dev_map
        dev_output = self.session.cmd(cmd, ok_status=[0, 1])
        if dev_output:
            logging.info(dev_output)
            return False

        cmd = "grep -E 'vd[a-z]' %s" % dev_map
        dev_output = self.session.cmd(cmd, ok_status=[0, 1])
        if not dev_output:
            logging.info(dev_output)
            return False

        return True


class WindowsVMCheck(VMCheck):

    """
    This class handles all basic windows VM check operations.
    """
    pass


def v2v_cmd(params):
    """
    Append cmd to 'virt-v2v' and execute, optionally return full results.

    :param params: A dictionary includes all of required parameters such as
                    'target', 'hypervisor' and 'hostname', etc.
    :return: stdout of command
    """
    if V2V_EXEC is None:
        raise ValueError('Missing command: virt-v2v')

    target = params.get('target')
    hypervisor = params.get('hypervisor')
    hostname = params.get('hostname')
    vpx_dc = params.get('vpx_dc')
    esx_ip = params.get('esx_ip')
    opts_extra = params.get('v2v_opts')

    uri_obj = Uri(hypervisor)
    # Return actual 'uri' according to 'hostname' and 'hypervisor'
    uri = uri_obj.get_uri(hostname, vpx_dc, esx_ip)

    tgt_obj = Target(target, uri)
    # Return virt-v2v command line options based on 'target' and 'hypervisor'
    options = tgt_obj.get_cmd_options(params)

    if opts_extra:
        options = options + ' ' + opts_extra

    # Construct a final virt-v2v command
    cmd = '%s %s' % (V2V_EXEC, options)
    logging.debug('%s' % cmd)
    cmd_result = utils.run(cmd, verbose=DEBUG)
    return cmd_result
