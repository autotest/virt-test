"""
Virt-v2v test utility functions.

:copyright: 2008-2012 Red Hat Inc.
"""
import os
import re
import time
import logging
import ovirt
from utils_test import libvirt
from autotest.client import os_dep
from autotest.client import utils
import virsh
import ppm_utils
import data_dir
import remote
import libvirt_vm as lvirt

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
        self.input_mode = self.params.get('input_mode')
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

        if self.input_mode is not None:
            options = " -i %s %s" % (self.input_mode, options)
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
        self.os_version = params.get("os_version")
        self.os_type = params.get('os_type', 'linux')
        self.target = params.get('target')
        self.username = params.get('vm_user', 'root')
        self.password = params.get('vm_pwd')
        self.nic_index = params.get('nic_index', 0)
        self.export_name = params.get('export_name')
        self.delete_vm = 'yes' == params.get('vm_cleanup', 'yes')
        self.virsh_session_id = params.get("virsh_session_id")
        self.pool_type = params.get("pool_type", "dir")
        self.pool_name = params.get("pool_name", "v2v_test")
        self.target_path = params.get("target_path", "pool_path")
        self.emulated_img = params.get("emulated_image_path",
                                       "v2v-emulated-img")
        # Need create session after create the instance
        self.session = None

        if self.name is None:
            logging.error("vm name not exist")

        # libvirt is a default target
        if self.target == "libvirt" or self.target is None:
            self.vm = lvirt.VM(self.name, self.params, self.test.bindir,
                               self.env.get("address_cache"))
            self.pv = libvirt.PoolVolumeTest(test, params)
        elif self.target == "ovirt":
            self.vm = ovirt.VMManager(self.params, self.test.bindir,
                                      self.env.get("address_cache"))
        else:
            raise ValueError("Doesn't support %s target now" % self.target)

    def create_session(self, timeout=480):
        self.session = self.vm.wait_for_login(nic_index=self.nic_index,
                                              timeout=timeout,
                                              username=self.username,
                                              password=self.password)

    def cleanup(self):
        """
        Cleanup VM and remove all of storage files about guest
        """
        if self.vm.is_alive():
            self.vm.destroy(gracefully=False)
            time.sleep(5)

        if self.target == "libvirt":
            if self.vm.exists() and self.vm.is_persistent():
                self.vm.undefine()
                self.pv.cleanup_pool(self.pool_name, self.pool_type,
                                     self.target_path, self.emulated_img)

        if self.target == "ovirt":
            self.vm.delete()
            self.vm.delete_from_export_domain(self.export_name)

    def storage_cleanup(self):
        """
        Cleanup storage pool and volume
        """
        raise NotImplementedError


