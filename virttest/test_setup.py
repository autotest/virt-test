"""
Library to perform pre/post test setup for KVM autotest.
"""
import os
import logging
import time
import re
import random
import commands
import math
from autotest.client.shared import error, utils
from autotest.client import kvm_control, os_dep
import utils_misc

try:
    from virttest.staging import utils_memory
except ImportError:
    from autotest.client import utils_memory


class THPError(Exception):

    """
    Base exception for Transparent Hugepage setup.
    """
    pass


class THPNotSupportedError(THPError):

    """
    Thrown when host does not support tansparent hugepages.
    """
    pass


class THPWriteConfigError(THPError):

    """
    Thrown when host does not support tansparent hugepages.
    """
    pass


class THPKhugepagedError(THPError):

    """
    Thrown when khugepaged is not behaving as expected.
    """
    pass


class TransparentHugePageConfig(object):

    def __init__(self, test, params):
        """
        Find paths for transparent hugepages and kugepaged configuration. Also,
        back up original host configuration so it can be restored during
        cleanup.
        """
        self.params = params

        RH_THP_PATH = "/sys/kernel/mm/redhat_transparent_hugepage"
        UPSTREAM_THP_PATH = "/sys/kernel/mm/transparent_hugepage"
        if os.path.isdir(RH_THP_PATH):
            self.thp_path = RH_THP_PATH
        elif os.path.isdir(UPSTREAM_THP_PATH):
            self.thp_path = UPSTREAM_THP_PATH
        else:
            raise THPNotSupportedError("System doesn't support transparent "
                                       "hugepages")

        tmp_list = []
        test_cfg = {}
        test_config = self.params.get("test_config", None)
        if test_config is not None:
            tmp_list = re.split(';', test_config)
        while len(tmp_list) > 0:
            tmp_cfg = tmp_list.pop()
            test_cfg[re.split(":", tmp_cfg)[0]] = re.split(":", tmp_cfg)[1]
        # Save host current config, so we can restore it during cleanup
        # We will only save the writeable part of the config files
        original_config = {}
        # List of files that contain string config values
        self.file_list_str = []
        # List of files that contain integer config values
        self.file_list_num = []
        logging.info("Scanning THP base path and recording base values")
        for f in os.walk(self.thp_path):
            base_dir = f[0]
            if f[2]:
                for name in f[2]:
                    f_dir = os.path.join(base_dir, name)
                    parameter = file(f_dir, 'r').read()
                    logging.debug("Reading path %s: %s", f_dir,
                                  parameter.strip())
                    try:
                        # Verify if the path in question is writable
                        f = open(f_dir, 'w')
                        f.close()
                        if re.findall("\[(.*)\]", parameter):
                            original_config[f_dir] = re.findall("\[(.*)\]",
                                                                parameter)[0]
                            self.file_list_str.append(f_dir)
                        else:
                            original_config[f_dir] = int(parameter)
                            self.file_list_num.append(f_dir)
                    except IOError:
                        pass

        self.test_config = test_cfg
        self.original_config = original_config

    def set_env(self):
        """
        Applies test configuration on the host.
        """
        if self.test_config:
            logging.info("Applying custom THP test configuration")
            for path in self.test_config.keys():
                logging.info("Writing path %s: %s", path,
                             self.test_config[path])
                file(path, 'w').write(self.test_config[path])

    def value_listed(self, value):
        """
        Get a parameters list from a string
        """
        value_list = []
        for i in re.split("\[|\]|\n+|\s+", value):
            if i:
                value_list.append(i)
        return value_list

    def khugepaged_test(self):
        """
        Start, stop and frequency change test for khugepaged.
        """
        def check_status_with_value(action_list, file_name):
            """
            Check the status of khugepaged when set value to specify file.
            """
            for (a, r) in action_list:
                logging.info("Writing path %s: %s, expected khugepage rc: %s ",
                             file_name, a, r)
                try:
                    file_object = open(file_name, "w")
                    file_object.write(a)
                    file_object.close()
                except IOError, error_detail:
                    logging.info("IO Operation on path %s failed: %s",
                                 file_name, error_detail)
                time.sleep(5)
                try:
                    utils.run('pgrep khugepaged', verbose=False)
                    if r != 0:
                        raise THPKhugepagedError("Khugepaged still alive when"
                                                 "transparent huge page is "
                                                 "disabled")
                except error.CmdError:
                    if r == 0:
                        raise THPKhugepagedError("Khugepaged could not be set to"
                                                 "status %s" % a)

        logging.info("Testing khugepaged")
        for file_path in self.file_list_str:
            action_list = []
            if re.findall("enabled", file_path):
                # Start and stop test for khugepaged
                value_list = self.value_listed(open(file_path, "r").read())
                for i in value_list:
                    if re.match("n", i, re.I):
                        action_stop = (i, 256)
                for i in value_list:
                    if re.match("[^n]", i, re.I):
                        action = (i, 0)
                        action_list += [action_stop, action, action_stop]
                action_list += [action]

                check_status_with_value(action_list, file_path)
            else:
                value_list = self.value_listed(open(file_path, "r").read())
                for i in value_list:
                    action = (i, 0)
                    action_list.append(action)
                check_status_with_value(action_list, file_path)

        for file_path in self.file_list_num:
            action_list = []
            file_object = open(file_path, "r")
            value = file_object.read()
            value = int(value)
            file_object.close()
            if value != 0 and value != 1:
                new_value = random.random()
                action_list.append((str(int(value * new_value)), 0))
                action_list.append((str(int(value * (new_value + 1))), 0))
            else:
                action_list.append(("0", 0))
                action_list.append(("1", 0))

            check_status_with_value(action_list, file_path)

    def setup(self):
        """
        Configure host for testing. Also, check that khugepaged is working as
        expected.
        """
        self.set_env()
        self.khugepaged_test()

    def cleanup(self):
        """:
        Restore the host's original configuration after test
        """
        logging.info("Restoring host's original THP configuration")
        for path in self.original_config:
            logging.info("Writing path %s: %s", path,
                         self.original_config[path])
            try:
                p_file = open(path, 'w')
                p_file.write(str(self.original_config[path]))
                p_file.close()
            except IOError, error_detail:
                logging.info("IO operation failed on file %s: %s", path,
                             error_detail)


