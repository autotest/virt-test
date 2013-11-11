import cPickle
import UserDict
import os
import logging
import virt_vm

ENV_VERSION = 1


def get_env_version():
    return ENV_VERSION


class EnvSaveError(Exception):
    pass


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
        filename = filename or self._filename
        if filename is None:
            raise EnvSaveError("No filename specified for this env file")
        f = open(filename, "w")
        cPickle.dump(self.data, f)
        f.close()

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
        for key in self.data:
            try:
                if key.startswith("vm__"):
                    self.data[key].destroy(gracefully=False)
                elif key == "tcpdump":
                    self.data[key].close()
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