class LinuxVMCheck(VMCheck):

    """
    This class handles all basic linux VM check operations.
    """

    def get_vm_kernel(self):
        """
        Get vm kernel info.
        """
        cmd = "uname -r"
        output = self.session.cmd(cmd)
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def get_vm_os_info(self):
        """
        Get vm os info.
        """
        check_issue = False
        cmd = "cat /etc/os-release"
        status, output = self.session.cmd_status_output(cmd)
        if status != 0:
            cmd = "cat /etc/issue"
            output = self.session.cmd(cmd)
            check_issue = True
        logging.debug("%s output:\n%s", cmd, output)
        os_info = ""
        try:
            if check_issue:
                os_info = output.splitlines()[0]
            else:
                os_info = output.splitlines()[5].split('=')[1]
        except IndexError:
            logging.error("Fail to get os release info")
        return os_info

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
        output = self.session.cmd(cmd)
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def get_vm_modprobe_conf(self):
        """
        Get /etc/modprobe.conf content.
        """
        cmd = "cat /etc/modprobe.conf"
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def get_vm_modules(self):
        """
        Get vm modules list.
        """
        cmd = "lsmod"
        output = self.session.cmd(cmd)
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def get_vm_pci_list(self):
        """
        Get vm pci list.
        """
        cmd = "lspci"
        output = self.session.cmd(cmd)
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def get_vm_rc_local(self):
        """
        Get vm /etc/rc.local output.
        """
        cmd = "cat /etc/rc.local"
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def has_vmware_tools(self):
        """
        Check vmware tools.
        """
        cmd = "rpm -q VMwareTools"
        status, output = self.session.cmd_status_output(cmd)
        if status != 0:
            cmd = "ls /usr/bin/vmware-uninstall-tools.pl"
            status, output = self.session.cmd_status_output(cmd)
        logging.debug("%s output:\n%s", cmd, output)
        return status == 0

    def get_vm_tty(self):
        """
        Get vm tty config.
        """
        confs = ('/etc/securetty', '/etc/inittab', '/boot/grub/grub.conf',
                 '/etc/default/grub')
        all_output = ''
        for conf in confs:
            cmd = "cat " + conf
            output = self.session.cmd(cmd, ok_status=[0, 1])
            logging.debug("%s output:\n%s", cmd, output)
            all_output += output
        return all_output

    def get_vm_video(self):
        """
        Get vm video config.
        """
        cmd = "cat /etc/X11/xorg.conf /var/log/Xorg.0.log"
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        return output

    def is_net_virtio(self):
        """
        Check whether vm's interface is virtio
        """
        cmd = "ls -l /sys/class/net/eth%s/device" % self.nic_index
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        try:
            if re.search("virtio", output.split('/')[-1]):
                return True
        except IndexError:
            logging.error("Fail to find virtio driver")
        return False

    def is_disk_virtio(self, disk="/dev/vda"):
        """
        Check whether disk is virtio.
        """
        cmd = "fdisk -l %s" % disk
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        if re.search(disk, output):
            return True
        return False

    def get_grub_device(self, dev_map="/boot/grub2/device.map"):
        """
        Check whether vd[a-z] device is in device map.
        """
        cmd = "cat %s" % dev_map
        output = self.session.cmd(cmd, ok_status=[0, 1])
        logging.debug("%s output:\n%s", cmd, output)
        if re.search("vd[a-z]", output):
            return True
        return False