class HugePageConfig(object):

    def __init__(self, params):
        """
        Gets environment variable values and calculates the target number
        of huge memory pages.

        :param params: Dict like object containing parameters for the test.
        """
        self.vms = len(params.objects("vms"))
        self.mem = int(params.get("mem"))
        self.max_vms = int(params.get("max_vms", 0))
        self.qemu_overhead = int(params.get("hugepages_qemu_overhead", 128))
        self.deallocate = params.get("hugepages_deallocate", "yes") == "yes"
        self.hugepage_path = '/mnt/kvm_hugepage'
        self.kernel_hp_file = '/proc/sys/vm/nr_hugepages'
        self.hugepage_size = self.get_hugepage_size()
        self.hugepage_force_allocate = params.get("hugepage_force_allocate",
                                                  "no")
        self.suggest_mem = None
        self.lowest_mem_per_vm = int(params.get("lowest_mem", "256"))

        target_hugepages = params.get("target_hugepages")
        if target_hugepages is None:
            target_hugepages = self.get_target_hugepages()
        else:
            target_hugepages = int(target_hugepages)

        self.target_hugepages = target_hugepages

    def get_hugepage_size(self):
        """
        Get the current system setting for huge memory page size.
        """
        meminfo = open('/proc/meminfo', 'r').readlines()
        huge_line_list = [h for h in meminfo if h.startswith("Hugepagesize")]
        try:
            return int(huge_line_list[0].split()[1])
        except ValueError, e:
            raise ValueError("Could not get huge page size setting from "
                             "/proc/meminfo: %s" % e)

    def get_target_hugepages(self):
        """
        Calculate the target number of hugepages for testing purposes.
        """
        if self.vms < self.max_vms:
            self.vms = self.max_vms
        # memory of all VMs plus qemu overhead of 128MB per guest
        # (this value can be overriden in your cartesian config)
        vmsm = self.vms * (self.mem + self.qemu_overhead)
        target_hugepages = int(vmsm * 1024 / self.hugepage_size)

        # FIXME Now the buddyinfo can not get chunk info which is bigger
        # than 4M. So this will only fit for 2M size hugepages. Can not work
        # when hugepage size is 1G.
        # And sometimes huge page can not get all pages so decrease the page
        # for about 10 huge page to make sure the allocate can success

        decreased_pages = 10
        if self.hugepage_size > 2048:
            self.hugepage_force_allocate = "yes"

        if self.hugepage_force_allocate == "no":
            hugepage_allocated = open(self.kernel_hp_file, "r")
            available_hugepages = int(hugepage_allocated.read().strip())
            hugepage_allocated.close()
            chunk_bottom = int(math.log(self.hugepage_size / 4, 2))
            chunk_info = utils_memory.get_buddy_info(">=%s" % chunk_bottom,
                                                     zones="DMA32 Normal")
            for size in chunk_info:
                available_hugepages += int(chunk_info[size] * math.pow(2,
                                           int(int(size) - chunk_bottom)))

            available_hugepages = available_hugepages - decreased_pages
            if target_hugepages > available_hugepages:
                logging.warn("This test requires more huge pages than we"
                             " currently have, we'll try to allocate the"
                             " biggest number the system can support.")
                target_hugepages = available_hugepages
                available_mem = available_hugepages * self.hugepage_size
                self.suggest_mem = int(available_mem / self.vms / 1024
                                       - self.qemu_overhead)
                if self.suggest_mem < self.lowest_mem_per_vm:
                    raise MemoryError("Sugguest memory %sM is too small for"
                                      " guest to boot up. Please check your"
                                      " host memory "
                                      "status." % self.suggest_mem)

        return target_hugepages

    @error.context_aware
    def set_hugepages(self):
        """
        Sets the hugepage limit to the target hugepage value calculated.
        """
        error.context("setting hugepages limit to %s" % self.target_hugepages)
        hugepage_cfg = open(self.kernel_hp_file, "r+")
        hp = hugepage_cfg.readline()
        while int(hp) < self.target_hugepages:
            loop_hp = hp
            hugepage_cfg.write(str(self.target_hugepages))
            hugepage_cfg.flush()
            hugepage_cfg.seek(0)
            hp = int(hugepage_cfg.readline())
            if loop_hp == hp:
                raise ValueError("Cannot set the kernel hugepage setting "
                                 "to the target value of %d hugepages." %
                                 self.target_hugepages)
        hugepage_cfg.close()
        logging.debug("Successfully set %s large memory pages on host ",
                      self.target_hugepages)

    @error.context_aware
    def mount_hugepage_fs(self):
        """
        Verify if there's a hugetlbfs mount set. If there's none, will set up
        a hugetlbfs mount using the class attribute that defines the mount
        point.
        """
        error.context("mounting hugepages path")
        if not os.path.ismount(self.hugepage_path):
            if not os.path.isdir(self.hugepage_path):
                os.makedirs(self.hugepage_path)
            cmd = "mount -t hugetlbfs none %s" % self.hugepage_path
            utils.system(cmd)

    def setup(self):
        logging.debug("Number of VMs this test will use: %d", self.vms)
        logging.debug("Amount of memory used by each vm: %s", self.mem)
        logging.debug("System setting for large memory page size: %s",
                      self.hugepage_size)
        logging.debug("Number of large memory pages needed for this test: %s",
                      self.target_hugepages)
        self.set_hugepages()
        self.mount_hugepage_fs()

        return self.suggest_mem

    @error.context_aware
    def cleanup(self):
        if self.deallocate:
            error.context("trying to dealocate hugepage memory")
            try:
                utils.system("umount %s" % self.hugepage_path)
            except error.CmdError:
                return
            utils.system("echo 0 > %s" % self.kernel_hp_file)
            logging.debug("Hugepage memory successfully dealocated")


