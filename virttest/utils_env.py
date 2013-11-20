import cPickle
import UserDict
import os
import logging
import re
import time

import utils_misc
import virt_vm
import aexpect
import remote

ENV_VERSION = 1


def get_env_version():
    return ENV_VERSION


class EnvSaveError(Exception):
    pass

def _update_address_cache(address_cache, line):
    if re.search("Your.IP", line, re.IGNORECASE):
        matches = re.findall(r"\d*\.\d*\.\d*\.\d*", line)
        if matches:
            address_cache["last_seen"] = matches[0]

    if re.search("Client.Ethernet.Address", line, re.IGNORECASE):
        matches = re.findall(r"\w*:\w*:\w*:\w*:\w*:\w*", line)
        if matches and address_cache.get("last_seen"):
            mac_address = matches[0].lower()
            last_time = address_cache.get("time_%s" % mac_address, 0)
            last_ip = address_cache.get("last_seen")
            cached_ip = address_cache.get(mac_address)

            if (time.time() - last_time > 5 or cached_ip != last_ip):
                logging.debug("(address cache) DHCP lease OK: %s --> %s",
                              mac_address, address_cache.get("last_seen"))

            address_cache[mac_address] = address_cache.get("last_seen")
            address_cache["time_%s" % mac_address] = time.time()
            del address_cache["last_seen"]
        elif matches:
            address_cache["last_seen_mac"] = matches[0]

    if re.search("Requested.IP", line, re.IGNORECASE):
        matches = matches = re.findall(r"\d*\.\d*\.\d*\.\d*", line)
        if matches and address_cache.get("last_seen_mac"):
            ip_address = matches[0]
            mac_address = address_cache.get("last_seen_mac")
            last_time = address_cache.get("time_%s" % mac_address, 0)

            if time.time() - last_time > 10:
                logging.debug("(address cache) DHCP lease OK: %s --> %s",
                              mac_address, ip_address)

            address_cache[mac_address] = ip_address
            address_cache["time_%s" % mac_address] = time.time()
            del address_cache["last_seen_mac"]


def _tcpdump_handler(address_cache, filename, line):
    """
    Helper for handler tcpdump output.

    :params address_cache: address cache path.
    :params filename: Log file name for tcpdump message.
    :params line: Tcpdump output message.
    """
    try:
        utils_misc.log_line(filename, line)
    except Exception, reason:
        logging.warn("Can't log tcpdump output, '%s'", reason)

    _update_address_cache(address_cache, line)