class WindowsVMCheck(VMCheck):

    """
    This class handles all basic Windows VM check operations.
    """

    def send_win32_key(self, keycode):
        """
        Send key to Windows VM
        """
        options = "--codeset win32 %s" % keycode
        virsh.sendkey(self.name, options, session_id=self.virsh_session_id)
        time.sleep(1)

    def move_mouse(self, coordinate):
        """
        Move VM mouse.
        """
        virsh.move_mouse(self.name, coordinate,
                         session_id=self.virsh_session_id)

    def click_left_button(self):
        """
        Click left button of VM mouse.
        """
        virsh.click_button(self.name, session_id=self.virsh_session_id)

    def click_tab_enter(self):
        """
        Send TAB and ENTER to VM.
        """
        self.send_win32_key('VK_TAB')
        self.send_win32_key('VK_RETURN')

    def click_install_driver(self):
        """
        Move mouse and click button to install dirver for new
        device(Ethernet controller)
        """
        # Get window focus by click left button
        self.move_mouse((0, -80))
        self.click_left_button()
        self.move_mouse((0, 30))
        self.click_left_button()

    def get_screenshot(self):
        """
        Do virsh screenshot of the vm and fetch the image if the VM in
        remote host.
        """
        sshot_file = os.path.join(data_dir.get_tmp_dir(), "vm_screenshot.ppm")
        if self.target == "ovirt":
            vm_sshot = "/tmp/vm_screenshot.ppm"
        else:
            vm_sshot = sshot_file
        virsh.screenshot(self.name, vm_sshot, session_id=self.virsh_session_id)
        if self.target == "ovirt":
            remote_ip = self.params.get("remote_ip")
            remote_user = self.params.get("remote_user")
            remote_pwd = self.params.get("remote_pwd")
            remote.scp_from_remote(remote_ip, '22', remote_user,
                                   remote_pwd, vm_sshot, sshot_file)
            r_runner = remote.RemoteRunner(host=remote_ip, username=remote_user,
                                           password=remote_pwd)
            r_runner.run("rm -f %s" % vm_sshot)
        return sshot_file

    def wait_for_match(self, images, similar_degree=0.98, timeout=300):
        """
        Compare VM screenshot with given images, if any image in the list
        matched, then return the image index, or return -1.
        """
        end_time = time.time() + timeout
        image_matched = False
        cropped_image = os.path.join(data_dir.get_tmp_dir(), "croped.ppm")
        while time.time() < end_time:
            vm_screenshot = self.get_screenshot()
            ppm_utils.image_crop_save(vm_screenshot, vm_screenshot)
            img_index = 0
            for image in images:
                logging.debug("Compare vm screenshot with image %s", image)
                ppm_utils.image_crop_save(image, cropped_image)
                h_degree = ppm_utils.image_histogram_compare(cropped_image,
                                                             vm_screenshot)
                if h_degree >= similar_degree:
                    logging.debug("Image %s matched", image)
                    image_matched = True
                    break
                img_index += 1
            if image_matched:
                break
            time.sleep(1)
        if os.path.exists(cropped_image):
            os.unlink(cropped_image)
        if os.path.exists(vm_screenshot):
            os.unlink(vm_screenshot)
        if image_matched:
            return img_index
        else:
            return -1

    def init_windows(self, timeout=300):
        """
        Click buttons to active windows latest and install
        ethernet controller driver.
        """
        logging.info("Initialize windows in %s seconds", timeout)
        compare_screenshot_vms = ["win2003", "win2008", "win2008r2", "win7"]
        timeout_msg = "Not match expected images in %s" % timeout
        timeout_msg += " seconds, try to login VM directly"
        match_image_list = []
        if self.os_version in compare_screenshot_vms:
            image_name_list = self.params.get("images_for_match", '').split(',')
            for image_name in image_name_list:
                match_image = os.path.join(data_dir.get_data_dir(), image_name)
                if not os.path.exists(match_image):
                    logging.error("Init windows quit as '%s' not exist",
                                  match_image)
                    return
                match_image_list.append(match_image)
            img_match_ret = self.wait_for_match(match_image_list,
                                                timeout=timeout)
            if img_match_ret < 0:
                logging.error(timeout_msg)
            else:
                if self.os_version == "win2003":
                    if img_match_ret == 0:
                        self.click_left_button()
                        # VM may have no response in awhile
                        time.sleep(20)
                        self.click_left_button()
                        self.click_tab_enter()
                    elif img_match_ret == 1:
                        self.click_left_button()
                        time.sleep(20)
                        self.click_left_button()
                        self.click_tab_enter()
                        self.click_left_button()
                        self.send_win32_key('VK_RETURN')
                    else:
                        pass
                elif self.os_version in ["win7", "win2008r2"]:
                    if img_match_ret in [0, 1]:
                        self.click_left_button()
                        self.click_left_button()
                        self.send_win32_key('VK_TAB')
                        self.click_tab_enter()
                elif self.os_version == "win2008":
                    if img_match_ret in [0, 1]:
                        self.click_tab_enter()
                        self.click_install_driver()
                        self.move_mouse((0, -50))
                        self.click_left_button()
                        self.click_tab_enter()
                    else:
                        self.click_install_driver()
        else:
            # No need sendkey/click button for Win8, Win8.1, Win2012, Win2012r2
            logging.info("%s is booting up without program intervention",
                         self.os_version)


    def reboot_windows(self):
        """
        Reboot Windows immediately
        """
        logging.debug("Reboot windows")
        cmd = "shutdown -t 0 -r -f"
        self.session.cmd(cmd)

    def get_viostor_info(self):
        """
        Get viostor info.
        """
        cmd = "dir C:\Windows\Drivers\VirtIO\\viostor.sys"
        status, output = self.session.cmd_status_output(cmd)
        if status == 0:
            logging.debug("The viostor info is: %s", output)
            return output

    def get_driver_info(self, signed=True):
        """
        Get windows signed driver info.
        """
        cmd = "DRIVERQUERY"
        if signed:
            cmd += " /SI"
        status, output = self.session.cmd_status_output(cmd)
        if status == 0:
            logging.debug("Windows drivers info: %s", output)
            return output

    def get_windows_event_info(self):
        """
        Get windows event log info about WSH.
        """
        cmd = "CSCRIPT C:\WINDOWS\system32\eventquery.vbs /l application /Fi \"Source eq WSH\""
        status, output = self.session.cmd_status_output(cmd)
        if status != 0:
            #if the OS version was not win2003 or winXP, use following cmd
            cmd = "wevtutil qe application | find \"WSH\""
            output = self.session.cmd(cmd)
        logging.debug("The windows event log info about WSH is: %s", output)
        return output

    def get_network_restart(self):
        """
        Get windows network restart.
        """
        cmd = "ipconfig /renew"
        status, output = self.session.cmd_status_output(cmd)
        if status == 0:
            logging.debug("The windows network restart info is: %s", output)
            return output

    def copy_windows_file(self):
        """
        Copy a widnows file
        """
        cmd = "COPY /y C:\\rss.reg C:\\rss.reg.bak"
        status, _ = self.session.cmd_status_output(cmd)
        logging.debug("Copy a windows file status is : %s", status)
        return status

    def delete_windows_file(self):
        """
        Delete a widnows file
        """
        cmd = "DEL C:\rss.reg.bak"
        status, _ = self.session.cmd_status_output(cmd)
        logging.debug("Delete a windows file status is : %s", status)
        return status


