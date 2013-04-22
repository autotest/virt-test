"""
Utility classes and functions to handle Virtual Machine creation using qemu.

@copyright: 2008-2009 Red Hat Inc.
"""

import time, os, logging, fcntl, re, commands
from autotest.client.shared import error
from autotest.client import utils
import utils_misc, virt_vm, test_setup, storage, qemu_monitor, aexpect
import qemu_virtio_port, remote, data_dir, utils_net

class QemuSegFaultError(virt_vm.VMError):
    def __init__(self, crash_message):
        virt_vm.VMError.__init__(self, crash_message)
        self.crash_message = crash_message

    def __str__(self):
        return ("Qemu crashed: %s" % self.crash_message)


class ImageUnbootableError(virt_vm.VMError):
    def __init__(self, name):
        virt_vm.VMError.__init__(self, name)
        self.name = name

    def __str__(self):
        return ("VM '%s' can't bootup from image" % self.name)


class VM(virt_vm.BaseVM):
    """
    This class handles all basic VM operations.
    """

    MIGRATION_PROTOS = ['tcp', 'unix', 'exec', 'fd']

    # By default we inherit all timeouts from the base VM class except...
    CLOSE_SESSION_TIMEOUT = 30

    def __init__(self, name, params, root_dir, address_cache, state=None):
        """
        Initialize the object and set a few attributes.

        @param name: The name of the object
        @param params: A dict containing VM params
                (see method make_qemu_command for a full description)
        @param root_dir: Base directory for relative filenames
        @param address_cache: A dict that maps MAC addresses to IP addresses
        @param state: If provided, use this as self.__dict__
        """

        if state:
            self.__dict__ = state
        else:
            self.process = None
            self.serial_console = None
            self.redirs = {}
            self.spice_options = {}
            self.vnc_port = 5900
            self.monitors = []
            self.virtio_ports = []      # virtio_console / virtio_serialport
            self.pci_assignable = None
            self.uuid = None
            self.vcpu_threads = []
            self.vhost_threads = []


        self.name = name
        self.params = params
        self.root_dir = root_dir
        self.address_cache = address_cache
        # This usb_dev_dict member stores usb controller and device info,
        # It's dict, each key is an id of usb controller,
        # and key's value is a list, contains usb devices' ids which
        # attach to this controller.
        # A filled usb_dev_dict may look like:
        # { "usb1" : ["stg1", "stg2", "stg3", "stg4", "stg5", "stg6"],
        #   "usb2" : ["stg7", "stg8"],
        #   ...
        # }
        # This structure can used in usb hotplug/unplug test.
        self.usb_dev_dict = {}
        self.logs = {}
        self.logsessions = {}
        self.driver_type = 'kvm'
        self.params['driver_type_'+self.name] = self.driver_type
        # virtnet init depends on vm_type/driver_type being set w/in params
        super(VM, self).__init__(name, params)
        # un-overwrite instance attribute, virtnet db lookups depend on this
        if state:
            self.instance = state['instance']
        self.qemu_command = ''


    def verify_alive(self):
        """
        Make sure the VM is alive and that the main monitor is responsive.

        @raise VMDeadError: If the VM is dead
        @raise: Various monitor exceptions if the monitor is unresponsive
        """
        self.verify_disk_image_bootable()
        self.verify_userspace_crash()
        self.verify_kernel_crash()
        self.verify_illegal_instruction()
        try:
            virt_vm.BaseVM.verify_alive(self)
            if self.monitors:
                self.monitor.verify_responsive()
        except virt_vm.VMDeadError:
            raise virt_vm.VMDeadError(self.process.get_status(),
                                      self.process.get_output())


    def is_alive(self):
        """
        Return True if the VM is alive and its monitor is responsive.
        """
        return not self.is_dead() and (not self.monitors or
                                       self.monitor.is_responsive())


    def is_dead(self):
        """
        Return True if the qemu process is dead.
        """
        return not self.process or not self.process.is_alive()


    def is_paused(self):
        """
        Return True if the qemu process is paused ('stop'ed)
        """
        if self.is_dead():
            return False
        try:
            self.verify_status("paused")
            return True
        except virt_vm.VMStatusError:
            return False


    def verify_status(self, status):
        """
        Check VM status

        @param status: Optional VM status, 'running' or 'paused'
        @raise VMStatusError: If the VM status is not same as parameter
        """
        if not self.monitor.verify_status(status):
            raise virt_vm.VMStatusError('Unexpected VM status: "%s"' %
                                        self.monitor.get_status())


    def verify_userspace_crash(self):
        """
        Verify if the userspace component (qemu) crashed.
        """
        for line in self.process.get_output().splitlines():
            if "(core dumped)" in line:
                raise QemuSegFaultError(line)


    def verify_disk_image_bootable(self):
        if self.params.get("image_verify_bootable") == "yes":
            pattern = self.params.get("image_unbootable_pattern")
            if not pattern:
                raise virt_vm.VMConfigMissingError(self.name,
                                                   "image_unbootable_pattern")
            try:
                seabios_log = self.logsessions['seabios'].get_output()
                if re.search(pattern, seabios_log, re.S):
                    logging.error("Can't boot guest from image.")
                    # Set 'shutdown_command' to None to force autotest
                    # shuts down guest with monitor.
                    self.params["shutdown_command"] = None
                    raise ImageUnbootableError(self.name)
            except KeyError:
                pass


    def clone(self, name=None, params=None, root_dir=None, address_cache=None,
              copy_state=False):
        """
        Return a clone of the VM object with optionally modified parameters.
        The clone is initially not alive and needs to be started using create().
        Any parameters not passed to this function are copied from the source
        VM.

        @param name: Optional new VM name
        @param params: Optional new VM creation parameters
        @param root_dir: Optional new base directory for relative filenames
        @param address_cache: A dict that maps MAC addresses to IP addresses
        @param copy_state: If True, copy the original VM's state to the clone.
                Mainly useful for make_qemu_command().
        """
        if name is None:
            name = self.name
        if params is None:
            params = self.params.copy()
        if root_dir is None:
            root_dir = self.root_dir
        if address_cache is None:
            address_cache = self.address_cache
        if copy_state:
            state = self.__dict__.copy()
        else:
            state = None
        return VM(name, params, root_dir, address_cache, state)


    def make_create_command(self, name=None, params=None, root_dir=None):
        """
        Generate a qemu command line. All parameters are optional. If a
        parameter is not supplied, the corresponding value stored in the
        class attributes is used.

        @param name: The name of the object
        @param params: A dict containing VM params
        @param root_dir: Base directory for relative filenames

        @note: The params dict should contain:
               mem -- memory size in MBs
               cdrom -- ISO filename to use with the qemu -cdrom parameter
               extra_params -- a string to append to the qemu command
               shell_port -- port of the remote shell daemon on the guest
               (SSH, Telnet or the home-made Remote Shell Server)
               shell_client -- client program to use for connecting to the
               remote shell daemon on the guest (ssh, telnet or nc)
               x11_display -- if specified, the DISPLAY environment variable
               will be be set to this value for the qemu process (useful for
               SDL rendering)
               images -- a list of image object names, separated by spaces
               nics -- a list of NIC object names, separated by spaces

               For each image in images:
               drive_format -- string to pass as 'if' parameter for this
               image (e.g. ide, scsi)
               image_snapshot -- if yes, pass 'snapshot=on' to qemu for
               this image
               image_boot -- if yes, pass 'boot=on' to qemu for this image
               In addition, all parameters required by get_image_filename.

               For each NIC in nics:
               nic_model -- string to pass as 'model' parameter for this
               NIC (e.g. e1000)
        """
        # Helper function for command line option wrappers
        def has_option(help_text, option):
            return bool(re.search(r"^-%s(\s|$)" % option, help_text, re.MULTILINE))


        def has_device(device_help, device):
            """
            Helper for checking if qemu-kvm support 'device'.
            """
            return bool(re.search(r'name "%s"' % device, device_help, re.M))


        def _add_option(option, value, option_type=None, first=False):
            """
            Add option to qemu parameters.
            """
            if first:
                fmt = " %s=%s"
            else:
                fmt = ",%s=%s"
            if option_type is bool:
                # Decode value for bool parameter (supports True, False, None)
                if value in ['yes', 'on', True]:
                    return fmt % (option, "on")
                elif value in ['no', 'off', False]:
                    return fmt % (option, "off")
            elif value and isinstance(value, bool):
                return fmt % (option, "on")
            elif value and isinstance(value, str):
                # "EMPTY_STRING" and "NULL_STRING" is used for testing illegal
                # foramt of option.
                # "EMPTY_STRING": set option as a empty string "".
                # "NO_EQUAL_STRING": set option as a option string only,
                #                    even without "=".
                #       (In most case, qemu-kvm should recognize it as "<null>")
                if value == "NO_EQUAL_STRING":
                    return ",%s" % option
                if value == "EMPTY_STRING":
                    value = '""'
                return fmt % (option, str(value))
            return ""


        def get_free_usb_port(dev, controller_type):
            # Find an available USB port.
            bus = None
            port = None
            controller = None

            for usb in params.objects("usbs"):
                usb_params = params.object_params(usb)
                usb_type = usb_params.get("usb_type")
                usb_dev = self.usb_dev_dict.get(usb)

                if usb_type.find(controller_type) != -1:
                    controller = usb
                    max_port = int(usb_params.get("usb_max_port", 6))
                    if len(usb_dev) < max_port:
                        bus = "%s.0" % usb
                        self.usb_dev_dict[usb].append(dev)
                        # Usb port starts from 1, so add 1 directly here.
                        port = self.usb_dev_dict[usb].index(dev) + 1
                        break

            if controller is None:
                raise virt_vm.VMUSBControllerMissingError(self.name,
                                                          controller_type)
            elif bus is None:
                raise virt_vm.VMUSBControllerPortFullError(self.name)

            return (bus, str(port))


        # Wrappers for all supported qemu command line parameters.
        # This is meant to allow support for multiple qemu versions.
        # Each of these functions receives the output of 'qemu -help'
        # as a parameter, and should add the requested command line
        # option accordingly.

        def add_name(help_text, name):
            return " -name '%s'" % name


        def add_human_monitor(help_text, monitor_name, filename):
            if not has_option(help_text, "chardev"):
                return " -monitor unix:'%s',server,nowait" % filename

            monitor_id = "hmp_id_%s" % monitor_name
            cmd = " -chardev socket"
            cmd += _add_option("id", monitor_id)
            cmd += _add_option("path", filename)
            cmd += _add_option("server", "NO_EQUAL_STRING")
            cmd += _add_option("nowait", "NO_EQUAL_STRING")
            cmd += " -mon chardev=%s" % monitor_id
            cmd += _add_option("mode", "readline")
            return cmd


        def add_qmp_monitor(help_text, monitor_name, filename):
            if not has_option(help_text, "qmp"):
                logging.warn("Fallback to human monitor since qmp is"
                             " unsupported")
                return add_human_monitor(help_text, monitor_name, filename)

            if not has_option(help_text, "chardev"):
                return " -qmp unix:'%s',server,nowait" % filename

            monitor_id = "qmp_id_%s" % monitor_name
            cmd = " -chardev socket"
            cmd += _add_option("id", monitor_id)
            cmd += _add_option("path", filename)
            cmd += _add_option("server", "NO_EQUAL_STRING")
            cmd += _add_option("nowait", "NO_EQUAL_STRING")
            cmd += " -mon chardev=%s" % monitor_id
            cmd += _add_option("mode", "control")
            return cmd


        def add_serial(help_text, name, filename):
            if not has_option(help_text, "chardev"):
                return " -serial unix:'%s',server,nowait" % filename

            serial_id = "serial_id_%s" % name
            cmd = " -chardev socket"
            cmd += _add_option("id", serial_id)
            cmd += _add_option("path", filename)
            cmd += _add_option("server", "NO_EQUAL_STRING")
            cmd += _add_option("nowait", "NO_EQUAL_STRING")
            cmd += " -device isa-serial"
            cmd += _add_option("chardev", serial_id)
            return cmd


        def add_virtio_port(help_text, name, bus, filename, porttype, chardev,
                            name_prefix=None, index=None, extra_params=""):
            """
            Appends virtio_serialport or virtio_console device to cmdline.
            @param help: qemu -h output
            @param name: Name of the port
            @param bus: Which virtio-serial-pci device use
            @param filename: Path to chardev filename
            @param porttype: Type of the port (*serialport, console)
            @param chardev: Which chardev to use (*socket, spicevmc)
            @param name_prefix: Custom name prefix (port index is appended)
            @param index: Index of the current virtio_port
            @param extra_params: Space sepparated chardev params
            """
            cmd = ''
            # host chardev
            if chardev == "spicevmc":   # SPICE
                cmd += " -chardev spicevmc,id=dev%s,name=%s" % (name, name)
            else:   # SOCKET
                cmd = (" -chardev socket,id=dev%s,path=%s,server,nowait"
                                                        % (name, filename))
            # virtport device
            if porttype in ("console", "virtio_console"):
                cmd += " -device virtconsole"
            else:
                cmd += " -device virtserialport"
            if name_prefix:     # used by spiceagent (com.redhat.spice.*)
                port_name = "%s%d" % (name_prefix, index)
            else:
                port_name = name
            cmd += ",chardev=dev%s,name=%s,id=%s" % (name, port_name, name)
            cmd += _add_option("bus", bus)
            # Space sepparated chardev params
            _params = ""
            for parm in extra_params.split():
                _params += ',' + parm
            cmd += _params
            return cmd


        def add_log_seabios(device_help):
            if not has_device(device_help, "isa-debugcon"):
                return ""

            default_id = "seabioslog_id_%s" % self.instance
            filename = "/tmp/seabios-%s" % self.instance
            self.logs["seabios"] = filename
            cmd = " -chardev socket"
            cmd += _add_option("id", default_id)
            cmd += _add_option("path", filename)
            cmd += _add_option("server", "NO_EQUAL_STRING")
            cmd += _add_option("nowait", "NO_EQUAL_STRING")
            cmd += " -device isa-debugcon"
            cmd += _add_option("chardev", default_id)
            cmd += _add_option("iobase", "0x402")
            return cmd


        def add_log_anaconda(help_text):
            chardev_id = "anacondalog_chardev_%s" % self.instance
            vioser_id = "anacondalog_vioser_%s" % self.instance
            filename = "/tmp/anaconda-%s" % self.instance
            self.logs["anaconda"] = filename
            cmd = " -chardev socket"
            cmd += _add_option("id", chardev_id)
            cmd += _add_option("path", filename)
            cmd += _add_option("server", "NO_EQUAL_STRING")
            cmd += _add_option("nowait", "NO_EQUAL_STRING")
            cmd += " -device virtio-serial-pci"
            cmd += _add_option("id", vioser_id)
            cmd += " -device virtserialport"
            cmd += _add_option("bus", "%s.0" % vioser_id)
            cmd += _add_option("chardev", chardev_id)
            cmd += _add_option("name", "org.fedoraproject.anaconda.log.0")
            return cmd


        def add_mem(help_text, mem):
            return " -m %s" % mem


        def add_smp(help_text):
            smp_str = " -smp %d" % self.cpuinfo.smp
            smp_pattern = "smp n\[,maxcpus=cpus\].*"
            if has_option(help_text, smp_pattern):
                smp_str += ",maxcpus=%d" % self.cpuinfo.maxcpus
            smp_str += ",cores=%d" % self.cpuinfo.cores
            smp_str += ",threads=%d" % self.cpuinfo.threads
            smp_str += ",sockets=%d" % self.cpuinfo.sockets
            return smp_str


        def add_cdrom(help_text, filename, index=None, fmt=None, bus=None,
                      port=None):
            if has_option(help_text, "drive"):
                name = None;
                dev = "";
                if fmt == "ahci":
                    name = "ahci%s" % index
                    dev += " -device ide-drive,bus=ahci.%s,drive=%s" % (index, name)
                    fmt = "none"
                    index = None
                if fmt in ['usb1', 'usb2', 'usb3']:
                    name = "%s.%s" % (fmt, index)
                    dev += " -device usb-storage"
                    dev += _add_option("bus", bus)
                    dev += _add_option("port", port)
                    dev += _add_option("drive", name)
                    fmt = "none"
                    index = None
                if fmt is not None and fmt.startswith("scsi-"):
                    # handles scsi-{hd, cd, disk, block, generic} targets
                    name = "virtio-scsi-cd%s" % index
                    dev += (" -device %s,drive=%s" %
                            (fmt, name))
                    dev += _add_option("bus", "virtio_scsi_pci%d.0" % bus)
                    fmt = "none"
                    index = None
                cmd = " -drive file='%s',media=cdrom" % filename
                if index is not None:
                    cmd += ",index=%s" % index
                if fmt:
                    cmd += ",if=%s" % fmt
                if name:
                    cmd += ",id=%s" % name
                return cmd + dev
            else:
                return " -cdrom '%s'" % filename


        def add_drive(help_text, filename, index=None, fmt=None, cache=None,
                      werror=None, rerror=None, serial=None, snapshot=False,
                      boot=False, blkdebug=None, bus=None, port=None,
                      bootindex=None, removable=None, min_io_size=None,
                      opt_io_size=None, physical_block_size=None,
                      logical_block_size=None, readonly=False, scsiid=None,
                      lun=None):
            name = None
            dev = ""
            if not re.search("boot=on\|off", help_text, re.MULTILINE):
                if boot in ['yes', 'on', True]:
                    bootindex = "1"
                boot = "unused"
            if fmt == "ahci":
                name = "ahci%s" % index
                dev += " -device ide-drive,bus=ahci.%s,drive=%s" % (index, name)
                dev += _add_option("bootindex", bootindex)
                fmt = "none"
                index = None
            if fmt == "virtio":
                if has_option(help_text, "device"):
                    name = "virtio%s" % index
                    dev += " -device virtio-blk-pci"
                    dev += _add_option("drive", name)
                    fmt = "none"
                    dev += _add_option("bootindex", bootindex)
                index = None
            if fmt in ['usb1', 'usb2', 'usb3']:
                name = "%s.%s" % (fmt, index)
                dev += " -device usb-storage"
                dev += _add_option("bus", bus)
                dev += _add_option("port", port)
                dev += _add_option("serial", serial)
                dev += _add_option("bootindex", bootindex)
                dev += _add_option("removable", removable)
                dev += _add_option("min_io_size", min_io_size)
                dev += _add_option("opt_io_size", opt_io_size)
                dev += _add_option("physical_block_size", physical_block_size)
                dev += _add_option("logical_block_size", logical_block_size)
                dev += _add_option("drive", name)
                fmt = "none"
                index = None
            if fmt.startswith("scsi-"):
                # handles scsi-{hd, cd, disk, block, generic} targets
                name = "virtio-scsi%s" % index
                dev += " -device %s" % fmt
                dev += _add_option("logical_block_size", logical_block_size)
                dev += _add_option("physical_block_size", physical_block_size)
                dev += _add_option("min_io_size", min_io_size)
                dev += _add_option("opt_io_size", opt_io_size)
                dev += _add_option("bootindex", bootindex)
                dev += _add_option("serial", serial)
                dev += _add_option("removable", removable)
                if bus:
                    name += "-b%s" % bus
                    dev += _add_option("bus", "virtio_scsi_pci%d.0" % bus)
                if scsiid:
                    name += "-i%s" % scsiid
                    dev += _add_option("scsi-id", scsiid)
                if lun:
                    name += "-l%s" % lun
                    dev += _add_option("lun", lun)
                fmt = "none"
                dev += _add_option("drive", name)
                index = None
            if fmt == "floppy":
                drivelist = ['driveA','driveB']
                name ="fdc0-0-%s" % index
                fmt = "none"
                dev += " -global"
                dev += _add_option("isa-fdc.%s" % drivelist[index], name,
                                   first=True)

            if blkdebug is not None:
                cmd = " -drive file=blkdebug:%s:%s" % (blkdebug, filename)
            else:
                cmd = " -drive file='%s'" % filename

            cmd += _add_option("index", index)
            cmd += _add_option("if", fmt)
            cmd += _add_option("cache", cache)
            cmd += _add_option("rerror", rerror)
            cmd += _add_option("werror", werror)
            cmd += _add_option("serial", serial)
            cmd += _add_option("snapshot", snapshot, bool)
            # Only add boot=on/off if necessary (deprecated in newer qemu)
            if boot != "unused":
                cmd += _add_option("boot", boot, bool)
            cmd += _add_option("id", name)
            cmd += _add_option("readonly", readonly, bool)
            return cmd + dev

        def add_nic(help_text, vlan, model=None, mac=None, device_id=None, netdev_id=None,
                    nic_extra_params=None):
            if model == 'none':
                return ''
            if has_option(help_text, "netdev"):
                netdev_vlan_str = ",netdev=%s" % netdev_id
            else:
                netdev_vlan_str = ",vlan=%d" % vlan
            if has_option(help_text, "device"):
                if not model:
                    model = "rtl8139"
                elif model == "virtio":
                    model = "virtio-net-pci"
                cmd = " -device %s" % model + netdev_vlan_str
                if mac:
                    cmd += ",mac='%s'" % mac
                if nic_extra_params:
                    cmd += ",%s" % nic_extra_params
            else:
                cmd = " -net nic" + netdev_vlan_str
                if model:
                    cmd += ",model=%s" % model
                if mac:
                    cmd += ",macaddr='%s'" % mac
            if device_id:
                cmd += ",id='%s'" % device_id
            return cmd

        def add_net(help_text, vlan, nettype, ifname=None, tftp=None, bootfile=None,
                    hostfwd=[], netdev_id=None, netdev_extra_params=None,
                    tapfd=None):
            mode = None
            if nettype in ['bridge', 'network', 'macvtap']:
                mode = 'tap'
            elif nettype == 'user':
                mode = 'user'
            else:
                logging.warning("Unknown/unsupported nettype %s" % nettype)
                return ''
            if has_option(help_text, "netdev"):
                cmd = " -netdev %s,id=%s" % (mode, netdev_id)
                if netdev_extra_params:
                    cmd += "%s" % netdev_extra_params
            else:
                cmd = " -net %s,vlan=%d" % (mode, vlan)
            if mode == "tap" and tapfd:
                cmd += ",fd=%d" % tapfd
            elif mode == "user":
                if tftp and "[,tftp=" in help_text:
                    cmd += ",tftp='%s'" % tftp
                if bootfile and "[,bootfile=" in help_text:
                    cmd += ",bootfile='%s'" % bootfile
                if "[,hostfwd=" in help_text:
                    for host_port, guest_port in hostfwd:
                        cmd += ",hostfwd=tcp::%s-:%s" % (host_port, guest_port)
            return cmd

        def add_floppy(help_text, filename, index):
            cmd_list = [" -fda '%s'"," -fdb '%s'"]
            return cmd_list[index] % filename


        def add_tftp(help_text, filename):
            # If the new syntax is supported, don't add -tftp
            if "[,tftp=" in help_text:
                return ""
            else:
                return " -tftp '%s'" % filename

        def add_bootp(help_text, filename):
            # If the new syntax is supported, don't add -bootp
            if "[,bootfile=" in help_text:
                return ""
            else:
                return " -bootp '%s'" % filename

        def add_tcp_redir(help_text, host_port, guest_port):
            # If the new syntax is supported, don't add -redir
            if "[,hostfwd=" in help_text:
                return ""
            else:
                return " -redir tcp:%s::%s" % (host_port, guest_port)


        def add_vnc(help_text, vnc_port, vnc_password='no', extra_params=None):
            vnc_cmd = " -vnc :%d" % (vnc_port - 5900)
            if vnc_password == "yes":
                vnc_cmd += ",password"
            if extra_params:
                vnc_cmd += ",%s" % extra_params
            return vnc_cmd


        def add_sdl(help_text):
            if has_option(help_text, "sdl"):
                return " -sdl"
            else:
                return ""

        def add_nographic(help_text):
            return " -nographic"

        def add_uuid(help_text, uuid):
            return " -uuid '%s'" % uuid

        def add_pcidevice(help_text, host, params=None):
            assign_param = []
            device_help = utils.system_output("%s -device \\? 2>&1" % qemu_binary)
            cmd = "  -pcidevice "
            if bool(re.search("pci-assign", device_help, re.M)):
                cmd = " -device pci-assign,"
            help_cmd = "%s -device pci-assign,\\? 2>&1" % qemu_binary
            pcidevice_help = utils.system_output(help_cmd)
            cmd += "host=%s" % host
            cmd += ",id=id_%s" % host
            if params is not None and params.get("pci-assign_params"):
                assign_param = params.get("pci-assign_params").split()
            fail_param = []
            for param in assign_param:
                value = params.get(param)
                if value:
                    if bool(re.search(param, pcidevice_help, re.M)):
                        cmd += ",%s=%s" % (param, value)
                    else:
                        fail_param.append(param)
            if fail_param:
                msg = ("parameter %s is not support in device pci-assign."
                       " It only support following paramter:\n %s" %
                       (param, pcidevice_help))
                logging.warn(msg)
            return cmd

        def add_spice(port_range=(3000, 3199),
             tls_port_range=(3200, 3399)):
            """
            processes spice parameters
            @param port_range - tuple with port range, default: (3000, 3199)
            @param tls_port_range - tuple with tls port range,
                                    default: (3200, 3399)
            """
            spice_opts = [] # will be used for ",".join()
            tmp = None
            def optget(opt):
                """a helper function"""
                return self.spice_options.get(opt)

            def set_yes_no_value(key, yes_value=None, no_value=None):
                """just a helper function"""
                tmp = optget(key)
                if tmp == "no" and no_value:
                    spice_opts.append(no_value)

                elif tmp == "yes" and yes_value:
                    spice_opts.append(yes_value)

            def set_value(opt_string, key, fallback=None):
                """just a helper function"""
                tmp = optget(key)
                if tmp:
                    spice_opts.append(opt_string % tmp)
                elif fallback:
                    spice_opts.append(fallback)
            s_port = str(utils_misc.find_free_port(*port_range))
            if optget("spice_port") == "generate":
                self.spice_options['spice_port'] = s_port
                spice_opts.append("port=%s" % s_port)
            else:
                set_value("port=%s", "spice_port")

            set_value("password=%s", "spice_password", "disable-ticketing")
            set_yes_no_value("disable_copy_paste", yes_value="disable-copy-paste")
            set_value("addr=%s", "spice_addr")

            if optget("spice_ssl") == "yes":
                # SSL only part
                t_port = str(utils_misc.find_free_port(*tls_port_range))
                if optget("spice_tls_port") == "generate":
                    self.spice_options['spice_tls_port'] = t_port
                    spice_opts.append("tls-port=%s" % t_port)
                else:
                    set_value("tls-port=%s", "spice_tls_port")

                prefix = optget("spice_x509_prefix")
                if (not os.path.exists(prefix) and
                    (optget("spice_gen_x509") == "yes")):
                    # Generate spice_x509_* is not always necessary,
                    # Regenerate them will make your existing VM
                    # not longer accessiable via encrypted spice.
                    c_subj = optget("spice_x509_cacert_subj")
                    s_subj = optget("spice_x509_server_subj")
                    passwd = optget("spice_x509_key_password")
                    secure = optget("spice_x509_secure")

                    utils_misc.create_x509_dir(prefix, c_subj, s_subj, passwd,
                                               secure)

                tmp = optget("spice_x509_dir")
                if tmp == "yes":
                    spice_opts.append("x509-dir=%s" % (prefix))

                elif tmp == "no":
                    cacert = optget("spice_x509_cacert_file")
                    server_key = optget("spice_x509_key_file")
                    server_cert = optget("spice_x509_cert_file")
                    keyfile_str = ("x509-key-file=%s,x509-cacert-file=%s,"
                                   "x509-cert-file=%s" %
                                   (os.path.join(prefix, server_key),
                                   os.path.join(prefix, cacert),
                                   os.path.join(prefix, server_cert)))
                    spice_opts.append(keyfile_str)

                set_yes_no_value("spice_x509_secure",
                    yes_value="x509-key-password=%s" %
                        (optget("spice_x509_key_password")))

                tmp = optget("spice_secure_channels")
                if tmp:
                    for item in tmp.split(","):
                        spice_opts.append("tls-channel=%s" % (item.strip()))

            # Less common options
            set_value("seamless-migration=%s", "spice_seamless_migration")
            set_value("image-compression=%s", "spice_image_compression")
            set_value("jpeg-wan-compression=%s", "spice_jpeg_wan_compression")
            set_value("zlib-glz-wan-compression=%s",
                      "spice_zlib_glz_wan_compression")
            set_value("streaming-video=%s", "spice_streaming_video")
            set_value("agent-mouse=%s", "spice_agent_mouse")
            set_value("playback-compression=%s", "spice_playback_compression")

            set_yes_no_value("spice_ipv4", yes_value="ipv4")
            set_yes_no_value("spice_ipv6", yes_value="ipv6")

            return " -spice %s" % (",".join(spice_opts))

        def add_qxl(qxl_nr, qxl_memory=None):
            """
            adds extra qxl devices + sets memory to -vga qxl and extra qxls
            @param qxl_nr total number of qxl devices
            @param qxl_memory sets memory to individual devices
            """
            qxl_str = ""
            vram_help = ""

            if qxl_memory:
                vram_help = "vram_size=%d" % qxl_memory
                qxl_str += " -global qxl-vga.%s" % (vram_help)

            for index in range(1, qxl_nr):
                qxl_str += " -device qxl,id=video%d,%s"\
                        % (index, vram_help)
            return qxl_str

        def add_vga(vga):
            return " -vga %s" % vga

        def add_kernel(help_text, filename):
            return " -kernel '%s'" % filename

        def add_initrd(help_text, filename):
            return " -initrd '%s'" % filename


        def add_rtc(help_text):
            # Pay attention that rtc-td-hack is for early version
            # if "rtc " in help:
            if has_option(help_text, "rtc"):
                cmd = " -rtc base=%s" % params.get("rtc_base", "utc")
                cmd += _add_option("clock", params.get("rtc_clock", "host"))
                cmd += _add_option("driftfix", params.get("rtc_drift", "none"))
                return cmd
            elif has_option(help_text, "rtc-td-hack"):
                return " -rtc-td-hack"
            else:
                return ""


        def add_kernel_cmdline(help_text, cmdline):
            return " -append '%s'" % cmdline

        def add_testdev(help_text, filename=None):
            if has_device(device_help, "testdev"):
                return (" -chardev file,id=testlog,path=%s"
                        " -device testdev,chardev=testlog" % filename)
            elif has_device(device_help, "pc-testdev"):
                return " -device pc-testdev"
            else:
                return ""

        def add_isa_debug_exit(help_text, iobase=0xf4, iosize=0x04):
            if has_device(device_help, "isa-debug-exit"):
                return (" -device isa-debug-exit,iobase=%s,iosize=%s" %
                        (iobase, iosize))
            else:
                return ""

        def add_no_hpet(help_text):
            if has_option(help_text, "no-hpet"):
                return " -no-hpet"
            else:
                return ""

        def add_cpu_flags(help_text, cpu_model, flags=None, vendor_id=None,
                          family=None):
            if has_option(help_text, 'cpu'):
                cmd = " -cpu '%s'" % cpu_model

                if vendor_id:
                    cmd += ",vendor=\"%s\"" % vendor_id
                if flags:
                    cmd += ",%s" % flags
                if family is not None:
                    cmd += ",family=%s" % family
                return cmd
            else:
                return ""


        def add_boot(help_text, boot_order, boot_once, boot_menu):
            cmd = " -boot"
            pattern = "boot \[order=drives\]\[,once=drives\]\[,menu=on\|off\]"
            if has_option(help_text, "boot \[a\|c\|d\|n\]"):
                cmd += " %s" % boot_once
            elif has_option(help_text, pattern):
                cmd += (" order=%s,once=%s,menu=%s" %
                        (boot_order, boot_once, boot_menu))
            else:
                cmd = ""
            return cmd

        def add_machine_type(help_text, machine_type):
            if has_option(help_text, "machine") or has_option(help_text, "M"):
                return " -M %s" % machine_type
            else:
                return ""

        def add_usb(help_text, usb_id, usb_type):
            if not has_option(help_text, "device"):
                # Okay, for the archaic qemu which has not device parameter,
                # just return a usb uhci controller.
                # If choose this kind of usb controller, it has no name/id,
                # and only can be created once, so give it a special name.
                self.usb_dev_dict["OLDVERSION_usb0"] = []
                return " -usb"

            if not has_device(device_help, usb_type):
                raise error.TestNAError("usb controller %s not available" % usb_type)

            cmd = " -device %s" % usb_type
            cmd += _add_option("id", usb_id)

            if usb_type == "ich9-usb-ehci1":
                common = ",multifunction=on,masterbus=%s.0" % usb_id
                uhci1 = " -device ich9-usb-uhci1,addr=1d.0,firstport=0"
                uhci2 = " -device ich9-usb-uhci2,addr=1d.1,firstport=2"
                uhci3 = " -device ich9-usb-uhci3,addr=1d.2,firstport=4"
                cmd += ",addr=1d.7,multifunction=on"
                cmd += uhci1 + common
                cmd += uhci2 + common
                cmd += uhci3 + common

            # register this usb controller.
            self.usb_dev_dict[usb_id] = []
            return cmd

        def add_usbdevice(help_text, usb_dev, usb_type, controller_type,
                          bus=None, port=None):
            """
            This function is used to add usb device except for usb storage.
            """

            if not has_device(device_help, usb_type):
                raise error.TestNAError("usb device %s not available" % usb_type)

            cmd = ""
            if has_option(help_text, "device"):
                cmd = " -device %s" % usb_type
                cmd += _add_option("id", "usb-%s" % usb_dev)
                cmd += _add_option("bus", bus)
                cmd += _add_option("port", port)
            else:
                if "tablet" in usb_type:
                    cmd = " -usbdevice %s" % usb_type
                else:
                    logging.error("This version of host only support"
                                  " tablet device")

            return cmd


        def add_sga(help_text):
            if not has_option(help_text, "device"):
                return ""

            return " -device sga"


        # End of command line option wrappers

        if name is None:
            name = self.name
        if params is None:
            params = self.params
        if root_dir is None:
            root_dir = self.root_dir

        have_ahci = False
        virtio_scsi_pcis = []

        # Clone this VM using the new params
        vm = self.clone(name, params, root_dir, copy_state=True)

        qemu_binary = utils_misc.get_path(os.path.join(root_dir,
                                                       params.get("vm_type")),
                                          params.get("qemu_binary", "qemu"))

        self.qemu_binary = qemu_binary
        help_text = commands.getoutput("%s -help" % qemu_binary)
        support_cpu_model = commands.getoutput("%s -cpu ?" % qemu_binary)
        support_machine_type = commands.getoutput("%s -M ?" % qemu_binary)

        device_help = ""
        if has_option(help_text, "device"):
            device_help = commands.getoutput("%s -device \\?" % qemu_binary)

        # Start constructing the qemu command
        qemu_cmd = ""

        # Enable the use of glibc's malloc_perturb feature
        if params.get("malloc_perturb", "no") == "yes":
            qemu_cmd += "MALLOC_PERTURB_=1 "
        # Set the X11 display parameter if requested
        if params.get("x11_display"):
            qemu_cmd += "DISPLAY=%s " % params.get("x11_display")
        # Update LD_LIBRARY_PATH for built libraries (libspice-server)
        library_path = os.path.join(self.root_dir, 'build', 'lib')
        if os.path.isdir(library_path):
            library_path = os.path.abspath(library_path)
            qemu_cmd += "LD_LIBRARY_PATH=%s " % library_path
        if params.get("qemu_audio_drv"):
            qemu_cmd += "QEMU_AUDIO_DRV=%s " % params.get("qemu_audio_drv")
        # Add command prefix for qemu-kvm. like taskset, valgrind and so on
        if params.get("qemu_command_prefix"):
            qemu_command_prefix = params.get("qemu_command_prefix")
            qemu_cmd += "%s " % qemu_command_prefix
        # Add numa memory cmd to pin guest memory to numa node
        if params.get("numa_node"):
            numa_node = int(params.get("numa_node"))
            if numa_node < 0:
                p = utils_misc.NumaNode(numa_node)
                n = int(p.get_node_num()) + numa_node
                qemu_cmd += "numactl -m %s " % n
            else:
                n = numa_node - 1
                qemu_cmd += "numactl -m %s " % n
        # Add the qemu binary
        qemu_cmd += qemu_binary
        qemu_cmd += " -S"
        # Add the VM's name
        qemu_cmd += add_name(help_text, name)
        # no automagic devices please
        defaults = params.get("defaults", "no")
        if has_option(help_text, "nodefaults") and defaults != "yes":
            qemu_cmd += " -nodefaults"
        # Add monitors
        for monitor_name in params.objects("monitors"):
            monitor_params = params.object_params(monitor_name)
            monitor_filename = vm.get_monitor_filename(monitor_name)
            if monitor_params.get("monitor_type") == "qmp":
                qemu_cmd += add_qmp_monitor(help_text, monitor_name,
                                            monitor_filename)
            else:
                qemu_cmd += add_human_monitor(help_text, monitor_name,
                                              monitor_filename)

        # Add serial console redirection
        for serial in params.objects("isa_serials"):
            serial_filename = vm.get_serial_console_filename(serial)
            qemu_cmd += add_serial(help_text, serial, serial_filename)

        # Add virtio_serial ports
        no_virtio_serial_pcis = 0
        no_virtio_ports = 0
        virtio_port_spread = int(params.get('virtio_port_spread', 2))
        for port_name in params.objects("virtio_ports"):
            port_params = params.object_params(port_name)
            bus = params.get('virtio_port_bus', False)
            if bus is not False:     # Manually set bus
                bus = int(bus)
            elif not virtio_port_spread:
                # bus not specified, let qemu decide
                pass
            elif not no_virtio_ports % virtio_port_spread:
                # Add new vio-pci every n-th port. (Spread ports)
                bus = no_virtio_serial_pcis
            else:  # Port not overriden, use last vio-pci
                bus = no_virtio_serial_pcis - 1
                if bus < 0:     # First bus
                    bus = 0
            # Add virtio_serial_pcis
            for i in range(no_virtio_serial_pcis, bus + 1):
                qemu_cmd += (" -device virtio-serial-pci,id=virtio_serial_pci"
                             "%d" % i)
                no_virtio_serial_pcis += 1
            if bus is not False:
                bus = "virtio_serial_pci%d.0" % bus
            # Add actual ports
            qemu_cmd += add_virtio_port(help_text, port_name, bus,
                                    self.get_virtio_port_filename(port_name),
                                    port_params.get('virtio_port_type'),
                                    port_params.get('virtio_port_chardev'),
                                    port_params.get('virtio_port_name_prefix'),
                                    no_virtio_ports,
                                    port_params.get('virtio_port_params', ''))
            no_virtio_ports += 1

        # Add logging
        qemu_cmd += add_log_seabios(device_help)
        if params.get("anaconda_log", "no") == "yes":
            qemu_cmd += add_log_anaconda(help_text)

        # Add USB controllers
        for usb_name in params.objects("usbs"):
            usb_params = params.object_params(usb_name)
            qemu_cmd += add_usb(help_text, usb_name, usb_params.get("usb_type"))

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            if image_params.get("boot_drive") == "no":
                continue
            if image_params.get("drive_format") == "ahci" and not have_ahci:
                qemu_cmd += " -device ahci,id=ahci"
                have_ahci = True

            bus = None
            port = None
            if image_params.get("drive_format") == "usb1":
                bus, port = get_free_usb_port(image_name, "uhci")
            if image_params.get("drive_format") == "usb2":
                bus, port = get_free_usb_port(image_name, "ehci")
            if image_params.get("drive_format") == "usb3":
                bus, port = get_free_usb_port(image_name, "xhci")
            if image_params.get("drive_format").startswith("scsi-"):
                try:
                    bus = int(image_params.get("drive_bus", 0))
                except ValueError:
                    raise virt_vm.VMError("cfg: drive_bus have to be an "
                                          "integer. (%s)" % image_name)
                for i in range(len(virtio_scsi_pcis), bus + 1):
                    hba = params.get("scsi_hba", "virtio-scsi-pci")
                    qemu_cmd += " -device %s,id=virtio_scsi_pci%d" % (hba, i)
                    virtio_scsi_pcis.append("virtio_scsi_pci%d" % i)

            base_dir = image_params.get("images_base_dir",
                                        data_dir.get_data_dir())

            shared_dir = os.path.join(self.root_dir, "shared")
            qemu_cmd += add_drive(help_text,
                    storage.get_image_filename(image_params,
                                               base_dir),
                    image_params.get("drive_index"),
                    image_params.get("drive_format"),
                    image_params.get("drive_cache"),
                    image_params.get("drive_werror"),
                    image_params.get("drive_rerror"),
                    image_params.get("drive_serial"),
                    image_params.get("image_snapshot"),
                    image_params.get("image_boot"),
                    storage.get_image_blkdebug_filename(image_params,
                                                        shared_dir),
                    bus,
                    port,
                    image_params.get("bootindex"),
                    image_params.get("removable"),
                    image_params.get("min_io_size"),
                    image_params.get("opt_io_size"),
                    image_params.get("physical_block_size"),
                    image_params.get("logical_block_size"),
                    image_params.get("image_readonly"),
                    image_params.get("drive_scsiid"),
                    image_params.get("drive_lun"))

        # Networking
        redirs = []
        for redir_name in params.objects("redirs"):
            redir_params = params.object_params(redir_name)
            guest_port = int(redir_params.get("guest_port"))
            host_port = vm.redirs.get(guest_port)
            redirs += [(host_port, guest_port)]

        iov = 0
        for nic in vm.virtnet:
            nic_params = params.object_params(nic.nic_name)
            if nic_params.get('pci_assignable') == "no":
                # setup nic parameters as needed
                # add_netdev if netdev_id not set
                nic = vm.add_nic(**dict(nic))
                # gather set values or None if unset
                vlan = int(nic.get('vlan'))
                netdev_id = nic.get('netdev_id')
                device_id = nic.get('device_id')
                mac = nic.get('mac')
                nic_model = nic.get("nic_model")
                nic_extra = nic.get("nic_extra_params")
                netdev_extra = nic.get("netdev_extra_params")
                bootp = nic.get("bootp")
                if nic.get("tftp"):
                    tftp = utils_misc.get_path(root_dir, nic.get("tftp"))
                else:
                    tftp = None
                nettype = nic.get("nettype", "bridge")
                # don't force conversion add_nic()/add_net() optional parameter
                if nic.has_key('tapfd'):
                    tapfd = int(nic.tapfd)
                else:
                    tapfd = None
                ifname = nic.get('ifname')
                # Handle the '-net nic' part
                qemu_cmd += add_nic(help_text, vlan, nic_model, mac,
                                    device_id, netdev_id, nic_extra)
                # Handle the '-net tap' or '-net user' or '-netdev' part
                qemu_cmd += add_net(help_text, vlan, nettype, ifname, tftp,
                                    bootp, redirs, netdev_id, netdev_extra,
                                    tapfd)
            else:
                pci_id = vm.pa_pci_ids[iov]
                qemu_cmd += add_pcidevice(help, pci_id, params=nic_params)
                iov += 1


        mem = params.get("mem")
        if mem:
            qemu_cmd += add_mem(help_text, mem)

        smp = int(params.get("smp", 0))
        vcpu_maxcpus = int(params.get("vcpu_maxcpus", 0))
        vcpu_sockets = int(params.get("vcpu_sockets", 0))
        vcpu_cores = int(params.get("vcpu_cores", 0))
        vcpu_threads = int(params.get("vcpu_threads", 0))

        # Force CPU threads to 2 when smp > 8.
        if smp > 8 and vcpu_threads <= 1:
            vcpu_threads = 2

        if smp == 0 or vcpu_sockets == 0:
            vcpu_cores = vcpu_cores or 1
            vcpu_threads = vcpu_threads or 1
            if smp and vcpu_sockets == 0:
                vcpu_sockets = smp / (vcpu_cores * vcpu_threads)
            else:
                vcpu_sockets = vcpu_sockets or 1
            if smp == 0:
                smp = vcpu_cores * vcpu_threads * vcpu_sockets
        else:
            if vcpu_cores == 0:
                vcpu_threads = vcpu_threads or 1
                vcpu_cores = smp / (vcpu_sockets * vcpu_threads)
            else:
                vcpu_threads = smp / (vcpu_cores * vcpu_sockets)

        self.cpuinfo.smp = smp
        self.cpuinfo.maxcpus = vcpu_maxcpus or smp
        self.cpuinfo.cores = vcpu_cores
        self.cpuinfo.threads = vcpu_threads
        self.cpuinfo.sockets = vcpu_sockets
        qemu_cmd += add_smp(help_text)

        cpu_model = params.get("cpu_model")
        use_default_cpu_model = True
        if cpu_model:
            use_default_cpu_model = False
            for model in re.split(",", cpu_model):
                model = model.strip()
                if not model in support_cpu_model:
                    continue
                cpu_model = model
                break
            else:
                cpu_model = model
                logging.error("Non existing CPU model %s will be passed "
                              "to qemu (wrong config or negative test)", model)

        if use_default_cpu_model:
            cpu_model = params.get("default_cpu_model")

        if cpu_model:
            vendor = params.get("cpu_model_vendor")
            flags = params.get("cpu_model_flags")
            family = params.get("cpu_family")
            self.cpuinfo.model = cpu_model
            self.cpuinfo.vendor = vendor
            self.cpuinfo.flags = flags
            self.cpuinfo.family = family
            qemu_cmd += add_cpu_flags(help_text, cpu_model, flags,
                                      vendor, family)

        machine_type = params.get("machine_type")
        if machine_type:
            m_types = []
            for m in support_machine_type.splitlines()[1:]:
                m_types.append(m.split()[0])

            if machine_type in m_types:
                qemu_cmd += add_machine_type(help_text, machine_type)
            else:
                raise error.TestNAError("Unsupported machine type %s." %
                                        (machine_type))

        for cdrom in params.objects("cdroms"):
            cd_format = params.get("cd_format", "")
            cdrom_params = params.object_params(cdrom)
            iso = cdrom_params.get("cdrom")
            bus = None
            port = None
            if cd_format == "usb1":
                bus, port = get_free_usb_port(image_name, "uhci")
            if cd_format == "usb2":
                bus, port = get_free_usb_port(image_name, "ehci")
            if cd_format == "usb3":
                bus, port = get_free_usb_port(image_name, "xhci")
            if cd_format == "ahci" and not have_ahci:
                qemu_cmd += " -device ahci,id=ahci"
                have_ahci = True
            if cd_format and cd_format.startswith("scsi-"):
                try:
                    bus = int(cdrom_params.get("drive_bus", 0))
                except ValueError:
                    raise virt_vm.VMError("cfg: drive_bus have to be an "
                                          "integer. (%s)" % cdrom)
                for i in range(len(virtio_scsi_pcis), bus + 1):
                    qemu_cmd += " -device virtio-scsi-pci,id=virtio_scsi_pci%d" % i
                    virtio_scsi_pcis.append("virtio_scsi_pci%d" % i)
            if iso:
                qemu_cmd += add_cdrom(help_text,
                              utils_misc.get_path(data_dir.get_data_dir(), iso),
                                      cdrom_params.get("drive_index"),
                                      cd_format, bus)

        soundhw = params.get("soundcards")
        if soundhw:
            if not has_option(help_text, 'device') or soundhw == "all":
                qemu_cmd += " -soundhw %s" % soundhw
            else:
                for sound_device in soundhw.split(","):
                    if "hda" in sound_device:
                        qemu_cmd += " -device intel-hda -device hda-duplex"
                    elif sound_device in ["es1370", "ac97"]:
                        qemu_cmd += " -device %s" % sound_device.upper()
                    else:
                        qemu_cmd += " -device %s" % sound_device


        # We may want to add {floppy_otps} parameter for -fda, -fdb
        # {fat:floppy:}/path/. However vvfat is not usually recommended.
        for index, floppy_name in enumerate(params.objects("floppies")):
            if index > 1:
                logging.warn("At most support two floppy in qemu-kvm")
            else:
                floppy_params = params.object_params(floppy_name)
                floppy_readonly = floppy_params.get("floppy_readonly", "no")
                floppy_readonly = floppy_readonly == "yes"
                floppy = utils_misc.get_path(data_dir.get_data_dir(),
                                             floppy_params.get("floppy_name"))
                if has_option(help_text,"global"):
                    qemu_cmd += add_drive(help_text, floppy,
                                          fmt="floppy",
                                          index=index,
                                          readonly=floppy_readonly)
                else:
                    qemu_cmd += add_floppy(help_text, floppy, index)

        # Add usb devices
        for usb_dev in params.objects("usb_devices"):
            usb_dev_params = params.object_params(usb_dev)
            usb_type = usb_dev_params.get("usb_type")
            controller_type = usb_dev_params.get("usb_controller")

            usb_controller_list = self.usb_dev_dict.keys()
            if (len(usb_controller_list) == 1 and
                "OLDVERSION_usb0" in usb_controller_list):
                # old version of qemu-kvm doesn't support bus and port option.
                bus = None
                port = None
            else:
                bus, port = get_free_usb_port(usb_dev, controller_type)

            qemu_cmd += add_usbdevice(help_text, usb_dev, usb_type, controller_type,
                                      bus, port)

        tftp = params.get("tftp")
        if tftp:
            tftp = utils_misc.get_path(data_dir.get_data_dir(), tftp)
            qemu_cmd += add_tftp(help_text, tftp)

        bootp = params.get("bootp")
        if bootp:
            qemu_cmd += add_bootp(help_text, bootp)

        kernel = params.get("kernel")
        if kernel:
            kernel = utils_misc.get_path(data_dir.get_data_dir(), kernel)
            qemu_cmd += add_kernel(help_text, kernel)

        kernel_params = params.get("kernel_params")
        if kernel_params:
            qemu_cmd += add_kernel_cmdline(help_text, kernel_params)

        initrd = params.get("initrd")
        if initrd:
            initrd = utils_misc.get_path(data_dir.get_data_dir(), initrd)
            qemu_cmd += add_initrd(help_text, initrd)

        for host_port, guest_port in redirs:
            qemu_cmd += add_tcp_redir(help_text, host_port, guest_port)

        if params.get("display") == "vnc":
            vnc_extra_params = params.get("vnc_extra_params")
            vnc_password = params.get("vnc_password", "no")
            qemu_cmd += add_vnc(help_text, self.vnc_port, vnc_password,
                                vnc_extra_params)
        elif params.get("display") == "sdl":
            qemu_cmd += add_sdl(help_text)
        elif params.get("display") == "nographic":
            qemu_cmd += add_nographic(help_text)
        elif params.get("display") == "spice":
            spice_keys = (
                "spice_port", "spice_password", "spice_addr", "spice_ssl",
                "spice_tls_port", "spice_tls_ciphers", "spice_gen_x509",
                "spice_x509_dir", "spice_x509_prefix", "spice_x509_key_file",
                "spice_x509_cacert_file", "spice_x509_key_password",
                "spice_x509_secure", "spice_x509_cacert_subj",
                "spice_x509_server_subj", "spice_secure_channels",
                "spice_image_compression", "spice_jpeg_wan_compression",
                "spice_zlib_glz_wan_compression", "spice_streaming_video",
                "spice_agent_mouse", "spice_playback_compression",
                "spice_ipv4", "spice_ipv6", "spice_x509_cert_file",
                "disable_copy_paste", "spice_seamless_migration"
            )

            for skey in spice_keys:
                value = params.get(skey, None)
                if value:
                    self.spice_options[skey] = value

            qemu_cmd += add_spice()

        vga = params.get("vga", None)
        if vga:
            qemu_cmd += add_vga(vga)

            if vga == "qxl":
                qxl_dev_memory = int(params.get("qxl_dev_memory", 0))
                qxl_dev_nr = int(params.get("qxl_dev_nr", 1))
                qemu_cmd += add_qxl(qxl_dev_nr, qxl_dev_memory)

        if params.get("uuid") == "random":
            qemu_cmd += add_uuid(help_text, vm.uuid)
        elif params.get("uuid"):
            qemu_cmd += add_uuid(help_text, params.get("uuid"))

        if params.get("testdev") == "yes":
            qemu_cmd += add_testdev(help_text, vm.get_testlog_filename())

        if params.get("isa_debugexit") == "yes":
            iobase = params.get("isa_debugexit_iobase")
            iosize = params.get("isa_debugexit_iosize")
            qemu_cmd += add_isa_debug_exit(help_text, iobase, iosize)

        if params.get("disable_hpet") == "yes":
            qemu_cmd += add_no_hpet(help_text)

        qemu_cmd += add_rtc(help_text)

        if has_option(help_text, "boot"):
            boot_order = params.get("boot_order", "cdn")
            boot_once = params.get("boot_once", "c")
            boot_menu = params.get("boot_menu", "off")
            qemu_cmd += " %s " % add_boot(help_text, boot_order, boot_once,
                                          boot_menu)

        p9_export_dir = params.get("9p_export_dir")
        if p9_export_dir:
            qemu_cmd += " -fsdev"
            p9_fs_driver = params.get("9p_fs_driver")
            if p9_fs_driver == "handle":
                qemu_cmd += " handle,id=local1,path=" + p9_export_dir
            elif p9_fs_driver == "proxy":
                qemu_cmd += " proxy,id=local1,socket="
            else:
                p9_fs_driver = "local"
                qemu_cmd += " local,id=local1,path=" + p9_export_dir

            # security model is needed only for local fs driver
            if p9_fs_driver == "local":
                p9_security_model = params.get("9p_security_model")
                if not p9_security_model:
                    p9_security_model = "none"
                qemu_cmd += ",security_model=" + p9_security_model
            elif p9_fs_driver == "proxy":
                p9_socket_name = params.get("9p_socket_name")
                if not p9_socket_name:
                    raise virt_vm.VMImageMissingError("Socket name not defined")
                qemu_cmd += p9_socket_name

            p9_immediate_writeout = params.get("9p_immediate_writeout")
            if p9_immediate_writeout == "yes":
                qemu_cmd += ",writeout=immediate"

            p9_readonly = params.get("9p_readonly")
            if p9_readonly == "yes":
                qemu_cmd += ",readonly"

            qemu_cmd += " -device virtio-9p-pci,fsdev=local1,mount_tag=autotest_tag"

        extra_params = params.get("extra_params")
        if extra_params:
            qemu_cmd += " %s" % extra_params

        bios_path = params.get("bios_path")
        if bios_path:
            qemu_cmd += " -bios %s" % bios_path

        disable_kvm_option = ""
        if (has_option(help_text, "no-kvm")):
            disable_kvm_option = " -no-kvm "

        enable_kvm_option = ""
        if (has_option(help_text, "enable-kvm")):
            enable_kvm_option = " -enable-kvm"

        if (params.get("disable_kvm", "no") == "yes"):
            params["enable_kvm"] = "no"

        if (params.get("enable_kvm", "yes") == "no"):
            qemu_cmd += disable_kvm_option
            logging.debug("qemu will run in TCG mode")
        else:
            qemu_cmd += enable_kvm_option
            logging.debug("qemu will run in KVM mode")

        self.no_shutdown = (has_option(help_text, "no-shutdown") and
                            params.get("disable_shutdown", "no") == "yes")
        if self.no_shutdown:
            qemu_cmd += " -no-shutdown "

        if params.get("enable_sga") == "yes":
            qemu_cmd += add_sga(help_text)

        return qemu_cmd


    def _nic_tap_add_helper(self, nic):
        if nic.nettype == 'macvtap':
            logging.info("Adding macvtap ifname: %s" , nic.ifname)
            utils_net.add_nic_macvtap(nic)
        else:
            nic.tapfd = str(utils_net.open_tap("/dev/net/tun", nic.ifname,
                                               vnet_hdr=True))
            logging.debug("Adding VM %s NIC ifname %s to bridge %s",
                          self.name, nic.ifname, nic.netdst)
            if nic.nettype == 'bridge':
                utils_net.add_to_bridge(nic.ifname, nic.netdst)
            utils_net.bring_up_ifname(nic.ifname)


    def _nic_tap_remove_helper(self, nic):
        try:
            if nic.nettype == 'macvtap':
                logging.info("Remove macvtap ifname %s", nic.ifname)
                tap = utils_net.Macvtap(nic.ifname)
                tap.delete()
            else:
                logging.debug("Removing VM %s NIC ifname %s from bridge %s",
                             self.name, nic.ifname, nic.netdst)
                os.close(int(nic.tapfd))
        except TypeError:
            pass


    @error.context_aware
    def create(self, name=None, params=None, root_dir=None,
               timeout=virt_vm.BaseVM.CREATE_TIMEOUT, migration_mode=None,
               migration_exec_cmd=None, migration_fd=None,
               mac_source=None):
        """
        Start the VM by running a qemu command.
        All parameters are optional. If name, params or root_dir are not
        supplied, the respective values stored as class attributes are used.

        @param name: The name of the object
        @param params: A dict containing VM params
        @param root_dir: Base directory for relative filenames
        @param migration_mode: If supplied, start VM for incoming migration
                using this protocol (either 'tcp', 'unix' or 'exec')
        @param migration_exec_cmd: Command to embed in '-incoming "exec: ..."'
                (e.g. 'gzip -c -d filename') if migration_mode is 'exec'
                default to listening on a random TCP port
        @param migration_fd: Open descriptor from machine should migrate.
        @param mac_source: A VM object from which to copy MAC addresses. If not
                specified, new addresses will be generated.

        @raise VMCreateError: If qemu terminates unexpectedly
        @raise VMKVMInitError: If KVM initialization fails
        @raise VMHugePageError: If hugepage initialization fails
        @raise VMImageMissingError: If a CD image is missing
        @raise VMHashMismatchError: If a CD image hash has doesn't match the
                expected hash
        @raise VMBadPATypeError: If an unsupported PCI assignment type is
                requested
        @raise VMPAError: If no PCI assignable devices could be assigned
        @raise TAPCreationError: If fail to create tap fd
        @raise BRAddIfError: If fail to add a tap to a bridge
        @raise TAPBringUpError: If fail to bring up a tap
        """
        error.context("creating '%s'" % self.name)
        self.destroy(free_mac_addresses=False)

        if name is not None:
            self.name = name
        if params is not None:
            self.params = params
        if root_dir is not None:
            self.root_dir = root_dir
        name = self.name
        params = self.params
        root_dir = self.root_dir

        # Verify the md5sum of the ISO images
        for cdrom in params.objects("cdroms"):
            cdrom_params = params.object_params(cdrom)
            iso = cdrom_params.get("cdrom")
            if iso:
                iso = utils_misc.get_path(data_dir.get_data_dir(), iso)
                if not os.path.exists(iso):
                    raise virt_vm.VMImageMissingError(iso)
                compare = False
                if cdrom_params.get("md5sum_1m"):
                    logging.debug("Comparing expected MD5 sum with MD5 sum of "
                                  "first MB of ISO file...")
                    actual_hash = utils.hash_file(iso, 1048576, method="md5")
                    expected_hash = cdrom_params.get("md5sum_1m")
                    compare = True
                elif cdrom_params.get("md5sum"):
                    logging.debug("Comparing expected MD5 sum with MD5 sum of "
                                  "ISO file...")
                    actual_hash = utils.hash_file(iso, method="md5")
                    expected_hash = cdrom_params.get("md5sum")
                    compare = True
                elif cdrom_params.get("sha1sum"):
                    logging.debug("Comparing expected SHA1 sum with SHA1 sum "
                                  "of ISO file...")
                    actual_hash = utils.hash_file(iso, method="sha1")
                    expected_hash = cdrom_params.get("sha1sum")
                    compare = True
                if compare:
                    if actual_hash == expected_hash:
                        logging.debug("Hashes match")
                    else:
                        raise virt_vm.VMHashMismatchError(actual_hash,
                                                          expected_hash)

        # Make sure the following code is not executed by more than one thread
        # at the same time
        lockfile = open("/tmp/kvm-autotest-vm-create.lock", "w+")
        fcntl.lockf(lockfile, fcntl.LOCK_EX)

        try:
            # Handle port redirections
            redir_names = params.objects("redirs")
            host_ports = utils_misc.find_free_ports(5000, 6000, len(redir_names))
            self.redirs = {}
            for i in range(len(redir_names)):
                redir_params = params.object_params(redir_names[i])
                guest_port = int(redir_params.get("guest_port"))
                self.redirs[guest_port] = host_ports[i]

            # Generate basic parameter values for all NICs and create TAP fd
            for nic in self.virtnet:
                nic_params = params.object_params(nic.nic_name)
                pa_type = nic_params.get("pci_assignable")
                if pa_type and pa_type != "no":
                    if self.pci_assignable is None:
                        self.pci_assignable = test_setup.PciAssignable(
                           driver=params.get("driver"),
                           driver_option=params.get("driver_option"),
                           host_set_flag = params.get("host_setup_flag"),
                           kvm_params = params.get("kvm_default"),
                           vf_filter_re = params.get("vf_filter_re"),
                           pf_filter_re = params.get("pf_filter_re"))
                    # Virtual Functions (VF) assignable devices
                    if pa_type == "vf":
                        self.pci_assignable.add_device(device_type=pa_type)
                    # Physical NIC (PF) assignable devices
                    elif pa_type == "pf":
                        self.pci_assignable.add_device(device_type=pa_type,
                                            name=nic_params.get("device_name"))
                    else:
                        raise virt_vm.VMBadPATypeError(pa_type)
                else:
                    # fill in key values, validate nettype
                    # note: make_create_command() calls vm.add_nic (i.e. on a copy)
                    nic = self.add_nic(**dict(nic)) # implied add_netdev
                    if mac_source:
                        # Will raise exception if source doesn't
                        # have cooresponding nic
                        logging.debug("Copying mac for nic %s from VM %s"
                                       % (nic.nic_name, mac_source.name))
                        nic.mac = mac_source.get_mac_address(nic.nic_name)
                    if nic.nettype in ['bridge', 'network', 'macvtap']:
                        self._nic_tap_add_helper(nic)
                    elif nic.nettype == 'user':
                        logging.info("Assuming dependencies met for "
                                     "user mode nic %s, and ready to go"
                                     % nic.nic_name)
                    self.virtnet.update_db()

            # Find available VNC port, if needed
            if params.get("display") == "vnc":
                self.vnc_port = utils_misc.find_free_port(5900, 6100)

            # Find random UUID if specified 'uuid = random' in config file
            if params.get("uuid") == "random":
                f = open("/proc/sys/kernel/random/uuid")
                self.uuid = f.read().strip()
                f.close()

            if self.pci_assignable is not None:
                self.pa_pci_ids = self.pci_assignable.request_devs()

                if self.pa_pci_ids:
                    logging.debug("Successfuly assigned devices: %s",
                                  self.pa_pci_ids)
                else:
                    raise virt_vm.VMPAError(pa_type)

            # Make qemu command
            try:
                qemu_command = self.make_create_command()
            except Exception:
                for nic in self.virtnet:
                    self._nic_tap_remove_helper(nic)
                # TODO: log_last_traceback is being moved into autotest.
                # use autotest.client.shared.base_utils when it's completed.
                if 'log_last_traceback' in utils.__dict__:
                    utils.log_last_traceback('Fail to create qemu command:')
                else:
                    utils_misc.log_last_traceback('Fail to create qemu'
                                                  'command:')
                raise virt_vm.VMStartError(self.name, 'Error occured while '
                                           'executing make_create_command(). '
                                           'Check the log for traceback.')

            # Add migration parameters if required
            if migration_mode == "tcp":
                self.migration_port = utils_misc.find_free_port(5200, 6000)
                qemu_command += " -incoming tcp:0:%d" % self.migration_port
            elif migration_mode == "unix":
                self.migration_file = "/tmp/migration-unix-%s" % self.instance
                qemu_command += " -incoming unix:%s" % self.migration_file
            elif migration_mode == "exec":
                if migration_exec_cmd == None:
                    self.migration_port = utils_misc.find_free_port(5200, 6000)
                    qemu_command += (' -incoming "exec:nc -l %s"' %
                                     self.migration_port)
                else:
                    qemu_command += (' -incoming "exec:%s"' %
                                     migration_exec_cmd)
            elif migration_mode == "fd":
                qemu_command += ' -incoming "fd:%d"' % (migration_fd)

            p9_fs_driver = params.get("9p_fs_driver")
            if p9_fs_driver == "proxy":
                proxy_helper_name = params.get("9p_proxy_binary",
                                               "virtfs-proxy-helper")
                proxy_helper_cmd =  utils_misc.get_path(root_dir,
                                                        proxy_helper_name)
                if not proxy_helper_cmd:
                    raise virt_vm.VMConfigMissingError(self.name,
                                                       "9p_proxy_binary")

                p9_export_dir = params.get("9p_export_dir")
                if not p9_export_dir:
                    raise virt_vm.VMConfigMissingError(self.name,
                                                       "9p_export_dir")

                proxy_helper_cmd += " -p " + p9_export_dir
                proxy_helper_cmd += " -u 0 -g 0"
                p9_socket_name = params.get("9p_socket_name")
                proxy_helper_cmd += " -s " + p9_socket_name
                proxy_helper_cmd += " -n"

                logging.info("Running Proxy Helper:\n%s", proxy_helper_cmd)
                self.process = aexpect.run_bg(proxy_helper_cmd, None,
                                              logging.info,
                                              "[9p proxy helper]",
                                              auto_close=False)

            logging.info("Running qemu command (reformatted):\n%s",
                    qemu_command.replace(" -", " \\\n    -"))
            self.qemu_command = qemu_command
            self.process = aexpect.run_bg(qemu_command, None,
                                          logging.info, "[qemu output] ",
                                          auto_close=False)

            # test doesn't need to hold tapfd's open
            for nic in self.virtnet:
                if nic.has_key('tapfd'): # implies bridge/tap
                    try:
                        os.close(int(nic.tapfd))
                        # qemu process retains access via open file
                        # remove this attribute from virtnet because
                        # fd numbers are not always predictable and
                        # vm instance must support cloning.
                        del nic['tapfd']
                    # File descriptor is already closed
                    except OSError:
                        pass

            # Make sure the process was started successfully
            if not self.process.is_alive():
                e = virt_vm.VMCreateError(qemu_command,
                                          self.process.get_status(),
                                          self.process.get_output())
                self.destroy()
                raise e

            # Establish monitor connections
            self.monitors = []
            for monitor_name in params.objects("monitors"):
                monitor_params = params.object_params(monitor_name)
                # Wait for monitor connection to succeed
                end_time = time.time() + timeout
                while time.time() < end_time:
                    try:
                        if monitor_params.get("monitor_type") == "qmp":
                            if utils_misc.qemu_has_option("qmp",
                                                          self.qemu_binary):
                                # Add a QMP monitor
                                monitor = qemu_monitor.QMPMonitor(
                                    monitor_name,
                                    self.get_monitor_filename(monitor_name))
                            else:
                                logging.warn("qmp monitor is unsupported, "
                                             "using human monitor instead.")
                                # Add a "human" monitor
                                monitor = qemu_monitor.HumanMonitor(
                                    monitor_name,
                                    self.get_monitor_filename(monitor_name))
                        else:
                            # Add a "human" monitor
                            monitor = qemu_monitor.HumanMonitor(
                                monitor_name,
                                self.get_monitor_filename(monitor_name))
                        monitor.verify_responsive()
                        break
                    except qemu_monitor.MonitorError, e:
                        logging.warn(e)
                        time.sleep(1)
                else:
                    e = qemu_monitor.MonitorConnectError(monitor_name)
                    self.destroy()
                    raise e
                # Add this monitor to the list
                self.monitors += [monitor]

            # Create isa serial ports.
            self.serial_ports = []
            for serial in params.objects("isa_serials"):
                self.serial_ports.append(serial)

            # Create virtio_ports (virtio_serialports and virtio_consoles)
            i = 0
            self.virtio_ports = []
            for port in params.objects("virtio_ports"):
                port_params = params.object_params(port)
                if port_params.get('virtio_port_chardev') == "spicevmc":
                    filename = 'dev%s' % port
                else:
                    filename = self.get_virtio_port_filename(port)
                port_name = port_params.get('virtio_port_name_prefix', None)
                if port_name:   # If port_name_prefix was used
                    port_name = port_name + str(i)
                else:           # Implicit name - port
                    port_name = port
                if port_params.get('virtio_port_type') in ("console",
                                                           "virtio_console"):
                    self.virtio_ports.append(
                            qemu_virtio_port.VirtioConsole(port, port_name,
                                                          filename))
                else:
                    self.virtio_ports.append(
                            qemu_virtio_port.VirtioSerial(port, port_name,
                                                         filename))
                i += 1

            # Get the output so far, to see if we have any problems with
            # KVM modules or with hugepage setup.
            output = self.process.get_output()

            if re.search("Could not initialize KVM", output, re.IGNORECASE):
                e = virt_vm.VMKVMInitError(qemu_command, self.process.get_output())
                self.destroy()
                raise e

            if "alloc_mem_area" in output:
                e = virt_vm.VMHugePageError(qemu_command, self.process.get_output())
                self.destroy()
                raise e

            logging.debug("VM appears to be alive with PID %s", self.get_pid())

            o = self.monitor.info("cpus")
            vcpu_thread_pattern = params.get("vcpu_thread_pattern",
                                               "thread_id=(\d+)")
            self.vcpu_threads = re.findall(vcpu_thread_pattern, str(o))
            o = commands.getoutput("ps aux")
            self.vhost_threads = re.findall("\w+\s+(\d+)\s.*\[vhost-%s\]" %
                                            self.get_pid(), o)

            # Establish a session with the serial console
            # Let's consider the first serial port as serial console.
            # Note: requires a version of netcat that supports -U
            try:
                tmp_serial = self.serial_ports[0]
            except IndexError:
                raise virt_vm.VMConfigMissingError(name, "isa_serial")

            self.serial_console = aexpect.ShellSession(
                "nc -U %s" % self.get_serial_console_filename(tmp_serial),
                auto_close=False,
                output_func=utils_misc.log_line,
                output_params=("serial-%s-%s.log" % (tmp_serial, name),),
                prompt=self.params.get("shell_prompt", "[\#\$]"))
            del tmp_serial

            for key, value in self.logs.items():
                outfile = "%s-%s.log" % (key, name)
                self.logsessions[key] = aexpect.Tail(
                    "nc -U %s" % value,
                    auto_close=False,
                    output_func=utils_misc.log_line,
                    output_params=(outfile,))
                self.logsessions[key].set_log_file(outfile)

            if params.get("paused_after_start_vm") != "yes":
                # start guest
                if self.monitor.verify_status("paused"):
                    try:
                        self.monitor.cmd("cont")
                    except qemu_monitor.QMPCmdError, e:
                        if ((e.data['class'] == "MigrationExpected") and
                            (migration_mode is not None)):
                            logging.debug("Migration did not start yet...")
                        else:
                            raise e

        finally:
            fcntl.lockf(lockfile, fcntl.LOCK_UN)
            lockfile.close()


    def wait_for_status(self, status, timeout, first=0.0, step=1.0, text=None):
        """
        Wait until the VM status changes to specified status

        @return: True in case the status has changed before timeout, otherwise
        return None.

        @param timeout: Timeout in seconds
        @param first: Time to sleep before first attempt
        @param steps: Time to sleep between attempts in seconds
        @param text: Text to print while waiting, for debug purposes
        """
        return utils_misc.wait_for(lambda: self.monitor.verify_status(status),
                                   timeout, first, step, text)


    def wait_until_paused(self, timeout):
        """
        Wait until the VM is paused.

        @return: True in case the VM is paused before timeout, otherwise
        return None.

        @param timeout: Timeout in seconds
        """
        return self.wait_for_status("paused", timeout)


    def wait_until_dead(self, timeout, first=0.0, step=1.0):
        """
        Wait until VM is dead.

        @return: True if VM is dead before timeout, otherwise returns None.

        @param timeout: Timeout in seconds
        @param first: Time to sleep before first attempt
        @param steps: Time to sleep between attempts in seconds
        """
        return utils_misc.wait_for(self.is_dead, timeout, first, step)


    def wait_for_shutdown(self, timeout=60):
        """
        Wait until guest shuts down.

        Helps until the VM is shut down by the guest.

        @return: True in case the VM was shut down, None otherwise.

        Note that the VM is not necessarily dead when this function returns
        True. If QEMU is running in -no-shutdown mode, the QEMU process
        may be still alive.
        """
        if self.no_shutdown:
            return self.wait_until_paused(timeout)
        else:
            return self.wait_until_dead(timeout, 1, 1)


    def graceful_shutdown(self, timeout=60):
        """
        Try to gracefully shut down the VM.

        @return: True if VM was successfully shut down, None otherwise.

        Note that the VM is not necessarily dead when this function returns
        True. If QEMU is running in -no-shutdown mode, the QEMU process
        may be still alive.
        """
        if self.params.get("shutdown_command"):
            # Try to destroy with shell command
            logging.debug("Shutting down VM %s (shell)", self.name)
            try:
                session = self.login()
            except (remote.LoginError, virt_vm.VMError), e:
                logging.debug(e)
            else:
                try:
                    # Send the shutdown command
                    session.sendline(self.params.get("shutdown_command"))
                    if self.wait_for_shutdown(timeout):
                        return True
                finally:
                    session.close()


    def _cleanup(self, free_mac_addresses):
        """
        Do cleanup works
            .removes VM monitor files.
            .process close
            .serial_console close
            .logsessions close
            .delete tmp files
            .free_mac_addresses, if needed
            .delete macvtap, if needed

        @param free_mac_addresses: Whether to release the VM's NICs back
                to the address pool.
        """
        self.monitors = []
        if self.pci_assignable:
            self.pci_assignable.release_devs()
            self.pci_assignable = None
        if self.process:
            self.process.close()
        if self.serial_console:
            self.serial_console.close()
        if self.logsessions:
            for key in self.logsessions:
                self.logsessions[key].close()

        # Generate the tmp file which should be deleted.
        file_list = [self.get_testlog_filename()]
        file_list += self.get_monitor_filenames()
        file_list += self.get_virtio_port_filenames()
        file_list += self.get_serial_console_filenames()
        file_list += self.logs.values()

        for f in file_list:
            try:
                os.unlink(f)
            except OSError:
                pass

        if hasattr(self, "migration_file"):
            try:
                os.unlink(self.migration_file)
            except OSError:
                pass

        if free_mac_addresses:
            for nic_index in xrange(0,len(self.virtnet)):
                self.free_mac_address(nic_index)

        for nic in self.virtnet:
            if nic.nettype == 'macvtap':
                tap = utils_net.Macvtap(nic.ifname)
                tap.delete()

    def destroy(self, gracefully=True, free_mac_addresses=True):
        """
        Destroy the VM.

        If gracefully is True, first attempt to shutdown the VM with a shell
        command.  Then, attempt to destroy the VM via the monitor with a 'quit'
        command.  If that fails, send SIGKILL to the qemu process.

        @param gracefully: If True, an attempt will be made to end the VM
                using a shell command before trying to end the qemu process
                with a 'quit' or a kill signal.
        @param free_mac_addresses: If True, the MAC addresses used by the VM
                will be freed.
        """
        try:
            # Is it already dead?
            if self.is_dead():
                return

            logging.debug("Destroying VM %s (PID %s)", self.name,
                          self.get_pid())

            kill_timeout = int(self.params.get("kill_timeout", "60"))

            if gracefully:
                self.graceful_shutdown(kill_timeout)
                if self.is_dead():
                    logging.debug("VM %s down (shell)", self.name)
                    return
                else:
                    logging.debug("VM %s failed to go down (shell)", self.name)

            if self.monitor:
                # Try to finish process with a monitor command
                logging.debug("Ending VM %s process (monitor)", self.name)
                try:
                    self.monitor.quit()
                except qemu_monitor.MonitorError, e:
                    logging.warn(e)
                else:
                    # Wait for the VM to be really dead
                    if self.wait_until_dead(5, 0.5, 0.5):
                        logging.debug("VM %s down (monitor)", self.name)
                        return
                    else:
                        logging.debug("VM %s failed to go down (monitor)",
                                      self.name)

            # If the VM isn't dead yet...
            pid = self.process.get_pid()
            logging.debug("Ending VM %s process (killing PID %s)",
                          self.name, pid)
            utils_misc.kill_process_tree(pid, 9)

            # Wait for the VM to be really dead
            if utils_misc.wait_for(self.is_dead, 5, 0.5, 0.5):
                logging.debug("VM %s down (process killed)", self.name)
                return

            # If all else fails, we've got a zombie...
            logging.error("VM %s (PID %s) is a zombie!", self.name,
                          self.process.get_pid())

        finally:
            self._cleanup(free_mac_addresses)


    @property
    def monitor(self):
        """
        Return the main monitor object, selected by the parameter main_monitor.
        If main_monitor isn't defined, return the first monitor.
        If no monitors exist, or if main_monitor refers to a nonexistent
        monitor, return None.
        """
        for m in self.monitors:
            if m.name == self.params.get("main_monitor"):
                return m
        if self.monitors and not self.params.get("main_monitor"):
            return self.monitors[0]


    def get_monitor_filename(self, monitor_name):
        """
        Return the filename corresponding to a given monitor name.
        """
        return "/tmp/monitor-%s-%s" % (monitor_name, self.instance)


    def get_monitor_filenames(self):
        """
        Return a list of all monitor filenames (as specified in the VM's
        params).
        """
        return [self.get_monitor_filename(m) for m in
                self.params.objects("monitors")]


    def get_peer(self, netid):
        """
        Return the peer of netdev or network deivce.

        @param netid: id of netdev or device
        @return: id of the peer device otherwise None
        """
        o = self.monitor.info("network")
        network_info = o
        if isinstance(o, dict):
            network_info = o.get["return"]

        netdev_peer_re = self.params.get("netdev_peer_re")
        if not netdev_peer_re:
            default_netdev_peer_re = "\s{2,}(.*?): .*?\\\s(.*?):"
            logging.warning("Missing config netdev_peer_re for VM %s, "
                            "using default %s", self.name,
                            default_netdev_peer_re)
            netdev_peer_re = default_netdev_peer_re

        pairs = re.findall(netdev_peer_re, network_info, re.S)
        for nic, tap in pairs:
            if nic == netid:
                return tap
            if tap == netid:
                return nic

        return None


    def get_ifname(self, nic_index=0):
        """
        Return the ifname of a bridge/tap device associated with a NIC.

        @param nic_index: Index of the NIC
        """
        return self.virtnet[nic_index].ifname


    def get_pid(self):
        """
        Return the VM's PID.  If the VM is dead return None.

        @note: This works under the assumption that self.process.get_pid()
        returns the PID of the parent shell process.
        """
        try:
            children = commands.getoutput("ps --ppid=%d -o pid=" %
                                          self.process.get_pid()).split()
            return int(children[0])
        except (TypeError, IndexError, ValueError):
            return None


    def get_shell_pid(self):
        """
        Return the PID of the parent shell process.

        @note: This works under the assumption that self.process.get_pid()
        returns the PID of the parent shell process.
        """
        return self.process.get_pid()


    def get_vnc_port(self):
        """
        Return self.vnc_port.
        """

        return self.vnc_port


    def get_vcpu_pids(self):
        """
        Return the list of vcpu PIDs

        @return: the list of vcpu PIDs
        """
        return [int(_) for _ in re.findall(r'thread_id=(\d+)',
                                           self.monitor.info("cpus"))]


    def get_shared_meminfo(self):
        """
        Returns the VM's shared memory information.

        @return: Shared memory used by VM (MB)
        """
        if self.is_dead():
            logging.error("Could not get shared memory info from dead VM.")
            return None

        filename = "/proc/%d/statm" % self.get_pid()
        shm = int(open(filename).read().split()[2])
        # statm stores informations in pages, translate it to MB
        return shm * 4.0 / 1024

    def get_spice_var(self, spice_var):
        """
        Returns string value of spice variable of choice or None
        @param spice_var - spice related variable 'spice_port', ...
        """
        return self.spice_options.get(spice_var, None)

    @error.context_aware
    def hotplug_nic(self, **params):
        """
        Convenience method wrapper for add_nic() and add_netdev().

        @return: dict-like object containing nic's details
        """
        nic_name = self.add_nic(**params)["nic_name"]
        self.activate_netdev(nic_name)
        self.activate_nic(nic_name)
        return self.virtnet[nic_name]

    @error.context_aware
    def hotunplug_nic(self,nic_index_or_name):
        """
        Convenience method wrapper for del/deactivate nic and netdev.
        """
        # make sure we got a name
        nic_name = self.virtnet[nic_index_or_name].nic_name
        self.deactivate_nic(nic_name)
        self.deactivate_netdev(nic_name)
        self.del_nic(nic_name)

    @error.context_aware
    def add_netdev(self, **params):
        """
        Hotplug a netdev device.

        @param: **params: NIC info. dict.
        @return: netdev_id
        """
        nic_name = params['nic_name']
        nic = self.virtnet[nic_name]
        nic_index = self.virtnet.nic_name_index(nic_name)
        nic.set_if_none('netdev_id', utils_misc.generate_random_id())
        nic.set_if_none('ifname', self.virtnet.generate_ifname(nic_index))
        nic.set_if_none('nettype', 'bridge')
        if nic.nettype in ['bridge', 'macvtap']: # implies tap
            # destination is required, hard-code reasonable default if unset
            # nic.set_if_none('netdst', 'virbr0')
            # tapfd allocated/set in activate because requires system resources
            nic.set_if_none('tapfd_id', utils_misc.generate_random_id())
        elif nic.nettype == 'user':
            pass # nothing to do
        else: # unsupported nettype
            raise virt_vm.VMUnknownNetTypeError(self.name, nic_name,
                                                nic.nettype)
        return nic.netdev_id

    @error.context_aware
    def del_netdev(self, nic_index_or_name):
        """
        Remove netdev info. from nic on VM, does not deactivate.

        @param: netdev_id: ID set/returned from activate_netdev()
        """
        nic = self.virtnet[nic_index_or_name]
        error.context("removing netdev info from nic %s from vm %s" % (
                      nic, self.name))
        for propertea in ['netdev_id', 'ifname', 'tapfd', 'tapfd_id']:
            if nic.has_key(propertea):
                del nic[propertea]

    def add_nic(self, **params):
        """
        Add new or setup existing NIC, optionally creating netdev if None

        @param: **params: Parameters to set
        @param: nic_name: Name for existing or new device
        @param: nic_model: Model name to emulate
        @param: netdev_id: Existing qemu net device ID name, None to create new
        @param: mac: Optional MAC address, None to randomly generate.
        """
        # returns existing or new nic object
        nic = super(VM, self).add_nic(**params)
        nic_index = self.virtnet.nic_name_index(nic.nic_name)
        nic.set_if_none('vlan', str(nic_index))
        nic.set_if_none('device_id', utils_misc.generate_random_id())
        if not nic.has_key('netdev_id'):
            # virtnet items are lists that act like dicts
            nic.netdev_id = self.add_netdev(**dict(nic))
        nic.set_if_none('nic_model', params['nic_model'])
        return nic


    @error.context_aware
    def activate_netdev(self, nic_index_or_name):
        """
        Activate an inactive host-side networking device

        @raises: IndexError if nic doesn't exist
        @raises: VMUnknownNetTypeError: if nettype is unset/unsupported
        @raises: IOError if TAP device node cannot be opened
        @raises: VMAddNetDevError: if operation failed
        """
        nic = self.virtnet[nic_index_or_name]
        error.context("Activating netdev for %s based on %s" % (self.name, nic))
        msg_sfx = ("nic %s on vm %s with attach_cmd " %
                   (self.virtnet[nic_index_or_name], self.name))

        attach_cmd = "netdev_add"
        if nic.nettype == 'bridge': # implies tap
            error.context("Opening tap device node for %s " % nic.ifname,
                          logging.debug)
            nic.set_if_none('tapfd', str(utils_net.open_tap("/dev/net/tun",
                                                             nic.ifname,
                                                             vnet_hdr=False)))
            error.context("Registering tap id %s for FD %d" %
                          (nic.tapfd_id, int(nic.tapfd)), logging.debug)
            self.monitor.getfd(int(nic.tapfd), nic.tapfd_id)
            attach_cmd += " tap,id=%s,fd=%s" % (nic.device_id, nic.tapfd_id)
            error.context("Raising interface for " + msg_sfx + attach_cmd,
                          logging.debug)
            utils_net.bring_up_ifname(nic.ifname)
            error.context("Raising bridge for " + msg_sfx + attach_cmd,
                          logging.debug)
            # assume this will puke if netdst unset
            if not nic.netdst is None:
                utils_net.add_to_bridge(nic.ifname, nic.netdst)
        elif nic.nettype == 'macvtap':
            pass
        elif nic.nettype == 'user':
            attach_cmd += " user,id=%s" % nic.device_id
        else: # unsupported nettype
            raise virt_vm.VMUnknownNetTypeError(self.name, nic_index_or_name,
                                        nic.nettype)
        if nic.has_key('netdev_extra_params'):
            attach_cmd += nic.netdev_extra_params
        error.context("Hotplugging " + msg_sfx + attach_cmd, logging.debug)
        self.monitor.cmd(attach_cmd)
        network_info = self.monitor.info("network")
        if nic.device_id not in network_info:
            # Don't leave resources dangling
            self.deactivate_netdev(nic_index_or_name)
            raise virt_vm.VMAddNetDevError(("Failed to add netdev: %s for " %
                                            nic.netdev_id) + msg_sfx +
                                           attach_cmd)


    @error.context_aware
    def activate_nic(self, nic_index_or_name):
        """
        Activate an VM's inactive NIC device and verify state

        @param: nic_index_or_name: name or index number for existing NIC
        """
        error.context("Retrieving info for NIC %s on VM %s" % (
                    nic_index_or_name, self.name))
        nic = self.virtnet[nic_index_or_name]
        device_add_cmd = "device_add"
        if nic.has_key('nic_model'):
            device_add_cmd += ' driver=%s' % nic.nic_model
        device_add_cmd += ",netdev=%s" % nic.device_id
        if nic.has_key('mac'):
            device_add_cmd += ",mac=%s" % nic.mac
        device_add_cmd += ",id=%s" % nic.nic_name
        device_add_cmd += nic.get('nic_extra_params', '')
        if nic.has_key('romfile'):
            device_add_cmd += ",romfile=%s" % nic.romfile
        error.context("Activating nic on VM %s with monitor command %s" % (
                    self.name, device_add_cmd))
        self.monitor.cmd(device_add_cmd)
        error.context("Verifying nic %s shows in qtree" % nic.nic_name)
        qtree = self.monitor.info("qtree")
        if not nic.nic_name in qtree:
            logging.error(qtree)
            raise virt_vm.VMAddNicError("Device %s was not plugged into qdev"
                                        "tree" % nic.nic_name)



    @error.context_aware
    def deactivate_nic(self, nic_index_or_name, wait=20):
        """
        Reverses what activate_nic did

        @param: nic_index_or_name: name or index number for existing NIC
        @param: wait: Time test will wait for the guest to unplug the device
        """
        nic = self.virtnet[nic_index_or_name]
        error.context("Removing nic %s from VM %s" % (nic_index_or_name,
                                        self.name))
        nic_del_cmd = "device_del %s" % (nic.nic_name)
        self.monitor.cmd(nic_del_cmd)
        if wait:
            logging.info("waiting for the guest to finish the unplug")
            if not utils_misc.wait_for(lambda: nic.nic_name not in
                                       self.monitor.info("qtree"),
                                       wait, 5 ,1):
                raise virt_vm.VMDelNicError("Device is not unplugged by "
                                            "guest, please check whether the "
                                            "hotplug module was loaded in "
                                            "guest")


    @error.context_aware
    def deactivate_netdev(self, netdev_id):
        """
        Reverses what activate_netdev() did

        @param: netdev_id: ID set/returned from activate_netdev()
        """
        # FIXME: Need to down interface & remove from bridge????
        error.context("removing netdev id %s from vm %s" %
                      (netdev_id, self.name))
        self.monitor.cmd("netdev_del %s" % netdev_id)
        network_info = self.monitor.info("network")
        if netdev_id in network_info:
            raise virt_vm.VMDelNetDevError("Fail to remove netdev %s" %
                                           netdev_id)

    @error.context_aware
    def del_nic(self, nic_index_or_name):
        """
        Undefine nic prameters, reverses what add_nic did.

        @param: nic_index_or_name: name or index number for existing NIC
        @param: wait: Time test will wait for the guest to unplug the device
        """
        super(VM, self).del_nic(nic_index_or_name)


    @error.context_aware
    def send_fd(self, fd, fd_name="migfd"):
        """
        Send file descriptor over unix socket to VM.

        @param fd: File descriptor.
        @param fd_name: File descriptor identificator in VM.
        """
        error.context("Send fd %d like %s to VM %s" % (fd, fd_name, self.name))

        logging.debug("Send file descriptor %s to source VM.", fd_name)
        if self.monitor.protocol == 'human':
            self.monitor.cmd("getfd %s" % (fd_name), fd=fd)
        elif self.monitor.protocol == 'qmp':
            self.monitor.cmd("getfd", args={'fdname': fd_name}, fd=fd)
        error.context()


    def mig_finished(self):
        ret = True
        if (self.params["display"] == "spice" and
            self.get_spice_var("spice_seamless_migration") == "on"):
            s = self.monitor.info("spice")
            if isinstance(s, str):
                ret = "migrated: true" in s
            else:
                ret = s.get("migrated") == "true"
        o = self.monitor.info("migrate")
        if isinstance(o, str):
            return ret and (not "status: active" in o)
        else:
            return ret and (o.get("status") != "active")

    def mig_succeeded(self):
        o = self.monitor.info("migrate")
        if isinstance(o, str):
            return "status: completed" in o
        else:
            return o.get("status") == "completed"

    def mig_failed(self):
        o = self.monitor.info("migrate")
        if isinstance(o, str):
            return "status: failed" in o
        else:
            return o.get("status") == "failed"

    def mig_cancelled(self):
        if self.mig_succeeded():
            raise virt_vm.VMMigrateCancelError("Migration completed successfully")
        elif self.mig_failed():
            raise virt_vm.VMMigrateFailedError("Migration failed")
        o = self.monitor.info("migrate")
        if isinstance(o, str):
            return ("Migration status: cancelled" in o or
                    "Migration status: canceled" in o)
        else:
            return (o.get("status") == "cancelled" or
                    o.get("status") == "canceled")

    def wait_for_migration(self, timeout):
        if not utils_misc.wait_for(self.mig_finished, timeout, 2, 2,
                                  "Waiting for migration to complete"):
            raise virt_vm.VMMigrateTimeoutError("Timeout expired while waiting"
                                        " for migration to finish")


    @error.context_aware
    def migrate(self, timeout=virt_vm.BaseVM.MIGRATE_TIMEOUT, protocol="tcp",
                cancel_delay=None, offline=False, stable_check=False,
                clean=True, save_path="/tmp", dest_host="localhost",
                remote_port=None, not_wait_for_migration=False,
                fd_src=None, fd_dst=None, migration_exec_cmd_src=None,
                migration_exec_cmd_dst=None):
        """
        Migrate the VM.

        If the migration is local, the VM object's state is switched with that
        of the destination VM.  Otherwise, the state is switched with that of
        a dead VM (returned by self.clone()).

        @param timeout: Time to wait for migration to complete.
        @param protocol: Migration protocol (as defined in MIGRATION_PROTOS)
        @param cancel_delay: If provided, specifies a time duration after which
                migration will be canceled.  Used for testing migrate_cancel.
        @param offline: If True, pause the source VM before migration.
        @param stable_check: If True, compare the VM's state after migration to
                its state before migration and raise an exception if they
                differ.
        @param clean: If True, delete the saved state files (relevant only if
                stable_check is also True).
        @save_path: The path for state files.
        @param dest_host: Destination host (defaults to 'localhost').
        @param remote_port: Port to use for remote migration.
        @param not_wait_for_migration: If True migration start but not wait till
                the end of migration.
        @param fd_s: File descriptor for migration to which source
                     VM write data. Descriptor is closed during the migration.
        @param fd_d: File descriptor for migration from which destination
                     VM read data.
        @param migration_exec_cmd_src: Command to embed in '-incoming "exec: "'
                (e.g. 'exec:gzip -c > filename') if migration_mode is 'exec'
                default to listening on a random TCP port
        @param migration_exec_cmd_dst: Command to embed in '-incoming "exec: "'
                (e.g. 'gzip -c -d filename') if migration_mode is 'exec'
                default to listening on a random TCP port
        """
        if protocol not in self.MIGRATION_PROTOS:
            raise virt_vm.VMMigrateProtoUnsupportedError

        error.base_context("migrating '%s'" % self.name)

        local = dest_host == "localhost"
        mig_fd_name = None

        if protocol == "fd":
            #Check if descriptors aren't None for local migration.
            if local and (fd_dst is None or fd_src is None):
                (fd_dst, fd_src) = os.pipe()

            mig_fd_name = "migfd_%d_%d" % (fd_src, time.time())
            self.send_fd(fd_src, mig_fd_name)
            os.close(fd_src)

        clone = self.clone()
        if local:
            error.context("creating destination VM")
            if stable_check:
                # Pause the dest vm after creation
                extra_params = clone.params.get("extra_params", "") + " -S"
                clone.params["extra_params"] = extra_params
            clone.create(migration_mode=protocol, mac_source=self,
                         migration_fd=fd_dst,
                         migration_exec_cmd=migration_exec_cmd_dst)
            if fd_dst:
                os.close(fd_dst)
            error.context()

        try:
            if self.params["display"] == "spice":
                host_ip = utils_net.get_host_ip_address(self.params)
                dest_port = clone.spice_options['spice_port']
                if self.params["spice_ssl"] == "yes":
                    dest_tls_port = clone.spice_options["spice_tls_port"]
                    cert_subj = clone.spice_options["spice_x509_server_subj"]
                    cert_subj = "\"%s\"" % cert_subj.replace('/',',')[1:]
                else:
                    dest_tls_port = ""
                    cert_subj = ""
                logging.debug("Informing migration to spice client")
                commands = ["__com.redhat_spice_migrate_info",
                            "spice_migrate_info",
                            "client_migrate_info"]

                if self.monitor.protocol == "human":
                    out = self.monitor.cmd("help", debug=False)
                    for command in commands:
                        if "\n%s" % command in out:
                            # spice_migrate_info requires host_ip, dest_port
                            if command in commands[:2]:
                                command = "%s %s %s %s %s" % (command, host_ip,
                                                        dest_port, dest_tls_port,
                                                        cert_subj)
                            # client_migrate_info also requires protocol
                            else:
                                command = "%s %s %s %s %s %s" % (command,
                                                         self.params['display'],
                                                         host_ip, dest_port,
                                                         dest_tls_port, cert_subj)
                            break
                    self.monitor.cmd(command)

                elif self.monitor.protocol == "qmp":
                    out = self.monitor.cmd_obj({"execute": "query-commands"})
                    for command in commands:
                        if {'name': command} in out['return']:
                            # spice_migrate_info requires host_ip, dest_port
                            if command in commands[:2]:
                                command_dict = {"execute": command,
                                                "arguments":
                                                 {"hostname": host_ip,
                                                  "port": dest_port,
                                                  "tls-port": dest_tls_port,
                                                  "cert-subject": cert_subj}}
                            # client_migrate_info also requires protocol
                            else:
                                command_dict = {"execute": command,
                                                "arguments":
                                            {"protocol": self.params['display'],
                                             "hostname": host_ip,
                                             "port": dest_port,
                                             "tls-port": dest_tls_port,
                                             "cert-subject": cert_subj}}
                            break
                    self.monitor.cmd_obj(command_dict)

            if protocol == "tcp":
                if local:
                    uri = "tcp:0:%d" % clone.migration_port
                else:
                    uri = "tcp:%s:%d" % (dest_host, remote_port)
            elif protocol == "unix":
                uri = "unix:%s" % clone.migration_file
            elif protocol == "exec":
                if local:
                    if not migration_exec_cmd_src:
                        uri = '"exec:nc localhost %s"' % clone.migration_port
                    else:
                        uri = '"exec:%s"' % (migration_exec_cmd_src)
                else:
                    uri = '"exec:%s"' % (migration_exec_cmd_src)
            elif protocol == "fd":
                uri = "fd:%s" % mig_fd_name

            if offline == True:
                self.monitor.cmd("stop")

            logging.info("Migrating to %s", uri)
            self.monitor.migrate(uri)
            if not_wait_for_migration:
                return clone

            if cancel_delay:
                time.sleep(cancel_delay)
                self.monitor.cmd("migrate_cancel")
                if not utils_misc.wait_for(self.mig_cancelled, 60, 2, 2,
                                          "Waiting for migration "
                                          "cancellation"):
                    raise virt_vm.VMMigrateCancelError("Cannot cancel migration")
                return

            self.wait_for_migration(timeout)

            self.verify_alive()

            # Report migration status
            if self.mig_succeeded():
                logging.info("Migration completed successfully")
            elif self.mig_failed():
                raise virt_vm.VMMigrateFailedError("Migration failed")
            else:
                raise virt_vm.VMMigrateFailedError("Migration ended with "
                                                   "unknown status")

            # Switch self <-> clone
            temp = self.clone(copy_state=True)
            self.__dict__ = clone.__dict__
            clone = temp

            # From now on, clone is the source VM that will soon be destroyed
            # and self is the destination VM that will remain alive.  If this
            # is remote migration, self is a dead VM object.

            error.context("after migration")
            if local:
                time.sleep(1)
                self.verify_kernel_crash()
                self.verify_alive()

            if local and stable_check:
                try:
                    save1 = os.path.join(save_path, "src-" + clone.instance)
                    save2 = os.path.join(save_path, "dst-" + self.instance)
                    clone.save_to_file(save1)
                    self.save_to_file(save2)
                    # Fail if we see deltas
                    md5_save1 = utils.hash_file(save1)
                    md5_save2 = utils.hash_file(save2)
                    if md5_save1 != md5_save2:
                        raise virt_vm.VMMigrateStateMismatchError()
                finally:
                    if clean:
                        if os.path.isfile(save1):
                            os.remove(save1)
                        if os.path.isfile(save2):
                            os.remove(save2)

        finally:
            # If we're doing remote migration and it's completed successfully,
            # self points to a dead VM object
            if not not_wait_for_migration:
                if self.is_alive():
                    self.monitor.cmd("cont")
                clone.destroy(gracefully=False)


    @error.context_aware
    def reboot(self, session=None, method="shell", nic_index=0,
               timeout=virt_vm.BaseVM.REBOOT_TIMEOUT):
        """
        Reboot the VM and wait for it to come back up by trying to log in until
        timeout expires.

        @param session: A shell session object or None.
        @param method: Reboot method.  Can be "shell" (send a shell reboot
                command) or "system_reset" (send a system_reset monitor command).
        @param nic_index: Index of NIC to access in the VM, when logging in
                after rebooting.
        @param timeout: Time to wait for login to succeed (after rebooting).
        @return: A new shell session object.
        """
        error.base_context("rebooting '%s'" % self.name, logging.info)
        error.context("before reboot")
        error.context()

        if method == "shell":
            session = session or self.login()
            session.sendline(self.params.get("reboot_command"))
            error.context("waiting for guest to go down", logging.info)
            if not utils_misc.wait_for(
                lambda:
                    not session.is_responsive(timeout=self.CLOSE_SESSION_TIMEOUT),
                timeout / 2, 0, 1):
                raise virt_vm.VMRebootError("Guest refuses to go down")
            session.close()

        elif method == "system_reset":
            # Clear the event list of all QMP monitors
            qmp_monitors = [m for m in self.monitors if m.protocol == "qmp"]
            for m in qmp_monitors:
                m.clear_events()
            # Send a system_reset monitor command
            self.monitor.cmd("system_reset")
            # Look for RESET QMP events
            time.sleep(1)
            for m in qmp_monitors:
                if m.get_event("RESET"):
                    logging.info("RESET QMP event received")
                else:
                    raise virt_vm.VMRebootError("RESET QMP event not received "
                                                "after system_reset "
                                                "(monitor '%s')" % m.name)
        else:
            raise virt_vm.VMRebootError("Unknown reboot method: %s" % method)

        error.context("logging in after reboot", logging.info)
        return self.wait_for_login(nic_index, timeout=timeout)


    def send_key(self, keystr):
        """
        Send a key event to the VM.

        @param: keystr: A key event string (e.g. "ctrl-alt-delete")
        """
        # For compatibility with versions of QEMU that do not recognize all
        # key names: replace keyname with the hex value from the dict, which
        # QEMU will definitely accept
        key_mapping = {"comma": "0x33",
                       "dot":   "0x34",
                       "slash": "0x35"}
        for key, value in key_mapping.items():
            keystr = keystr.replace(key, value)
        self.monitor.sendkey(keystr)
        time.sleep(0.2)


    # should this really be expected from VMs of all hypervisor types?
    def screendump(self, filename, debug=True):
        try:
            if self.monitor:
                self.monitor.screendump(filename=filename, debug=debug)
        except qemu_monitor.MonitorError, e:
            logging.warn(e)


    def save_to_file(self, path):
        """
        Override BaseVM save_to_file method
        """
        self.verify_status('paused') # Throws exception if not
        # Set high speed 1TB/S
        self.monitor.migrate_set_speed(2<<39)
        self.monitor.migrate_set_downtime(self.MIGRATE_TIMEOUT)
        logging.debug("Saving VM %s to %s" % (self.name, path))
        # Can only check status if background migration
        self.monitor.migrate("exec:cat>%s" % path, wait=False)
        utils_misc.wait_for(
            # no monitor.migrate-status method
            lambda : "status: completed" in self.monitor.info("migrate"),
            self.MIGRATE_TIMEOUT, 2, 2,
            "Waiting for save to %s to complete" % path)
        # Restore the speed and downtime to default values
        self.monitor.migrate_set_speed(32<<20)
        self.monitor.migrate_set_downtime(0.03)
        # Base class defines VM must be off after a save
        self.monitor.cmd("system_reset")
        self.verify_status('paused') # Throws exception if not

    def restore_from_file(self, path):
        """
        Override BaseVM restore_from_file method
        """
        self.verify_status('paused') # Throws exception if not
        logging.debug("Restoring VM %s from %s" % (self.name,path))
        # Rely on create() in incoming migration mode to do the 'right thing'
        self.create(name=self.name, params=self.params, root_dir=self.root_dir,
                    timeout=self.MIGRATE_TIMEOUT, migration_mode="exec",
                    migration_exec_cmd="cat "+path, mac_source=self)
        self.verify_status('running') # Throws exception if not


    def pause(self):
        """
        Pause the VM operation.
        """
        self.monitor.cmd("stop")


    def resume(self):
        """
        Resume the VM operation in case it's stopped.
        """
        self.monitor.cmd("cont")


    def set_link(self, netdev_name, up):
        """
        Set link up/down.

        @param name: Link name
        @param up: Bool value, True=set up this link, False=Set down this link
        """
        self.monitor.set_link(netdev_name, up)


    def get_block(self, p_dict={}):
        """
        Get specified block device from monitor's info block command.
        The block device is defined by parameter in p_dict.

        @param p_dict: Dictionary that contains parameters and its value used
                       to define specified block device.

        @return: Matched block device name, None when not find any device.
        """
        blocks_info = self.monitor.info("block")
        if isinstance(blocks_info, str):
            for block in blocks_info.splitlines():
                match = True
                for key, value in p_dict.iteritems():
                    if value == True:
                        check_str = "%s=1" % key
                    elif value == False:
                        check_str = "%s=0" % key
                    else:
                        check_str = "%s=%s" % (key, value)
                    if check_str not in block:
                        match = False
                        break
                if match:
                    return block.split(":")[0]
        else:
            for block in blocks_info:
                match = True
                for key, value in p_dict.iteritems():
                    if isinstance(value, bool):
                        check_str = "u'%s': %s" % (key, value)
                    else:
                        check_str = "u'%s': u'%s'" % (key, value)
                    if check_str not in str(block):
                        match = False
                        break
                if match:
                    return block['device']
        return None


    def check_block_locked(self, value):
        """
        Check whether specified block device is locked or not.
        Return True, if device is locked, else False.

        @param vm: VM object
        @param value: Parameter that can specify block device.
                      Can be any possible identification of a device,
                      Such as device name/image file name/...

        @return: True if device is locked, False if device is unlocked.
        """
        assert value, "Device identification not specified"

        blocks_info = self.monitor.info("block")

        assert value in str(blocks_info), \
               "Device %s not listed in monitor's output" % value

        if isinstance(blocks_info, str):
            lock_str = "locked=1"
            for block in blocks_info.splitlines():
                if (value in block) and (lock_str in block):
                    return True
        else:
            for block in blocks_info:
                if value in str(block):
                    return block['locked']
        return False


    def live_snapshot(self, base_file, snapshot_file,
                      snapshot_format="qcow2"):
        """
        Take a live disk snapshot.

        @param base_file: base file name
        @param snapshot_file: snapshot file name
        @param snapshot_format: snapshot file format

        @return: File name of disk snapshot.
        """
        device = self.get_block({"file": base_file})

        output = self.monitor.live_snapshot(device, snapshot_file,
                                            snapshot_format)
        logging.debug(output)
        device = self.get_block({"file": snapshot_file})
        if device:
            current_file = device
        else:
            current_file = None

        return current_file