class KSMError(Exception):

    """
    Base exception for KSM setup
    """
    pass


class KSMNotSupportedError(KSMError):

    """
    Thrown when host does not support KSM.
    """
    pass


class KSMConfigError(KSMError):

    """
    Thrown when host does not config KSM as expect.
    """
    pass


class KSMConfig(object):

    def __init__(self, params, env):
        """

        :param params: Dict like object containing parameters for the test.
        """
        KSM_PATH = "/sys/kernel/mm/ksm"

        self.pages_to_scan = params.get("ksm_pages_to_scan")
        self.sleep_ms = params.get("ksm_sleep_ms")
        self.run = params.get("ksm_run", "1")
        self.ksm_module = params.get("ksm_module")

        if self.run == "yes":
            self.run = "1"
        elif self.run == "no":
            self.run == "0"

        # Get KSM module status if there is one
        # Set the ksm_module_loaded to True in default as we consider it is
        # compiled into kernel
        self.ksm_module_loaded = True
        if self.ksm_module:
            status = utils.system("lsmod |grep ksm", ignore_status=True)
            if status != 0:
                self.ksm_module_loaded = False

        # load the ksm module for furthur information check
        if not self.ksm_module_loaded:
            utils.system("modprobe ksm")

        if os.path.isdir(KSM_PATH):
            self.interface = "sysfs"
            ksm_cmd = "cat /sys/kernel/mm/ksm/run;"
            ksm_cmd += " cat /sys/kernel/mm/ksm/pages_to_scan;"
            ksm_cmd += " cat /sys/kernel/mm/ksm/sleep_millisecs"
            self.ksm_path = KSM_PATH
        else:
            try:
                os_dep.command("ksmctl")
            except ValueError:
                raise KSMNotSupportedError
            self.interface = "ksmctl"
            ksm_cmd = "ksmctl info"
            # For ksmctl both pages_to_scan and sleep_ms should have value
            # So give some default value when it is not set up in params
            if self.pages_to_scan is None:
                self.pages_to_scan = "5000"
            if self.sleep_ms is None:
                self.sleep_ms = "50"

        self.ksmtuned_process = 0
        # Check if ksmtuned is running before the test
        ksmtuned_process = utils.system_output("ps -C ksmtuned -o pid=",
                                               ignore_status=True)
        if ksmtuned_process:
            self.ksmtuned_process = int(re.findall("\d+",
                                                   ksmtuned_process)[0])

        # As ksmtuned may update KSM config most of the time we should disable
        # it when we test KSM
        self.disable_ksmtuned = params.get("disable_ksmtuned", "yes") == "yes"

        output = utils.system_output(ksm_cmd)
        self.default_status = re.findall("\d+", output)
        if len(self.default_status) != 3:
            raise KSMError("Can not get KSM default setting: %s" % output)
        self.default_status.append(int(self.ksmtuned_process))
        self.default_status.append(self.ksm_module_loaded)

    def setup(self, env):
        if self.ksmtuned_process != 0 and self.disable_ksmtuned:
            kill_cmd = "kill -1 %s" % self.ksmtuned_process
            utils.system(kill_cmd)

        env.data["KSM_default_config"] = self.default_status
        ksm_cmd = ""
        if self.interface == "sysfs":
            if self.run != self.default_status[0]:
                ksm_cmd += " echo %s > KSM_PATH/run;" % self.run
            if (self.pages_to_scan
                    and self.pages_to_scan != self.default_status[1]):
                ksm_cmd += " echo %s > KSM_PATH" % self.pages_to_scan
                ksm_cmd += "/pages_to_scan;"
            if (self.sleep_ms
                    and self.sleep_ms != self.default_status[2]):
                ksm_cmd += " echo %s > KSM_PATH" % self.sleep_ms
                ksm_cmd += "/sleep_millisecs"
            ksm_cmd = re.sub("KSM_PATH", self.ksm_path, ksm_cmd)
        elif self.interface == "ksmctl":
            if self.run == "1":
                ksm_cmd += "ksmctl start %s %s" % (self.pages_to_scan,
                                                   self.sleep_ms)
            else:
                ksm_cmd += "ksmctl stop"

        utils.system(ksm_cmd)

    def cleanup(self, env):
        default_status = env.data.get("KSM_default_config")

        if default_status[3] != 0:
            # ksmtuned used to run in host. Start the process
            # and don't need set up the configures.
            utils.system("ksmtuned")
            return

        if default_status == self.default_status:
            # Nothing changed
            return

        ksm_cmd = ""
        if self.interface == "sysfs":
            if default_status[0] != self.default_status[0]:
                ksm_cmd += " echo %s > KSM_PATH/run;" % default_status[0]
            if default_status[1] != self.default_status[1]:
                ksm_cmd += " echo %s > KSM_PATH" % default_status[1]
                ksm_cmd += "/pages_to_scan;"
            if default_status[2] != self.default_status[2]:
                ksm_cmd += " echo %s > KSM_PATH" % default_status[2]
                ksm_cmd += "/sleep_millisecs"
            ksm_cmd = re.sub("KSM_PATH", self.ksm_path, ksm_cmd)
        elif self.interface == "ksmctl":
            if default_status[0] == "1":
                ksm_cmd += "ksmctl start %s %s" % (default_status[1],
                                                   default_status[2])
            else:
                ksm_cmd += "ksmctl stop"

        utils.system(ksm_cmd)

        if not default_status[4]:
            utils.system("modprobe -r ksm")