def v2v_cmd(params):
    """
    Append 'virt-v2v' and execute it.

    :param params: A dictionary includes all of required parameters such as
                    'target', 'hypervisor' and 'hostname', etc.
    :return: A CmdResult object
    """
    if V2V_EXEC is None:
        raise ValueError('Missing command: virt-v2v')

    target = params.get('target')
    hypervisor = params.get('hypervisor')
    hostname = params.get('hostname')
    vpx_dc = params.get('vpx_dc')
    esx_ip = params.get('esx_ip')
    opts_extra = params.get('v2v_opts')
    v2v_timeout = params.get('v2v_timeout', 2400)

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
    cmd_result = utils.run(cmd, timeout=v2v_timeout, verbose=True)
    return cmd_result


def import_vm_to_ovirt(params, address_cache, timeout=600):
    """
    Import VM from export domain to oVirt Data Center
    """
    os_type = params.get('os_type')
    export_name = params.get('export_name')
    storage_name = params.get('storage_name')
    cluster_name = params.get('cluster_name')
    # Check oVirt status
    dc = ovirt.DataCenterManager(params)
    logging.info("Current data centers list: %s", dc.list())
    cm = ovirt.ClusterManager(params)
    logging.info("Current cluster list: %s", cm.list())
    hm = ovirt.HostManager(params)
    logging.info("Current host list: %s", hm.list())
    sdm = ovirt.StorageDomainManager(params)
    logging.info("Current storage domain list: %s", sdm.list())
    vm = ovirt.VMManager(params, address_cache)
    logging.info("Current VM list: %s", vm.list())
    wait_for_up = True
    if os_type == 'windows':
        wait_for_up = False
    try:
        # Import VM
        vm.import_from_export_domain(export_name,
                                     storage_name,
                                     cluster_name,
                                     timeout=timeout)
        logging.info("The latest VM list: %s", vm.list())
    except Exception, e:
        # Try to delete the vm from export domain
        vm.delete_from_export_domain(export_name)
        logging.error("Import %s failed: %s", vm.name, e)
        return False
    try:
        # Start VM
        vm.start(wait_for_up=wait_for_up)
    except Exception, e:
        logging.error("Start %s failed: %s", vm.name, e)
        return False
    return True
