"""
Utility classes and functions to handle Virtual Machine creation using qemu.

@copyright: 2008-2009 Red Hat Inc.
"""

import time, os, logging, fcntl, re, commands, glob
from autotest.client.shared import error
from autotest.client import utils
import virt_utils, virt_vm, virt_test_setup, kvm_monitor, aexpect


class VM(virt_vm.BaseVM):
    """
    This class handles all basic VM operations.
    """

    MIGRATION_PROTOS = ['tcp', 'unix', 'exec', 'fd']

    #
    # By default we inherit all timeouts from the base VM class
    #
    LOGIN_TIMEOUT = virt_vm.BaseVM.LOGIN_TIMEOUT
    LOGIN_WAIT_TIMEOUT = virt_vm.BaseVM.LOGIN_WAIT_TIMEOUT
    COPY_FILES_TIMEOUT = virt_vm.BaseVM.COPY_FILES_TIMEOUT
    MIGRATE_TIMEOUT = virt_vm.BaseVM.MIGRATE_TIMEOUT
    REBOOT_TIMEOUT = virt_vm.BaseVM.REBOOT_TIMEOUT
    CREATE_TIMEOUT = virt_vm.BaseVM.CREATE_TIMEOUT
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
        virt_vm.BaseVM.__init__(self, name, params)

        if state:
            self.__dict__ = state
        else:
            self.process = None
            self.serial_console = None
            self.redirs = {}
            self.spice_options = {}
            self.vnc_port = 5900
            self.monitors = []
            self.pci_assignable = None
            self.netdev_id = []
            self.device_id = []
            self.tapfds = []
            self.uuid = None
            self.vcpu_threads = []
            self.vhost_threads = []


        self.name = name
        self.params = params
        self.root_dir = root_dir
        # We need this to get to the blkdebug files
        self.virt_dir = os.path.abspath(os.path.join(root_dir, "..", "..", "virt"))
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
        self.driver_type = 'kvm'


    def verify_alive(self):
        """
        Make sure the VM is alive and that the main monitor is responsive.

        @raise VMDeadError: If the VM is dead
        @raise: Various monitor exceptions if the monitor is unresponsive
        """
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


    def verify_status(self, status):
        """
        Check VM status

        @param status: Optional VM status, 'running' or 'paused'
        @raise VMStatusError: If the VM status is not same as parameter
        """
        if not self.monitor.verify_status(status):
            raise virt_vm.VMStatusError('Unexpected VM status: "%s"' %
                                        self.monitor.get_status())


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


    def __make_qemu_command(self, name=None, params=None, root_dir=None):
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
        def has_option(help, option):
            return bool(re.search(r"^-%s(\s|$)" % option, help, re.MULTILINE))

        # Wrappers for all supported qemu command line parameters.
        # This is meant to allow support for multiple qemu versions.
        # Each of these functions receives the output of 'qemu -help' as a
        # parameter, and should add the requested command line option
        # accordingly.

        def _add_option(option, value, option_type=None):
            """
            Add option to qemu parameters.
            """
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

                usb_dev = self.usb_dev_dict.get(usb)

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

            return (bus, port)

        def add_name(help, name):
            return " -name '%s'" % name

        def add_human_monitor(help, filename):
            return " -monitor unix:'%s',server,nowait" % filename

        def add_qmp_monitor(help, filename):
            return " -qmp unix:'%s',server,nowait" % filename

        def add_serial(help, filename):
            return " -serial unix:'%s',server,nowait" % filename

        def add_mem(help, mem):
            return " -m %s" % mem

        def add_smp(help, smp):
            return " -smp %s" % smp

        def add_cdrom(help, filename, index=None, format=None):
            if has_option(help, "drive"):
                name = None;
                dev = "";
                if format == "ahci":
                    name = "ahci%s" % index
                    dev += " -device ide-drive,bus=ahci.%s,drive=%s" % (index, name)
                    format = "none"
                    index = None
                if format == "usb2":
                    name = "usb2.%s" % index
                    dev += " -device usb-storage,bus=ehci.0,drive=%s" % name
                    dev += ",port=%d" % (int(index) + 1)
                    format = "none"
                    index = None
                if format is not None and format.startswith("scsi-"):
                    # handles scsi-{hd, cd, disk, block, generic} targets
                    name = "virtio-scsi-cd%s" % index
                    dev += (" -device %s,drive=%s,bus=virtio_scsi_pci.0" %
                            (format, name))
                    format = "none"
                    index = None
                cmd = " -drive file='%s',media=cdrom" % filename
                if index is not None:
                    cmd += ",index=%s" % index
                if format:
                    cmd += ",if=%s" % format
                if name:
                    cmd += ",id=%s" % name
                return cmd + dev
            else:
                return " -cdrom '%s'" % filename

        def add_drive(help, filename, index=None, format=None, cache=None,
                      werror=None, rerror=None, serial=None, snapshot=False,
                      boot=False, blkdebug=None, bus=None, port=None,
                      bootindex=None, removable=None, min_io_size=None,
                      opt_io_size=None, physical_block_size=None,
                      logical_block_size=None, readonly=False):
            name = None
            dev = ""
            if format == "ahci":
                name = "ahci%s" % index
                dev += " -device ide-drive,bus=ahci.%s,drive=%s" % (index, name)
                format = "none"
                index = None
            if format == "usb2":
                name = "usb2.%s" % index
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
                format = "none"
                index = None
            if format.startswith("scsi-"):
                # handles scsi-{hd, cd, disk, block, generic} targets
                name = "virtio-scsi%s" % index
                dev += " -device %s,bus=virtio_scsi_pci.0" % format
                dev += _add_option("drive", name)
                dev += _add_option("logical_block_size", logical_block_size)
                dev += _add_option("physical_block_size", physical_block_size)
                dev += _add_option("min_io_size", min_io_size)
                dev += _add_option("opt_io_size", opt_io_size)
                dev += _add_option("bootindex", bootindex)
                dev += _add_option("serial", serial)
                dev += _add_option("removable", removable)
                format = "none"
                index = None

            if blkdebug is not None:
                cmd = " -drive file=blkdebug:%s:%s" % (blkdebug, filename)
            else:
                cmd = " -drive file='%s'" % filename

            cmd += _add_option("index", index)
            cmd += _add_option("if", format)
            cmd += _add_option("cache", cache)
            cmd += _add_option("rerror", rerror)
            cmd += _add_option("werror", werror)
            cmd += _add_option("serial", serial)
            cmd += _add_option("snapshot", snapshot, bool)
            cmd += _add_option("boot", boot, bool)
            cmd += _add_option("id", name)
            cmd += _add_option("readonly", readonly, bool)
            return cmd + dev

        def add_nic(help, vlan, model=None, mac=None, device_id=None, netdev_id=None,
                    nic_extra_params=None):
            if model == 'none':
                return ''
            if has_option(help, "netdev"):
                netdev_vlan_str = ",netdev=%s" % netdev_id
            else:
                netdev_vlan_str = ",vlan=%d" % vlan
            if has_option(help, "device"):
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

        def add_net(help, vlan, mode, ifname=None, tftp=None, bootfile=None,
                    hostfwd=[], netdev_id=None, netdev_extra_params=None,
                    tapfd=None):
            if mode == 'none':
                return ''
            if has_option(help, "netdev"):
                cmd = " -netdev %s,id=%s" % (mode, netdev_id)
                if netdev_extra_params:
                    cmd += ",%s" % netdev_extra_params
            else:
                cmd = " -net %s,vlan=%d" % (mode, vlan)
            if mode == "tap" and tapfd:
                cmd += ",fd=%d" % tapfd
            elif mode == "user":
                if tftp and "[,tftp=" in help:
                    cmd += ",tftp='%s'" % tftp
                if bootfile and "[,bootfile=" in help:
                    cmd += ",bootfile='%s'" % bootfile
                if "[,hostfwd=" in help:
                    for host_port, guest_port in hostfwd:
                        cmd += ",hostfwd=tcp::%s-:%s" % (host_port, guest_port)
            return cmd

        def add_floppy(help, filename):
            return " -fda '%s'" % filename

        def add_tftp(help, filename):
            # If the new syntax is supported, don't add -tftp
            if "[,tftp=" in help:
                return ""
            else:
                return " -tftp '%s'" % filename

        def add_bootp(help, filename):
            # If the new syntax is supported, don't add -bootp
            if "[,bootfile=" in help:
                return ""
            else:
                return " -bootp '%s'" % filename

        def add_tcp_redir(help, host_port, guest_port):
            # If the new syntax is supported, don't add -redir
            if "[,hostfwd=" in help:
                return ""
            else:
                return " -redir tcp:%s::%s" % (host_port, guest_port)

        def add_vnc(help, vnc_port):
            return " -vnc :%d" % (vnc_port - 5900)

        def add_sdl(help):
            if has_option(help, "sdl"):
                return " -sdl"
            else:
                return ""

        def add_nographic(help):
            return " -nographic"

        def add_uuid(help, uuid):
            return " -uuid '%s'" % uuid

        def add_pcidevice(help, host):
            return " -pcidevice host='%s'" % host

        def add_spice(spice_options, port_range=(3000, 3199),
             tls_port_range=(3200, 3399)):
            """
            processes spice parameters
            @param spice_options - dict with spice keys/values
            @param port_range - tuple with port range, default: (3000, 3199)
            @param tls_port_range - tuple with tls port range,
                                    default: (3200, 3399)
            """
            spice_opts = [] # will be used for ",".join()
            tmp = None

            def optget(opt):
                """a helper function"""
                return spice_options.get(opt)

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
            s_port = str(virt_utils.find_free_port(*port_range))
            set_value("port=%s", "spice_port", "port=%s" % s_port)

            set_value("password=%s", "spice_password", "disable-ticketing")
            set_value("addr=%s", "spice_addr")

            if optget("spice_ssl") == "yes":
                # SSL only part
                t_port = str(virt_utils.find_free_port(*tls_port_range))
                set_value("tls-port=%s", "spice_tls_port",
                          "tls-port=%s" % t_port)

                prefix = optget("spice_x509_prefix")
                if optget("spice_gen_x509") == "yes":
                    c_subj = optget("spice_x509_cacert_subj")
                    s_subj = optget("spice_x509_server_subj")
                    passwd = optget("spice_x509_key_password")
                    secure = optget("spice_x509_secure")

                    virt_utils.create_x509_dir(prefix, c_subj, s_subj, passwd,
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

        def add_kernel(help, filename):
            return " -kernel '%s'" % filename

        def add_initrd(help, filename):
            return " -initrd '%s'" % filename

        def add_kernel_cmdline(help, cmdline):
            return " -append '%s'" % cmdline

        def add_testdev(help, filename):
            return (" -chardev file,id=testlog,path=%s"
                    " -device testdev,chardev=testlog" % filename)

        def add_no_hpet(help):
            if has_option(help, "no-hpet"):
                return " -no-hpet"
            else:
                return ""

        def add_cpu_flags(help, cpu_model, flags=None, vendor_id=None):
            if has_option(help, 'cpu'):
                cmd = " -cpu %s" % cpu_model

                if vendor_id:
                    cmd += ",vendor=\"%s\"" % vendor_id
                if flags:
                    cmd += ",%s" % flags

                return cmd
            else:
                return ""

        def add_machine_type(help, machine_type):
            if has_option(help, "machine") or has_option(help, "M"):
                return " -M %s" % machine_type
            else:
                return ""

        def add_usb(help, usb_id, usb_type, multifunction=False,
                    masterbus=None, firstport=None, freq=None):
            if not has_option(help, "device"):
                # Okay, for the archaic qemu which has not device parameter,
                # just return a usb uhci controller.
                # If choose this kind of usb controller, it has no name/id,
                # and only can be created once, so give it a special name.
                self.usb_dev_dict["OLDVERSION_usb0"] = []
                return " -usb"

            device_help = commands.getoutput("%s -device \\?" % qemu_binary)
            if not bool(re.search(usb_type, device_help, re.M)):
                raise virt_vm.VMDeviceNotSupportedError(self.name, usb_type)

            cmd = " -device %s" % usb_type

            cmd += _add_option("id", usb_id)
            cmd += _add_option("multifunction", multifunction)
            cmd += _add_option("masterbus", masterbus)
            cmd += _add_option("firstport", firstport)
            cmd += _add_option("freq", freq)

            # register this usb controller.
            self.usb_dev_dict[usb_id] = []
            return cmd

        def add_usbdevice(help, usb_dev, usb_type, controller_type,
                          bus=None, port=None):
            """
            This function is used to add usb device except for usb storage.
            """
            cmd = ""
            if has_option(help, "device"):
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

        # End of command line option wrappers

        if name is None:
            name = self.name
        if params is None:
            params = self.params
        if root_dir is None:
            root_dir = self.root_dir

        have_ahci = False
        have_virtio_scsi = False

        # Clone this VM using the new params
        vm = self.clone(name, params, root_dir, copy_state=True)

        qemu_binary = virt_utils.get_path(root_dir, params.get("qemu_binary",
                                                              "qemu"))
        help = commands.getoutput("%s -help" % qemu_binary)

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
        # Add numa memory cmd to pin guest memory to numa node
        if params.get("numa_node"):
            numa_node = int(params.get("numa_node"))
            if numa_node < 0:
                p = virt_utils.NumaNode(numa_node)
                n = int(p.get_node_num()) + numa_node
                qemu_cmd += "numactl -N %s -m %s " % (n, n)
            else:
                n = numa_node - 1
                qemu_cmd += "numactl -N %s -m %s " % (n, n)
        # Add the qemu binary
        qemu_cmd += qemu_binary
        # Add the VM's name
        qemu_cmd += add_name(help, name)
        # no automagic devices please
        defaults = params.get("defaults", "no")
        if has_option(help,"nodefaults") and defaults != "yes":
            qemu_cmd += " -nodefaults"
        # Add monitors
        for monitor_name in params.objects("monitors"):
            monitor_params = params.object_params(monitor_name)
            monitor_filename = vm.get_monitor_filename(monitor_name)
            if monitor_params.get("monitor_type") == "qmp":
                qemu_cmd += add_qmp_monitor(help, monitor_filename)
            else:
                qemu_cmd += add_human_monitor(help, monitor_filename)

        # Add serial console redirection
        qemu_cmd += add_serial(help, vm.get_serial_console_filename())

        # Add USB controllers
        for usb_name in params.objects("usbs"):
            usb_params = params.object_params(usb_name)
            qemu_cmd += add_usb(help, usb_name, usb_params.get("usb_type"),
                                usb_params.get("multifunction") == "on",
                                usb_params.get("masterbus"),
                                usb_params.get("firstport"),
                                usb_params.get("freq"))

        for image_name in params.objects("images"):
            image_params = params.object_params(image_name)
            if image_params.get("boot_drive") == "no":
                continue
            if image_params.get("drive_format") == "ahci" and not have_ahci:
                qemu_cmd += " -device ahci,id=ahci"
                have_ahci = True
            if (image_params.get("drive_format").startswith("scsi-")
                        and not have_virtio_scsi):
                qemu_cmd += " -device virtio-scsi,id=virtio_scsi_pci"
                have_virtio_scsi = True

            bus = None
            port = None
            if image_params.get("drive_format") == "usb2":
                bus, port = get_free_usb_port(image_name, "ehci")

            qemu_cmd += add_drive(help,
                    virt_utils.get_image_filename(image_params, root_dir),
                    image_params.get("drive_index"),
                    image_params.get("drive_format"),
                    image_params.get("drive_cache"),
                    image_params.get("drive_werror"),
                    image_params.get("drive_rerror"),
                    image_params.get("drive_serial"),
                    image_params.get("image_snapshot"),
                    image_params.get("image_boot"),
                    virt_utils.get_image_blkdebug_filename(image_params,
                                                           self.virt_dir),
                    bus,
                    port,
                    image_params.get("bootindex"),
                    image_params.get("removable"),
                    image_params.get("min_io_size"),
                    image_params.get("opt_io_size"),
                    image_params.get("physical_block_size"),
                    image_params.get("logical_block_size"),
                    image_params.get("image_readonly"))

        redirs = []
        for redir_name in params.objects("redirs"):
            redir_params = params.object_params(redir_name)
            guest_port = int(redir_params.get("guest_port"))
            host_port = vm.redirs.get(guest_port)
            redirs += [(host_port, guest_port)]

        vlan = 0
        for nic_name in params.objects("nics"):
            nic_params = params.object_params(nic_name)
            try:
                netdev_id = vm.netdev_id[vlan]
                device_id = vm.device_id[vlan]
            except IndexError:
                netdev_id = None
                device_id = None
            # Handle the '-net nic' part
            try:
                mac = vm.get_mac_address(vlan)
            except virt_vm.VMAddressError:
                mac = None
            qemu_cmd += add_nic(help, vlan, nic_params.get("nic_model"), mac,
                                device_id, netdev_id, nic_params.get("nic_extra_params"))
            # Handle the '-net tap' or '-net user' or '-netdev' part
            tftp = nic_params.get("tftp")
            if tftp:
                tftp = virt_utils.get_path(root_dir, tftp)
            if nic_params.get("nic_mode") == "tap":
                try:
                    tapfd = vm.tapfds[vlan]
                except Exception:
                    tapfd = None
            else:
                tapfd = None
            qemu_cmd += add_net(help, vlan,
                                nic_params.get("nic_mode", "user"),
                                vm.get_ifname(vlan), tftp,
                                nic_params.get("bootp"), redirs, netdev_id,
                                nic_params.get("netdev_extra_params"),
                                tapfd)
            # Proceed to next NIC
            vlan += 1

        mem = params.get("mem")
        if mem:
            qemu_cmd += add_mem(help, mem)

        smp = params.get("smp")
        if smp:
            qemu_cmd += add_smp(help, smp)

        cpu_model = params.get("cpu_model")
        if cpu_model:
            vendor = params.get("cpu_model_vendor")
            flags = params.get("cpu_model_flags")
            qemu_cmd += add_cpu_flags(help, cpu_model, vendor, flags)

        machine_type = params.get("machine_type")
        if machine_type:
            qemu_cmd += add_machine_type(help, machine_type)

        for cdrom in params.objects("cdroms"):
            cd_format = params.get("cd_format", "")
            cdrom_params = params.object_params(cdrom)
            iso = cdrom_params.get("cdrom")
            if cd_format == "ahci" and not have_ahci:
                qemu_cmd += " -device ahci,id=ahci"
                have_ahci = True
            if cd_format.startswith("scsi-") and not have_virtio_scsi:
                qemu_cmd += " -device virtio-scsi,id=virtio_scsi_pci"
                have_virtio_scsi = True
            if iso:
                qemu_cmd += add_cdrom(help, virt_utils.get_path(root_dir, iso),
                                      cdrom_params.get("drive_index"),
                                      cd_format)

        # We may want to add {floppy_otps} parameter for -fda
        # {fat:floppy:}/path/. However vvfat is not usually recommended.
        floppy = params.get("floppy")
        if floppy:
            floppy = virt_utils.get_path(root_dir, floppy)
            qemu_cmd += add_floppy(help, floppy)

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

            qemu_cmd += add_usbdevice(help, usb_dev, usb_type, controller_type,
                                      bus, port)

        tftp = params.get("tftp")
        if tftp:
            tftp = virt_utils.get_path(root_dir, tftp)
            qemu_cmd += add_tftp(help, tftp)

        bootp = params.get("bootp")
        if bootp:
            qemu_cmd += add_bootp(help, bootp)

        kernel = params.get("kernel")
        if kernel:
            kernel = virt_utils.get_path(root_dir, kernel)
            qemu_cmd += add_kernel(help, kernel)

        kernel_params = params.get("kernel_params")
        if kernel_params:
            qemu_cmd += add_kernel_cmdline(help, kernel_params)

        initrd = params.get("initrd")
        if initrd:
            initrd = virt_utils.get_path(root_dir, initrd)
            qemu_cmd += add_initrd(help, initrd)

        for host_port, guest_port in redirs:
            qemu_cmd += add_tcp_redir(help, host_port, guest_port)

        if params.get("display") == "vnc":
            qemu_cmd += add_vnc(help, vm.vnc_port)
        elif params.get("display") == "sdl":
            qemu_cmd += add_sdl(help)
        elif params.get("display") == "nographic":
            qemu_cmd += add_nographic(help)
        elif params.get("display") == "spice":
            qemu_cmd += add_spice(vm.spice_options)

        vga = params.get("vga", None)
        if vga:
            qemu_cmd += add_vga(vga)

            if vga == "qxl":
                qxl_dev_memory = int(params.get("qxl_dev_memory", 0))
                qxl_dev_nr = int(params.get("qxl_dev_nr", 1))
                qemu_cmd += add_qxl(qxl_dev_nr, qxl_dev_memory)

        if params.get("uuid") == "random":
            qemu_cmd += add_uuid(help, vm.uuid)
        elif params.get("uuid"):
            qemu_cmd += add_uuid(help, params.get("uuid"))

        if params.get("testdev") == "yes":
            qemu_cmd += add_testdev(help, vm.get_testlog_filename())

        if params.get("disable_hpet") == "yes":
            qemu_cmd += add_no_hpet(help)

        # If the PCI assignment step went OK, add each one of the PCI assigned
        # devices to the qemu command line.
        if vm.pci_assignable:
            for pci_id in vm.pa_pci_ids:
                qemu_cmd += add_pcidevice(help, pci_id)

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

        return qemu_cmd


    @error.context_aware
    def create(self, name=None, params=None, root_dir=None,
               timeout=CREATE_TIMEOUT, migration_mode=None,
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
                iso = virt_utils.get_path(root_dir, iso)
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
            host_ports = virt_utils.find_free_ports(5000, 6000, len(redir_names))
            self.redirs = {}
            for i in range(len(redir_names)):
                redir_params = params.object_params(redir_names[i])
                guest_port = int(redir_params.get("guest_port"))
                self.redirs[guest_port] = host_ports[i]

            # Generate netdev IDs for all NICs and create TAP fd
            self.netdev_id = []
            self.tapfds = []
            vlan = 0
            for nic in params.objects("nics"):
                self.netdev_id.append(virt_utils.generate_random_id())
                self.device_id.append(virt_utils.generate_random_id())
                nic_params = params.object_params(nic)
                if nic_params.get("nic_mode") == "tap":
                    ifname = self.get_ifname(vlan)
                    brname = nic_params.get("bridge")
                    tapfd = virt_utils.open_tap("/dev/net/tun", ifname)
                    virt_utils.add_to_bridge(ifname, brname)
                    virt_utils.bring_up_ifname(ifname)
                    self.tapfds.append(tapfd)
                vlan += 1

            # Find available VNC port, if needed
            if params.get("display") == "vnc":
                self.vnc_port = virt_utils.find_free_port(5900, 6100)

            # Get all SPICE options
            if params.get("display") == "spice":
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
                )

                for skey in spice_keys:
                    value = params.get(skey, None)
                    if value:
                        self.spice_options[skey] = value

            # Find random UUID if specified 'uuid = random' in config file
            if params.get("uuid") == "random":
                f = open("/proc/sys/kernel/random/uuid")
                self.uuid = f.read().strip()
                f.close()

            # Generate or copy MAC addresses for all NICs
            num_nics = len(params.objects("nics"))
            for vlan in range(num_nics):
                nic_name = params.objects("nics")[vlan]
                nic_params = params.object_params(nic_name)
                mac = (nic_params.get("nic_mac") or
                       mac_source and mac_source.get_mac_address(vlan))
                if mac:
                    virt_utils.set_mac_address(self.instance, vlan, mac)
                else:
                    mac = virt_utils.generate_mac_address(self.instance, vlan)

                if nic_params.get("ip"):
                    self.address_cache[mac] = nic_params.get("ip")
                    logging.debug("(address cache) Adding static cache entry: "
                                  "%s ---> %s" % (mac, nic_params.get("ip")))

            # Assign a PCI assignable device
            self.pci_assignable = None
            pa_type = params.get("pci_assignable")
            if pa_type and pa_type != "no":
                pa_devices_requested = params.get("devices_requested")

                # Virtual Functions (VF) assignable devices
                if pa_type == "vf":
                    self.pci_assignable = virt_utils.PciAssignable(
                        type=pa_type,
                        driver=params.get("driver"),
                        driver_option=params.get("driver_option"),
                        devices_requested=pa_devices_requested)
                # Physical NIC (PF) assignable devices
                elif pa_type == "pf":
                    self.pci_assignable = virt_utils.PciAssignable(
                        type=pa_type,
                        names=params.get("device_names"),
                        devices_requested=pa_devices_requested)
                # Working with both VF and PF
                elif pa_type == "mixed":
                    self.pci_assignable = virt_utils.PciAssignable(
                        type=pa_type,
                        driver=params.get("driver"),
                        driver_option=params.get("driver_option"),
                        names=params.get("device_names"),
                        devices_requested=pa_devices_requested)
                else:
                    raise virt_vm.VMBadPATypeError(pa_type)

                self.pa_pci_ids = self.pci_assignable.request_devs()

                if self.pa_pci_ids:
                    logging.debug("Successfuly assigned devices: %s",
                                  self.pa_pci_ids)
                else:
                    raise virt_vm.VMPAError(pa_type)

            # Make qemu command
            qemu_command = self.__make_qemu_command()

            # Add migration parameters if required
            if migration_mode == "tcp":
                self.migration_port = virt_utils.find_free_port(5200, 6000)
                qemu_command += " -incoming tcp:0:%d" % self.migration_port
            elif migration_mode == "unix":
                self.migration_file = "/tmp/migration-unix-%s" % self.instance
                qemu_command += " -incoming unix:%s" % self.migration_file
            elif migration_mode == "exec":
                if migration_exec_cmd == None:
                    self.migration_port = virt_utils.find_free_port(5200, 6000)
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
                proxy_helper_cmd =  virt_utils.get_path(root_dir,
                                                        proxy_helper_name)
                if not proxy_helper_cmd:
                    raise virt_vm.VMCreateError("Proxy command not specified")

                p9_export_dir = params.get("9p_export_dir")
                if not p9_export_dir:
                    raise virt_vm.VMCreateError("Export dir not specified")

                proxy_helper_cmd += " -p " + p9_export_dir
                proxy_helper_cmd += " -u 0 -g 0"
                p9_socket_name = params.get("9p_socket_name")
                proxy_helper_cmd += " -s " + p9_socket_name
                proxy_helper_cmd += " -n"

                logging.info("Running Proxy Helper:\n%s", proxy_helper_cmd)
                self.process = aexpect.run_bg(proxy_helper_cmd, None,
                                              logging.info,
                                              "[9p proxy helper]")

            logging.info("Running qemu command:\n%s", qemu_command)
            self.process = aexpect.run_bg(qemu_command, None,
                                          logging.info, "[qemu output] ")
            for tapfd in self.tapfds:
                try:
                    os.close(tapfd)
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
                            # Add a QMP monitor
                            monitor = kvm_monitor.QMPMonitor(
                                monitor_name,
                                self.get_monitor_filename(monitor_name))
                        else:
                            # Add a "human" monitor
                            monitor = kvm_monitor.HumanMonitor(
                                monitor_name,
                                self.get_monitor_filename(monitor_name))
                        monitor.verify_responsive()
                        break
                    except kvm_monitor.MonitorError, e:
                        logging.warn(e)
                        time.sleep(1)
                else:
                    self.destroy()
                    raise e
                # Add this monitor to the list
                self.monitors += [monitor]

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

            # Establish a session with the serial console -- requires a version
            # of netcat that supports -U
            self.serial_console = aexpect.ShellSession(
                "nc -U %s" % self.get_serial_console_filename(),
                auto_close=False,
                output_func=virt_utils.log_line,
                output_params=("serial-%s.log" % name,),
                prompt=self.params.get("shell_prompt", "[\#\$]"))

        finally:
            fcntl.lockf(lockfile, fcntl.LOCK_UN)
            lockfile.close()


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

            logging.debug("Destroying VM with PID %s", self.get_pid())

            if gracefully and self.params.get("shutdown_command"):
                # Try to destroy with shell command
                logging.debug("Trying to shutdown VM with shell command")
                try:
                    session = self.login()
                except (virt_utils.LoginError, virt_vm.VMError), e:
                    logging.debug(e)
                else:
                    try:
                        # Send the shutdown command
                        session.sendline(self.params.get("shutdown_command"))
                        logging.debug("Shutdown command sent; waiting for VM "
                                      "to go down")
                        if virt_utils.wait_for(self.is_dead, 60, 1, 1):
                            logging.debug("VM is down")
                            return
                    finally:
                        session.close()

            if self.monitor:
                # Try to destroy with a monitor command
                logging.debug("Trying to kill VM with monitor command")
                try:
                    self.monitor.quit()
                except kvm_monitor.MonitorError, e:
                    logging.warn(e)
                else:
                    # Wait for the VM to be really dead
                    if virt_utils.wait_for(self.is_dead, 5, 0.5, 0.5):
                        logging.debug("VM is down")
                        return

            # If the VM isn't dead yet...
            logging.debug("Cannot quit normally, sending a kill to close the "
                          "deal")
            virt_utils.kill_process_tree(self.process.get_pid(), 9)
            # Wait for the VM to be really dead
            if virt_utils.wait_for(self.is_dead, 5, 0.5, 0.5):
                logging.debug("VM is down")
                return

            logging.error("Process %s is a zombie!", self.process.get_pid())

        finally:
            self.monitors = []
            if self.pci_assignable:
                self.pci_assignable.release_devs()
            if self.process:
                self.process.close()
            if self.serial_console:
                self.serial_console.close()
            for f in ([self.get_testlog_filename(),
                       self.get_serial_console_filename()] +
                      self.get_monitor_filenames()):
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
                num_nics = len(self.params.objects("nics"))
                for vlan in range(num_nics):
                    self.free_mac_address(vlan)


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


    def get_address(self, index=0):
        """
        Return the address of a NIC of the guest, in host space.

        If port redirection is used, return 'localhost' (the NIC has no IP
        address of its own).  Otherwise return the NIC's IP address.

        @param index: Index of the NIC whose address is requested.
        @raise VMMACAddressMissingError: If no MAC address is defined for the
                requested NIC
        @raise VMIPAddressMissingError: If no IP address is found for the the
                NIC's MAC address
        @raise VMAddressVerificationError: If the MAC-IP address mapping cannot
                be verified (using arping)
        """
        nics = self.params.objects("nics")
        nic_name = nics[index]
        nic_params = self.params.object_params(nic_name)
        if nic_params.get("nic_mode") == "tap":
            mac = self.get_mac_address(index).lower()
            # Get the IP address from the cache
            ip = self.address_cache.get(mac)
            if not ip:
                raise virt_vm.VMIPAddressMissingError(mac)
            # Make sure the IP address is assigned to this guest
            macs = [self.get_mac_address(i) for i in range(len(nics))]
            if not virt_utils.verify_ip_address_ownership(ip, macs):
                raise virt_vm.VMAddressVerificationError(mac, ip)
            return ip
        else:
            return "localhost"


    def get_port(self, port, nic_index=0):
        """
        Return the port in host space corresponding to port in guest space.

        @param port: Port number in host space.
        @param nic_index: Index of the NIC.
        @return: If port redirection is used, return the host port redirected
                to guest port port. Otherwise return port.
        @raise VMPortNotRedirectedError: If an unredirected port is requested
                in user mode
        """
        nic_name = self.params.objects("nics")[nic_index]
        nic_params = self.params.object_params(nic_name)
        if nic_params.get("nic_mode") == "tap":
            return port
        else:
            try:
                return self.redirs[port]
            except KeyError:
                raise virt_vm.VMPortNotRedirectedError(port)


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
        Return the ifname of a tap device associated with a NIC.

        @param nic_index: Index of the NIC
        """
        nics = self.params.objects("nics")
        try:
            nic_name = nics[nic_index]
            nic_params = self.params.object_params(nic_name)
        except IndexError:
            nic_params = {}

        if nic_params.get("nic_ifname"):
            return nic_params.get("nic_ifname")
        else:
            return "t%d-%s" % (nic_index, self.instance[-11:])


    def get_mac_address(self, nic_index=0):
        """
        Return the MAC address of a NIC.

        @param nic_index: Index of the NIC
        @raise VMMACAddressMissingError: If no MAC address is defined for the
                requested NIC
        """
        nic_name = self.params.objects("nics")[nic_index]
        nic_params = self.params.object_params(nic_name)
        mac = (nic_params.get("nic_mac") or
               virt_utils.get_mac_address(self.instance, nic_index))
        if not mac:
            raise virt_vm.VMMACAddressMissingError(nic_index)
        return mac


    def free_mac_address(self, nic_index=0):
        """
        Free a NIC's MAC address.

        @param nic_index: Index of the NIC
        """
        virt_utils.free_mac_address(self.instance, nic_index)


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
    def add_netdev(self, netdev_id=None, extra_params=None):
        """
        Hotplug a netdev device.

        @param netdev_id: Optional netdev id.
        """
        brname = self.params.get("bridge")
        if netdev_id is None:
            netdev_id = virt_utils.generate_random_id()
        vlan_index = len(self.tapfds)
        ifname = self.get_ifname(vlan_index)
        logging.debug("interface name is %s" % ifname)
        tapfd = virt_utils.open_tap("/dev/net/tun", ifname, vnet_hdr=False)
        virt_utils.add_to_bridge(ifname, brname)
        virt_utils.bring_up_ifname(ifname)
        self.tapfds.append(tapfd)
        tapfd_id = virt_utils.generate_random_id()
        self.monitor.getfd(tapfd, tapfd_id)
        attach_cmd = "netdev_add tap,id=%s,fd=%s" % (netdev_id, tapfd_id)
        if extra_params is not None:
            attach_cmd += ",%s" % extra_params
        error.context("adding netdev id %s to vm %s" % (netdev_id, self.name))
        self.monitor.cmd(attach_cmd)

        network_info = self.monitor.info("network")
        if netdev_id not in network_info:
            raise virt_vm.VMAddNetDevError("Failed to add netdev: %s" %
                                           netdev_id)

        return netdev_id


    @error.context_aware
    def del_netdev(self, netdev_id):
        """
        Hot unplug a netdev device.
        """
        error.context("removing netdev id %s from vm %s" %
                      (netdev_id, self.name))
        self.monitor.cmd("netdev_del %s" % netdev_id)

        network_info = self.monitor.info("network")
        if netdev_id in network_info:
            raise virt_vm.VMDelNetDevError("Fail to remove netdev %s" %
                                           netdev_id)


    @error.context_aware
    def add_nic(self, model='rtl8139', nic_id=None, netdev_id=None, mac=None,
                romfile=None):
        """
        Hotplug a nic.

        @param model: Optional nic model.
        @param nic_id: Optional nic ID.
        @param netdev_id: Optional id of netdev.
        @param mac: Optional Mac address of new nic.
        @param rom: Optional Rom file.

        @return: Dict with added nic info. Keys:
                netdev_id = netdev id
                nic_id = nic id
                model = nic model
                mac = mac address
        """
        nic_info = {}
        nic_info['model'] = model

        if nic_id is None:
            nic_id = virt_utils.generate_random_id()
        nic_info['nic_id'] = nic_id

        if netdev_id is None:
            netdev_id = self.add_netdev()
        nic_info['netdev_id'] = netdev_id

        if mac is None:
            mac = virt_utils.generate_mac_address(self.instance, 1)
        nic_info['mac'] = mac

        device_add_cmd = "device_add driver=%s,netdev=%s,mac=%s,id=%s" % (model,
                                                                          netdev_id,
                                                                          mac, nic_id)

        if romfile is not None:
            device_add_cmd += ",romfile=%s" % romfile
        nic_info['romfile'] = romfile

        error.context("adding nic %s to vm %s" % (nic_info, self.name))
        self.monitor.cmd(device_add_cmd)

        qtree = self.monitor.info("qtree")
        if not nic_id in qtree:
            logging.error(qtree)
            raise virt_vm.VMAddNicError("Device %s was not plugged into qdev"
                                        "tree" % nic_id)

        return nic_info


    @error.context_aware
    def del_nic(self, nic_info, wait=20):
        """
        Remove the nic from pci tree.

        @vm: VM object
        @nic_info: Dictionary with nic info
        @wait: Time test will wait for the guest to unplug the device
        """
        error.context("")
        nic_del_cmd = "device_del %s" % nic_info['nic_id']
        self.monitor.cmd(nic_del_cmd)
        if wait:
            logging.info("waiting for the guest to finish the unplug")
            if not virt_utils.wait_for(lambda: nic_info['nic_id'] not in
                                       self.monitor.info("qtree"),
                                       wait, 5 ,1):
                raise virt_vm.VMDelNicError("Device is not unplugged by "
                                            "guest, please check whether the "
                                            "hotplug module was loaded in "
                                            "guest")
        self.del_netdev(nic_info['netdev_id'])


    @error.context_aware
    def send_fd(self, fd, fd_name="migfd"):
        """
        Send file descriptor over unix socket to VM.

        @param fd: File descriptor.
        @param fd_name: File descriptor identificator in VM.
        """
        error.context("Send fd %d like %s to VM %s" % (fd, fd_name, self.name))

        logging.debug("Send file descriptor %s to source VM." % fd_name)
        self.monitor.cmd("getfd %s" % (fd_name), fd=fd)
        error.context()


    @error.context_aware
    def migrate(self, timeout=MIGRATE_TIMEOUT, protocol="tcp",
                cancel_delay=None, offline=False, stable_check=False,
                clean=True, save_path="/tmp", dest_host="localhost",
                remote_port=None, fd_src=None, fd_dst=None):
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
        @param fd_s: File descriptor for migration to which source
                     VM write data. Descriptor is closed during the migration.
        @param fd_d: File descriptor for migration from which destination
                     VM read data.
        """
        if protocol not in self.MIGRATION_PROTOS:
            raise virt_vm.VMMigrateProtoUnsupportedError

        error.base_context("migrating '%s'" % self.name)

        def mig_finished():
            o = self.monitor.info("migrate")
            if isinstance(o, str):
                return "status: active" not in o
            else:
                return o.get("status") != "active"

        def mig_succeeded():
            o = self.monitor.info("migrate")
            if isinstance(o, str):
                return "status: completed" in o
            else:
                return o.get("status") == "completed"

        def mig_failed():
            o = self.monitor.info("migrate")
            if isinstance(o, str):
                return "status: failed" in o
            else:
                return o.get("status") == "failed"

        def mig_cancelled():
            o = self.monitor.info("migrate")
            if isinstance(o, str):
                return ("Migration status: cancelled" in o or
                        "Migration status: canceled" in o)
            else:
                return (o.get("status") == "cancelled" or
                        o.get("status") == "canceled")

        def wait_for_migration():
            if not virt_utils.wait_for(mig_finished, timeout, 2, 2,
                                      "Waiting for migration to complete"):
                raise virt_vm.VMMigrateTimeoutError("Timeout expired while waiting "
                                            "for migration to finish")

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
                         migration_fd=fd_dst)
            if fd_dst:
                os.close(fd_dst)
            error.context()

        try:
            if protocol == "tcp":
                if local:
                    uri = "tcp:localhost:%d" % clone.migration_port
                else:
                    uri = "tcp:%s:%d" % (dest_host, remote_port)
            elif protocol == "unix":
                uri = "unix:%s" % clone.migration_file
            elif protocol == "exec":
                uri = '"exec:nc localhost %s"' % clone.migration_port
            elif protocol == "fd":
                uri = "fd:%s" % mig_fd_name

            if offline:
                self.monitor.cmd("stop")

            logging.info("Migrating to %s", uri)
            self.monitor.migrate(uri)

            if cancel_delay:
                time.sleep(cancel_delay)
                self.monitor.cmd("migrate_cancel")
                if not virt_utils.wait_for(mig_cancelled, 60, 2, 2,
                                          "Waiting for migration "
                                          "cancellation"):
                    raise virt_vm.VMMigrateCancelError("Cannot cancel migration")
                return

            wait_for_migration()

            self.verify_kernel_crash()
            self.verify_alive()

            # Report migration status
            if mig_succeeded():
                logging.info("Migration completed successfully")
            elif mig_failed():
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
                        raise virt_vm.VMMigrateStateMismatchError(md5_save1,
                                                                  md5_save2)
                finally:
                    if clean:
                        if os.path.isfile(save1):
                            os.remove(save1)
                        if os.path.isfile(save2):
                            os.remove(save2)

        finally:
            # If we're doing remote migration and it's completed successfully,
            # self points to a dead VM object
            if self.is_alive():
                self.monitor.cmd("cont")
            clone.destroy(gracefully=False)


    @error.context_aware
    def reboot(self, session=None, method="shell", nic_index=0,
               timeout=REBOOT_TIMEOUT):
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
        session = session or self.login()
        error.context()

        if method == "shell":
            session.sendline(self.params.get("reboot_command"))
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

        error.context("waiting for guest to go down", logging.info)
        if not virt_utils.wait_for(
            lambda:
                not session.is_responsive(timeout=self.CLOSE_SESSION_TIMEOUT),
            timeout / 2, 0, 1):
            raise virt_vm.VMRebootError("Guest refuses to go down")
        session.close()

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
        dict = {"comma": "0x33",
                "dot":   "0x34",
                "slash": "0x35"}
        for key, value in dict.items():
            keystr = keystr.replace(key, value)
        self.monitor.sendkey(keystr)
        time.sleep(0.2)


    # should this really be expected from VMs of all hypervisor types?
    def screendump(self, filename, debug=True):
        try:
            if self.monitor:
                self.monitor.screendump(filename=filename, debug=debug)
        except kvm_monitor.MonitorError, e:
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
        result = virt_utils.wait_for(
            # no monitor.migrate-status method
            lambda : "status: completed" in self.monitor.info("migrate"),
            self.MIGRATE_TIMEOUT, 2, 2,
            "Waiting for save to %s to complete" % path)
        # Restore the speed and downtime to default values
        self.monitor.migrate_set_speed(32<<20)
        self.monitor.migrate_set_downtime(0.03)
        # Base class defines VM must be off after a save
        self.monitor.cmd("system_reset")
        state = self.monitor.get_status()
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

    def needs_restart(self, name, params, basedir):
        """
        Verifies whether the current qemu commandline matches the requested
        one, based on the test parameters.
        """
        return (self.__make_qemu_command() !=
                self.__make_qemu_command(name, params, basedir))


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