class Env(UserDict.IterableUserDict):

    """
    A dict-like object containing global objects used by tests.
    """

    def __init__(self, filename=None, version=0):
        """
        Create an empty Env object or load an existing one from a file.

        If the version recorded in the file is lower than version, or if some
        error occurs during unpickling, or if filename is not supplied,
        create an empty Env object.

        :param filename: Path to an env file.
        :param version: Required env version (int).
        """
        UserDict.IterableUserDict.__init__(self)
        empty = {"version": version}
        self._filename = filename
        self.tcpdump = None
        self.params = None
        if filename:
            try:
                if os.path.isfile(filename):
                    f = open(filename, "r")
                    env = cPickle.load(f)
                    f.close()
                    if env.get("version", 0) >= version:
                        self.data = env
                    else:
                        logging.warn(
                            "Incompatible env file found. Not using it.")
                        self.data = empty
                else:
                    # No previous env file found, proceed...
                    logging.warn("Creating new, empty env file")
                    self.data = empty
            # Almost any exception can be raised during unpickling, so let's
            # catch them all
            except Exception, e:
                logging.warn("Exception thrown while loading env")
                logging.warn(e)
                logging.warn("Creating new, empty env file")
                self.data = empty
        else:
            logging.warn("Creating new, empty env file")
            self.data = empty

    def save(self, filename=None):
        """
        Pickle the contents of the Env object into a file.

        :param filename: Filename to pickle the dict into.  If not supplied,
                use the filename from which the dict was loaded.
        """
        self.stop_tcpdump()
        filename = filename or self._filename
        if filename is None:
            raise EnvSaveError("No filename specified for this env file")
        f = open(filename, "w")
        cPickle.dump(self.data, f)
        f.close()
        if self.params:
            self.start_tcpdump(self.params)

    def get_all_vms(self):
        """
        Return a list of all VM objects in this Env object.
        """
        vm_list = []
        for key in self.data.keys():
            if key.startswith("vm__"):
                vm_list.append(self.data[key])
        return vm_list

    def clean_objects(self):
        """
        Destroy all objects registered in this Env object.
        """
        self.stop_tcpdump()
        for key in self.data:
            try:
                if key.startswith("vm__"):
                    self.data[key].destroy(gracefully=False)
            except Exception:
                pass
        self.data = {}

    def destroy(self):
        """
        Destroy all objects stored in Env and remove the backing file.
        """
        self.clean_objects()
        if self._filename is not None:
            if os.path.isfile(self._filename):
                os.unlink(self._filename)

    def get_vm(self, name):
        """
        Return a VM object by its name.

        :param name: VM name.
        """
        return self.data.get("vm__%s" % name)

    def create_vm(self, vm_type, target, name, params, bindir):
        """
        Create and register a VM in this Env object
        """
        vm_class = virt_vm.BaseVM.lookup_vm_class(vm_type, target)
        if vm_class is not None:
            vm = vm_class(name, params, bindir, self.get("address_cache"))
            self.register_vm(name, vm)
            return vm

    def register_vm(self, name, vm):
        """
        Register a VM in this Env object.

        :param name: VM name.
        :param vm: VM object.
        """
        self.data["vm__%s" % name] = vm

    def unregister_vm(self, name):
        """
        Remove a given VM.

        :param name: VM name.
        """
        del self.data["vm__%s" % name]

    def register_syncserver(self, port, server):
        """
        Register a Sync Server in this Env object.

        :param port: Sync Server port.
        :param server: Sync Server object.
        """
        self.data["sync__%s" % port] = server

    def unregister_syncserver(self, port):
        """
        Remove a given Sync Server.

        :param port: Sync Server port.
        """
        del self.data["sync__%s" % port]

    def get_syncserver(self, port):
        """
        Return a Sync Server object by its port.

        :param port: Sync Server port.
        """
        return self.data.get("sync__%s" % port)

    def register_lvmdev(self, name, lvmdev):
        """
        Register lvm device object into env;

        :param name: name of register lvmdev object
        :param lvmdev: lvmdev object;
        """
        self.data["lvmdev__%s" % name] = lvmdev

    def unregister_lvmdev(self, name):
        """
        Remove lvm device object from env;

        :param name: name of lvm device object;
        """
        del self.data["lvmdev__%s" % name]

    def get_lvmdev(self, name):
        """
        Get lvm device object by name from env;

        :param name: lvm device object name;
        :return: lvmdev object
        """
        return self.data.get("lvmdev__%s" % name)

    def _start_tcpdump(self, params):
        if "address_cache" not in self.data:
            self.data["address_cache"] = {}

        port = params.get('shell_port')
        prompt = params.get('shell_prompt')
        address = params.get('ovirt_node_address')
        username = params.get('ovirt_node_user')
        password = params.get('ovirt_node_password')

        cmd = "%s -npvi any 'port 68'" % utils_misc.find_command("tcpdump")
        if params.get("remote_preprocess") == "yes":
            login_cmd = ("ssh -o UserKnownHostsFile=/dev/null -o \
                         PreferredAuthentications=password -p %s %s@%s" %
                         (port, username, address))
            self.tcpdump = aexpect.ShellSession(
                login_cmd,
                output_func=_update_address_cache,
                output_params=(self.data["address_cache"],))

            remote.handle_prompts(self.tcpdump, username, password, prompt)
            self.tcpdump.sendline(cmd)

        else:
            self.tcpdump = aexpect.Tail(command=cmd,
                                        output_func=_tcpdump_handler,
                                        output_params=(self.data["address_cache"],
                                                       "tcpdump.log",))

        if utils_misc.wait_for(lambda: not self.tcpdump.is_alive(),
                               0.1, 0.1, 1.0):
            logging.warn("Could not start tcpdump")
            logging.warn("Status: %s", self.tcpdump.get_status())
            msg = utils_misc.format_str_for_message(self.tcpdump.get_output())
            logging.warn("Output: %s", msg)

    def start_tcpdump(self, params):
        self.params = params
        if self.tcpdump is None:
            self._start_tcpdump(params)
        else:
            if self.tcpdump.is_alive():
                logging.warning("Requested tcpdump thread start, "
                                "but there is an active thread already")
                logging.warning("Killing it and starting a new one")
                self.tcpdump.close()

            self.tcpdump = None
            self._start_tcpdump(params)

    def stop_tcpdump(self):
        if self.tcpdump is not None:
            self.tcpdump.close()
            self.tcpdump = None
