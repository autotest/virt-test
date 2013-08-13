"""
Basic nfs support for Linux host. It can support the remote
nfs mount and the local nfs set up and mount.
"""
import re, os, logging
from autotest.client import os_dep
from autotest.client.shared import utils, service, error
import utils_misc


def nfs_exported():
    """
    Get the list for nfs file system already exported

    :return: a list of nfs that is already exported in system
    :rtype: a lit of nfs file system exported
    """
    exportfs = utils.system_output("exportfs -v")
    if not exportfs:
        return {}

    nfs_exported_dict = {}
    for line in exportfs.strip().splitlines():
        fs_info = line.split()
        if len(fs_info) == 2:
            nfs_src = fs_info[0]
            access_ip = re.findall(r"(.*)\(", fs_info[1])[0]
            if "world" in access_ip:
                access_ip = "*"
            nfs_tag = "%s_%s" % (nfs_src, access_ip)
            permission = re.findall(r"\((.*)\)", fs_info[1])[0]
            nfs_exported_dict[nfs_tag] = permission

    return nfs_exported_dict


class Exportfs(object):
    """
    Add or remove one entry to exported nfs file system.
    """
    def __init__(self, path, client="*", options="", ori_exported=None):
        if ori_exported is None:
            ori_exported = []
        self.path = path
        self.client = client
        self.options = options.split(",")
        self.ori_exported = ori_exported
        self.entry_tag = "%s_%s" % (self.path, self.client)
        self.already_exported = False
        self.ori_options = ""


    def is_exported(self):
        """
        Check if the directory is already exported.

        :return: If the entry is exported
        :rtype: Boolean
        """
        ori_exported = self.ori_exported or nfs_exported()
        if self.entry_tag in ori_exported.keys():
            return True
        return False


    def need_reexport(self):
        """
        Check if the entry is already exported but the options are not
        the same as we required.

        :return: Need re export the entry or not
        :rtype: Boolean
        """
        ori_exported = self.ori_exported or nfs_exported()
        if self.is_exported():
            exported_options = ori_exported[self.entry_tag]
            options = [ _ for _ in self.options if _ not in exported_options]
            if options:
                self.ori_options = exported_options
                return True
        return False


    def unexport(self):
        """
        Unexport an entry.
        """
        if self.is_exported():
            unexport_cmd = "exportfs -u %s:%s" % (self.client, self.path)
            utils.system(unexport_cmd)
        else:
            logging.warn("Target %s %s is not exported yet."
                         "Can not unexport it." % (self.client, self.path))


    def reset_export(self):
        """
        Reset the exportfs to the original status before we export the
        specific entry.
        """
        self.unexport()
        if self.ori_options:
            tmp_options = self.options
            self.options = self.ori_options.split(",")
            self.export()
            self.options = tmp_options

    def export(self):
        """
        Export one directory if it is not in exported list.

        :return: Export nfs file system succeed or not
        "rtype": Boolean
        """
        if self.is_exported():
            if self.need_reexport():
                self.unexport()
            else:
                self.already_exported = True
                logging.warn("Already exported target."
                             " Don't need export it again")
                return True
        export_cmd = "exportfs"
        if self.options:
            export_cmd += " -o %s" % ",".join(self.options)
        export_cmd += " %s:%s" % (self.client, self.path)
        try:
            utils.system(export_cmd)
        except error.CmdError, export_failed_err:
            logging.error("Can not export target: %s" % export_failed_err)
            return False
        return True


class Nfs(object):
    """
    Nfs class for handle nfs mount and umount. If a local nfs service is
    required, it will configure a local nfs server accroding the params.
    """
    def __init__(self, params):
        self.mount_dir = params.get("nfs_mount_dir")
        self.mount_options = params.get("nfs_mount_options")
        self.mount_src = params.get("nfs_mount_src")
        self.nfs_setup = False
        os_dep.command("mount")
        self.unexportfs_in_clean = False

        if params.get("setup_local_nfs") == "yes":
            self.nfs_setup = True
            os_dep.command("service")
            os_dep.command("exportfs")
            self.nfs_service = service.SpecificServiceManager("nfs")
            self.enable_pattern = r"nfsd.*?running"
            self.disable_pattern = r"nfsd.*?stopped"
            if "Loaded: error" in self.nfs_service.status():
                self.nfs_service = service.SpecificServiceManager("nfs-server")
                self.enable_pattern = r"Active: active"
                self.disable_pattern = r"Active: inactive"

            self.export_dir = (params.get("export_dir")
                               or self.mount_src.split(":")[-1])
            self.export_ip = params.get("export_ip", "*")
            self.export_options = params.get("export_options", "").strip()
            self.exportfs = Exportfs(self.export_dir, self.export_ip,
                                     self.export_options)
            self.mount_src = "127.0.0.1:%s" % self.export_dir


    def service_status(self):
        """
        Check nfs service status.

        :return: The status of nfs service. It should be one of these:
                 enabled, disabled or unknown status.
        :rtype: string
        """
        output = self.nfs_service.status()
        logging.debug("NFS sevice status is %s" % output)
        if re.findall(self.enable_pattern, output):
            return "enabled"
        if re.findall(self.disable_pattern, output):
            return "disabled"
        return "unknown status"


    def is_mounted(self):
        """
        Check the NFS is mouunted or not.

        :return: If the src is mounted as expect
        :rtype: Boolean
        """
        return utils_misc.is_mounted(self.mount_src, self.mount_dir, "nfs")


    def setup(self):
        """
        Setup NFS in host.

        Mount NFS as configured. If a local nfs is requested, setup the NFS
        service and exportfs too.
        """
        if self.nfs_setup:
            if self.service_status() != "enabled":
                logging.debug("Restart NFS service.")
                self.nfs_service.restart()

            if not os.path.isdir(self.export_dir):
                os.mkdir(self.export_dir)
            self.exportfs.export()
            self.unexportfs_in_clean = not self.exportfs.already_exported

        logging.debug("Mount %s to %s" % (self.mount_src, self.mount_dir))
        utils_misc.mount(self.mount_src, self.mount_dir, "nfs",
                         perm=self.mount_options)


    def cleanup(self):
        """
        Clean up the host env.

        Umount NFS from the mount point. If there has some change for exported
        file system in host when setup, also clean up that.
        """
        utils_misc.umount(self.mount_src, self.mount_dir, "nfs")
        if self.nfs_setup and self.unexportfs_in_clean:
            self.exportfs.reset_export()