class PrivateBridgeError(Exception):

    def __init__(self, brname):
        self.brname = brname

    def __str__(self):
        return "Bridge %s not available after setup" % self.brname


class PrivateBridgeConfig(object):
    __shared_state = {}

    def __init__(self, params=None):
        self.__dict__ = self.__shared_state
        if params is not None:
            self.brname = params.get("priv_brname", 'atbr0')
            self.subnet = params.get("priv_subnet", '192.168.58')
            self.ip_version = params.get("bridge_ip_version", "ipv4")
            self.dhcp_server_pid = None
            ports = params.get("priv_bridge_ports", '53 67').split()
            s_port = params.get("guest_port_remote_shell", "10022")
            if s_port not in ports:
                ports.append(s_port)
            ft_port = params.get("guest_port_file_transfer", "10023")
            if ft_port not in ports:
                ports.append(ft_port)
            u_port = params.get("guest_port_unattended_install", "13323")
            if u_port not in ports:
                ports.append(u_port)
            self.iptables_rules = self._assemble_iptables_rules(ports)
            self.physical_nic = params.get("physical_nic")
            self.force_create = False
            if params.get("bridge_force_create", "no") == "yes":
                self.force_create = True

    def _assemble_iptables_rules(self, port_list):
        rules = []
        index = 0
        for port in port_list:
            index += 1
            rules.append("INPUT %s -i %s -p tcp --dport %s -j ACCEPT" %
                         (index, self.brname, port))
            index += 1
            rules.append("INPUT %s -i %s -p udp --dport %s -j ACCEPT" %
                         (index, self.brname, port))
        rules.append("FORWARD 1 -m physdev --physdev-is-bridged -j ACCEPT")
        rules.append("FORWARD 2 -d %s.0/24 -o %s -m state "
                     "--state RELATED,ESTABLISHED -j ACCEPT" %
                     (self.subnet, self.brname))
        rules.append("FORWARD 3 -s %s.0/24 -i %s -j ACCEPT" %
                     (self.subnet, self.brname))
        rules.append("FORWARD 4 -i %s -o %s -j ACCEPT" %
                     (self.brname, self.brname))
        return rules

    def _add_bridge(self):
        utils.system("brctl addbr %s" % self.brname)
        ip_fwd_path = "/proc/sys/net/%s/ip_forward" % self.ip_version
        ip_fwd = open(ip_fwd_path, "w")
        ip_fwd.write("1\n")
        utils.system("brctl stp %s on" % self.brname)
        utils.system("brctl setfd %s 4" % self.brname)
        if self.physical_nic:
            utils.system("brctl addif %s %s" % (self.brname,
                                                self.physical_nic))

    def _bring_bridge_up(self):
        utils.system("ifconfig %s %s.1 up" % (self.brname, self.subnet))

    def _iptables_add(self, cmd):
        return utils.system("iptables -I %s" % cmd)

    def _iptables_del(self, cmd):
        return utils.system("iptables -D %s" % cmd)

    def _enable_nat(self):
        for rule in self.iptables_rules:
            self._iptables_add(rule)

    def _start_dhcp_server(self):
        utils.system("service dnsmasq stop")
        utils.system("dnsmasq --strict-order --bind-interfaces "
                     "--listen-address %s.1 --dhcp-range %s.2,%s.254 "
                     "--dhcp-lease-max=253 "
                     "--dhcp-no-override "
                     "--pid-file=/tmp/dnsmasq.pid "
                     "--log-facility=/tmp/dnsmasq.log" %
                     (self.subnet, self.subnet, self.subnet))
        self.dhcp_server_pid = None
        try:
            self.dhcp_server_pid = int(open('/tmp/dnsmasq.pid', 'r').read())
        except ValueError:
            raise PrivateBridgeError(self.brname)
        logging.debug("Started internal DHCP server with PID %s",
                      self.dhcp_server_pid)

    def _verify_bridge(self):
        brctl_output = utils.system_output("brctl show")
        if self.brname not in brctl_output:
            raise PrivateBridgeError(self.brname)

    def setup(self):
        brctl_output = utils.system_output("brctl show")
        if self.brname in brctl_output and self.force_create:
            self._bring_bridge_down()
            self._remove_bridge()
            brctl_output = utils.system_output("brctl show")
        if self.brname not in brctl_output:
            logging.info("Configuring KVM test private bridge %s", self.brname)
            try:
                self._add_bridge()
            except:
                self._remove_bridge()
                raise
            try:
                self._bring_bridge_up()
            except:
                self._bring_bridge_down()
                self._remove_bridge()
                raise
            try:
                self._enable_nat()
            except:
                self._disable_nat()
                self._bring_bridge_down()
                self._remove_bridge()
                raise
            try:
                self._start_dhcp_server()
            except:
                self._stop_dhcp_server()
                self._disable_nat()
                self._bring_bridge_down()
                self._remove_bridge()
                raise
            # Fix me the physical_nic always down after setup
            # Need manually up.
            if self.physical_nic:
                time.sleep(5)
                utils.system("ifconfig %s up" % self.physical_nic)

            self._verify_bridge()

    def _stop_dhcp_server(self):
        if self.dhcp_server_pid is not None:
            try:
                os.kill(self.dhcp_server_pid, 15)
            except OSError:
                pass
        else:
            try:
                dhcp_server_pid = int(open('/tmp/dnsmasq.pid', 'r').read())
            except ValueError:
                return
            try:
                os.kill(dhcp_server_pid, 15)
            except OSError:
                pass

    def _bring_bridge_down(self):
        utils.system("ifconfig %s down" % self.brname, ignore_status=True)

    def _disable_nat(self):
        for rule in self.iptables_rules:
            split_list = rule.split(' ')
            # We need to remove numbering here
            split_list.pop(1)
            rule = " ".join(split_list)
            self._iptables_del(rule)

    def _remove_bridge(self):
        utils.system("brctl delbr %s" % self.brname, ignore_status=True)

    def cleanup(self):
        brctl_output = utils.system_output("brctl show")
        cleanup = False
        for line in brctl_output.split("\n"):
            if line.startswith(self.brname):
                # len == 4 means there is a TAP using the bridge
                # so don't try to clean it up
                if len(line.split()) < 4:
                    cleanup = True
                    break
        if cleanup:
            logging.debug(
                "Cleaning up KVM test private bridge %s", self.brname)
            self._stop_dhcp_server()
            self._disable_nat()
            self._bring_bridge_down()
            self._remove_bridge()


