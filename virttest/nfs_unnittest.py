#!/usr/bin/python
import unittest, os

try:
    import autotest.common as common
except ImportError:
    import common

import nfs, utils_misc
from autotest.client.shared.test_utils import mock
from autotest.client import os_dep
from autotest.client.shared import utils, service

class FakeService(object):
    def __init__(self, service_name):
        if service_name == "nfs-server":
            nfs_msg = """Redirecting to /bin/systemctl  status nfs-server.service
nfs-server.service - NFS Server
          Loaded: loaded (/lib/systemd/system/nfs-server.service; disabled)
          Active: active (running) since Wed, 05 Jun 2013 16:41:37 +0800; 1 weeks and 2 days ago
         Process: 19087 ExecStartPost=/usr/lib/nfs-utils/scripts/nfs-server.postconfig (code=exited, status=0/SUCCESS)
         Process: 19085 ExecStartPost=/usr/sbin/rpc.mountd $RPCMOUNTDOPTS (code=exited, status=0/SUCCESS)
         Process: 19073 ExecStart=/usr/sbin/rpc.nfsd $RPCNFSDARGS ${RPCNFSDCOUNT} (code=exited, status=0/SUCCESS)
         Process: 19072 ExecStartPre=/usr/sbin/exportfs -r (code=exited, status=0/SUCCESS)
         Process: 19070 ExecStartPre=/usr/sbin/rpc.rquotad $RPCRQUOTADOPTS (code=exited, status=0/SUCCESS)
         Process: 19068 ExecStartPre=/usr/lib/nfs-utils/scripts/nfs-server.preconfig (code=exited, status=0/SUCCESS)
        Main PID: 19071 (rpc.rquotad)
          CGroup: name=systemd:/system/nfs-server.service
"""
        else:
            nfs_msg = """Redirecting to /bin/systemctl  status nfs.service
nfs.service
          Loaded: error (Reason: No such file or directory)
          Active: inactive (dead)"""
        self.fake_cmds = [{"cmd": "status", "stdout" : nfs_msg},
                          {"cmd": "restart", "stdout": ""}]


    def get_stdout(self, cmd):
        for fake_cmd in self.fake_cmds:
            if fake_cmd['cmd'] == cmd:
                return fake_cmd['stdout']
        raise ValueError("Could not locate locate '%s' on fake cmd db" % cmd)


    def status(self):
        return self.get_stdout("status")


    def restart(self):
        return self.get_stdout("restart")


class nfs_test(unittest.TestCase):
    def setup_stubs_init(self):
        os_dep.command.expect_call("mount")
        os_dep.command.expect_call("service")
        os_dep.command.expect_call("exportfs")
        service.SpecificServiceManager.expect_call("nfs").and_return(
                                                          FakeService("nfs"))
        service.SpecificServiceManager.expect_call("nfs-server").and_return(
                                                   FakeService("nfs-server"))
        mount_src = self.nfs_params.get("nfs_mount_src")
        export_dir = (self.nfs_params.get("export_dir")
                      or mount_src.split(":")[-1])
        export_ip = self.nfs_params.get("export_ip", "*")
        export_options = self.nfs_params.get("export_options", "").strip()
        nfs.Exportfs.expect_new(export_dir, export_ip, export_options)


    def setup_stubs_setup(self, nfs_obj):
        os.mkdir.expect_call(nfs_obj.export_dir)
        nfs_obj.exportfs.export.expect_call()
        utils_misc.mount.expect_call(nfs_obj.mount_src, nfs_obj.mount_dir,
                                     "nfs", perm=nfs_obj.mount_options)


    def setup_stubs_is_mounted(self, nfs_obj):
        utils_misc.is_mounted.expect_call(nfs_obj.mount_src,
                                          nfs_obj.mount_dir,
                                          "nfs").and_return(True)

    def setup_stubs_cleanup(self, nfs_obj):
        utils_misc.umount.expect_call(nfs_obj.mount_src,
                                      nfs_obj.mount_dir,
                                      "nfs")
        nfs_obj.exportfs.reset_export.expect_call()


    def setUp(self):
        self.nfs_params = {"nfs_mount_dir": "/mnt/nfstest",
                           "nfs_mount_options": "rw,no_root_squash",
                           "nfs_mount_src": "127.0.0.1:/mnt/nfssrc",
                           "setup_local_nfs": "yes",
                           "export_options": "rw"}
        self.god = mock.mock_god()
        self.god.stub_function(os_dep, "command")
        self.god.stub_function(utils, "system")
        self.god.stub_function(utils, "system_output")
        self.god.stub_function(os.path, "isfile")
        self.god.stub_function(os, "mkdir")
        self.god.stub_function(utils_misc, "is_mounted")
        self.god.stub_function(utils_misc, "mount")
        self.god.stub_function(utils_misc, "umount")
        self.god.stub_function(service, "SpecificServiceManager")
        attr = getattr(nfs, "Exportfs")
        setattr(attr, "already_exported", False)
        mock_class = self.god.create_mock_class_obj(attr, "Exportfs")
        self.god.stub_with(nfs, "Exportfs", mock_class)


    def tearDown(self):
        self.god.unstub_all()


    def test_nfs_setup(self):
        self.setup_stubs_init()
        nfs_local = nfs.Nfs(self.nfs_params)
        self.setup_stubs_setup(nfs_local)
        nfs_local.setup()
        self.assertEqual(nfs_local.service_status(), "enabled")
        self.setup_stubs_is_mounted(nfs_local)
        self.assertTrue(nfs_local.is_mounted())
        self.setup_stubs_cleanup(nfs_local)
        nfs_local.cleanup()
        self.god.check_playback()


if __name__ == "__main__":
    unittest.main()