class PciAssignable(object):

    """
    Request PCI assignable devices on host. It will check whether to request
    PF (physical Functions) or VF (Virtual Functions).
    """

    def __init__(self, driver=None, driver_option=None, host_set_flag=None,
                 kvm_params=None, vf_filter_re=None, pf_filter_re=None):
        """
        Initialize parameter 'type' which could be:
        vf: Virtual Functions
        pf: Physical Function (actual hardware)
        mixed:  Both includes VFs and PFs

        If pass through Physical NIC cards, we need to specify which devices
        to be assigned, e.g. 'eth1 eth2'.

        If pass through Virtual Functions, we need to specify max vfs in driver
        e.g. max_vfs = 7 in config file.

        :param type: PCI device type.
        :param driver: Kernel module for the PCI assignable device.
        :param driver_option: Module option to specify the maximum number of
                VFs (eg 'max_vfs=7')
        :param names: Physical NIC cards correspondent network interfaces,
                e.g.'eth1 eth2 ...'
        :param host_set_flag: Flag for if the test should setup host env:
               0: do nothing
               1: do setup env
               2: do cleanup env
               3: setup and cleanup env
        :param kvm_params: a dict for kvm module parameters default value
        :param vf_filter_re: Regex used to filter vf from lspci.
        :param pf_filter_re: Regex used to filter pf from lspci.
        """
        self.type_list = []
        self.driver = driver
        self.driver_option = driver_option
        self.name_list = []
        self.devices_requested = 0
        self.dev_unbind_drivers = {}
        self.dev_drivers = {}
        self.vf_filter_re = vf_filter_re
        self.pf_filter_re = pf_filter_re
        if host_set_flag is not None:
            self.setup = int(host_set_flag) & 1 == 1
            self.cleanup = int(host_set_flag) & 2 == 2
        else:
            self.setup = False
            self.cleanup = False
        self.kvm_params = kvm_params
        self.auai_path = None
        if self.kvm_params is not None:
            for i in self.kvm_params:
                if "allow_unsafe_assigned_interrupts" in i:
                    self.auai_path = i

    def add_device(self, device_type="vf", name=None):
        """
        Add device type and name to class.

        :param device_type: vf/pf device is added.
        :param name:  Device name is need.
        """
        self.type_list.append(device_type)
        if name is not None:
            self.name_list.append(name)
        self.devices_requested += 1

    def _get_pf_pci_id(self, name, search_str):
        """
        Get the PF PCI ID according to name.

        :param name: Name of the PCI device.
        :param search_str: Search string to be used on lspci.
        """
        cmd = "ethtool -i %s | awk '/bus-info/ {print $2}'" % name
        s, pci_id = commands.getstatusoutput(cmd)
        if not (s or "Cannot get driver information" in pci_id):
            return pci_id[5:]
        cmd = "lspci | awk '/%s/ {print $1}'" % search_str
        pci_ids = [i for i in commands.getoutput(cmd).splitlines()]
        nic_id = int(re.search('[0-9]+', name).group(0))
        if (len(pci_ids) - 1) < nic_id:
            return None
        return pci_ids[nic_id]

    @error.context_aware
    def _release_dev(self, pci_id):
        """
        Release a single PCI device.

        :param pci_id: PCI ID of a given PCI device.
        """
        base_dir = "/sys/bus/pci"
        full_id = utils_misc.get_full_pci_id(pci_id)
        vendor_id = utils_misc.get_vendor_from_pci_id(pci_id)
        drv_path = os.path.join(base_dir, "devices/%s/driver" % full_id)
        if 'pci-stub' in os.readlink(drv_path):
            error.context("Release device %s to host" % pci_id, logging.info)
            driver = self.dev_unbind_drivers[pci_id]
            cmd = "echo '%s' > %s/new_id" % (vendor_id, driver)
            logging.info("Run command in host: %s" % cmd)
            if os.system(cmd):
                return False

            stub_path = os.path.join(base_dir, "drivers/pci-stub")
            cmd = "echo '%s' > %s/unbind" % (full_id, stub_path)
            logging.info("Run command in host: %s" % cmd)
            if os.system(cmd):
                return False

            driver = self.dev_unbind_drivers[pci_id]
            cmd = "echo '%s' > %s/bind" % (full_id, driver)
            logging.info("Run command in host: %s" % cmd)
            if os.system(cmd):
                return False
        return True

    def get_vf_status(self, vf_id):
        """
        Check whether one vf is assigned to VM.

        vf_id: vf id to check.
        :return: Return True if vf has already assinged to VM. Else
        return false.
        """
        base_dir = "/sys/bus/pci"
        tub_path = os.path.join(base_dir, "drivers/pci-stub")
        vf_res_path = os.path.join(tub_path, "0000\:%s/resource*" % vf_id)
        cmd = "lsof %s" % vf_res_path
        output = utils.system_output(cmd, timeout=60, ignore_status=True)
        if 'qemu' in output:
            return True
        else:
            return False

    def get_vf_devs(self):
        """
        Catch all VFs PCI IDs.

        :return: List with all PCI IDs for the Virtual Functions available
        """
        if self.setup:
            if not self.sr_iov_setup():
                return []
        self.setup = None
        cmd = "lspci | awk '/%s/ {print $1}'" % self.vf_filter_re
        return utils.system_output(cmd, verbose=False).split()

    def get_pf_devs(self):
        """
        Catch all PFs PCI IDs.

        :return: List with all PCI IDs for the physical hardware requested
        """
        pf_ids = []
        for name in self.name_list:
            pf_id = self._get_pf_pci_id(name, "%s" % self.pf_filter_re)
            if not pf_id:
                continue
            pf_ids.append(pf_id)
        return pf_ids

    def get_devs(self, count, type_list=None):
        """
        Check out all devices' PCI IDs according to their name.

        :param count: count number of PCI devices needed for pass through
        :return: a list of all devices' PCI IDs
        """
        base_dir = "/sys/bus/pci"
        if type_list is None:
            type_list = self.type_list
        vf_ids = self.get_vf_devs()
        pf_ids = self.get_pf_devs()
        vf_d = []
        for pf_id in pf_ids:
            for vf_id in vf_ids:
                if vf_id[:2] == pf_id[:2] and\
                        (int(vf_id[-1]) & 1 == int(pf_id[-1])):
                    vf_d.append(vf_id)
        for vf_id in vf_ids:
            if self.get_vf_status(vf_id):
                vf_d.append(vf_id)
        for vf in vf_d:
            vf_ids.remove(vf)
        dev_ids = []
        for i in range(count):
            if type_list:
                try:
                    d_type = type_list[i]
                except IndexError:
                    d_type = "vf"
            if d_type == "vf":
                vf_id = vf_ids.pop(0)
                dev_ids.append(vf_id)
                self.dev_unbind_drivers[vf_id] = os.path.join(base_dir,
                                                              "drivers/%svf" % self.driver)
            elif d_type == "pf":
                pf_id = pf_ids.pop(0)
                dev_ids.append(pf_id)
                self.dev_unbind_drivers[pf_id] = os.path.join(base_dir,
                                                              "drivers/%s" % self.driver)
        if len(dev_ids) != count:
            logging.error("Did not get enough PCI Device")
        return dev_ids

    def get_vfs_count(self):
        """
        Get VFs count number according to lspci.
        """
        # FIXME: Need to think out a method of identify which
        # 'virtual function' belongs to which physical card considering
        # that if the host has more than one 82576 card. PCI_ID?
        cmd = "lspci | grep '%s' | wc -l" % self.vf_filter_re
        return int(utils.system_output(cmd, verbose=False))

    def check_vfs_count(self):
        """
        Check VFs count number according to the parameter driver_options.
        """
        # Network card 82576 has two network interfaces and each can be
        # virtualized up to 7 virtual functions, therefore we multiply
        # two for the value of driver_option 'max_vfs'.
        expected_count = int((re.findall("(\d)", self.driver_option)[0])) * 2
        return (self.get_vfs_count() == expected_count)

    def is_binded_to_stub(self, full_id):
        """
        Verify whether the device with full_id is already binded to pci-stub.

        :param full_id: Full ID for the given PCI device
        """
        base_dir = "/sys/bus/pci"
        stub_path = os.path.join(base_dir, "drivers/pci-stub")
        if os.path.exists(os.path.join(stub_path, full_id)):
            return True
        return False

    @error.context_aware
    def sr_iov_setup(self):
        """
        Ensure the PCI device is working in sr_iov mode.

        Check if the PCI hardware device drive is loaded with the appropriate,
        parameters (number of VFs), and if it's not, perform setup.

        :return: True, if the setup was completed successfully, False otherwise.
        """
        # Check if the host support interrupt remapping
        error.context("Set up host env for PCI assign test", logging.info)
        kvm_re_probe = False
        o = utils.system_output("cat /var/log/dmesg")
        ecap = re.findall("ecap\s+(.\w+)", o)

        if ecap and int(ecap[0], 16) & 8 == 0:
            if self.kvm_params is not None:
                if self.auai_path and self.kvm_params[self.auai_path] == "N":
                    kvm_re_probe = True
            else:
                kvm_re_probe = True
        # Try to re probe kvm module with interrupt remapping support
        if kvm_re_probe:
            kvm_arch = kvm_control.get_kvm_arch()
            utils.system("modprobe -r %s" % kvm_arch)
            utils.system("modprobe -r kvm")
            cmd = "modprobe kvm allow_unsafe_assigned_interrupts=1"
            if self.kvm_params is not None:
                for i in self.kvm_params:
                    if "allow_unsafe_assigned_interrupts" not in i:
                        if self.kvm_params[i] == "Y":
                            params_name = os.path.split(i)[1]
                            cmd += " %s=1" % params_name
            error.context("Loading kvm with: %s" % cmd, logging.info)

            try:
                utils.system(cmd)
            except Exception:
                logging.debug("Can not enable the interrupt remapping support")
            utils.system("modprobe %s" % kvm_arch)

        re_probe = False
        s, o = commands.getstatusoutput('lsmod | grep %s' % self.driver)
        if s:
            re_probe = True
        elif not self.check_vfs_count():
            os.system("modprobe -r %s" % self.driver)
            re_probe = True
        else:
            return True

        # Re-probe driver with proper number of VFs
        if re_probe:
            cmd = "modprobe %s %s" % (self.driver, self.driver_option)
            error.context("Loading the driver '%s' with command '%s'" %
                          (self.driver, cmd), logging.info)
            s, o = commands.getstatusoutput(cmd)
            utils.system("/etc/init.d/network restart", ignore_status=True)
            if s:
                return False
            return True

    def sr_iov_cleanup(self):
        """
        Clean up the sriov setup

        Check if the PCI hardware device drive is loaded with the appropriate,
        parameters (none of VFs), and if it's not, perform cleanup.

        :return: True, if the setup was completed successfully, False otherwise.
        """
        # Check if the host support interrupt remapping
        error.context("Clean up host env after PCI assign test", logging.info)
        kvm_re_probe = False
        if self.kvm_params is not None:
            if (self.auai_path and
               open(self.auai_path, "r").read().strip() == "Y"):
                if self.kvm_params and self.kvm_params[self.auai_path] == "N":
                    kvm_re_probe = True
        else:
            kvm_re_probe = True
        # Try to re probe kvm module with interrupt remapping support
        if kvm_re_probe:
            kvm_arch = kvm_control.get_kvm_arch()
            utils.system("modprobe -r %s" % kvm_arch)
            utils.system("modprobe -r kvm")
            cmd = "modprobe kvm"
            if self.kvm_params:
                for i in self.kvm_params:
                    if self.kvm_params[i] == "Y":
                        params_name = os.path.split(i)[1]
                        cmd += " %s=1" % params_name
            logging.info("Loading kvm with command: %s" % cmd)

            try:
                utils.system(cmd)
            except Exception:
                logging.debug("Failed to reload kvm")
            cmd = "modprobe %s" % kvm_arch
            logging.info("Loading %s with command: %s" % (kvm_arch, cmd))
            utils.system(cmd)

        re_probe = False
        s = commands.getstatusoutput('lsmod | grep %s' % self.driver)[0]
        if s:
            cmd = "modprobe -r %s" % self.driver
            logging.info("Running host command: %s" % cmd)
            os.system(cmd)
            re_probe = True
        else:
            return True

        # Re-probe driver with proper number of VFs
        if re_probe:
            cmd = "modprobe %s" % self.driver
            msg = "Loading the driver '%s' without option" % self.driver
            error.context(msg, logging.info)
            s = commands.getstatusoutput(cmd)[0]
            utils.system("/etc/init.d/network restart", ignore_status=True)
            if s:
                return False
            return True

    def request_devs(self, count=None):
        """
        Implement setup process: unbind the PCI device and then bind it
        to the pci-stub driver.

        :param count: count number of PCI devices needed for pass through

        :return: a list of successfully requested devices' PCI IDs.
        """
        if count is None:
            count = self.devices_requested
        base_dir = "/sys/bus/pci"
        stub_path = os.path.join(base_dir, "drivers/pci-stub")

        self.pci_ids = self.get_devs(count)
        logging.info("The following pci_ids were found: %s", self.pci_ids)
        requested_pci_ids = []

        # Setup all devices specified for assignment to guest
        for pci_id in self.pci_ids:
            full_id = utils_misc.get_full_pci_id(pci_id)
            if not full_id:
                continue
            drv_path = os.path.join(base_dir, "devices/%s/driver" % full_id)
            dev_prev_driver = os.path.realpath(os.path.join(drv_path,
                                               os.readlink(drv_path)))
            self.dev_drivers[pci_id] = dev_prev_driver

            # Judge whether the device driver has been binded to stub
            if not self.is_binded_to_stub(full_id):
                error.context("Bind device %s to stub" % full_id, logging.info)
                vendor_id = utils_misc.get_vendor_from_pci_id(pci_id)
                stub_new_id = os.path.join(stub_path, 'new_id')
                unbind_dev = os.path.join(drv_path, 'unbind')
                stub_bind = os.path.join(stub_path, 'bind')

                info_write_to_files = [(vendor_id, stub_new_id),
                                       (full_id, unbind_dev),
                                       (full_id, stub_bind)]

                for content, file in info_write_to_files:
                    try:
                        utils.open_write_close(file, content)
                    except IOError:
                        logging.debug("Failed to write %s to file %s", content,
                                      file)
                        continue

                if not self.is_binded_to_stub(full_id):
                    logging.error("Binding device %s to stub failed", pci_id)
                    continue
            else:
                logging.debug("Device %s already binded to stub", pci_id)
            requested_pci_ids.append(pci_id)
        return requested_pci_ids

    @error.context_aware
    def release_devs(self):
        """
        Release all PCI devices currently assigned to VMs back to the
        virtualization host.
        """
        try:
            for pci_id in self.dev_drivers:
                if not self._release_dev(pci_id):
                    logging.error(
                        "Failed to release device %s to host", pci_id)
                else:
                    logging.info("Released device %s successfully", pci_id)
            if self.cleanup:
                self.sr_iov_cleanup()
                self.type_list = []
                self.devices_requested = 0
                self.dev_unbind_drivers = {}
        except Exception:
            return
