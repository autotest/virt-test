import logging
import os
from virttest import iscsi, nfs, virsh
from autotest.client import utils
from autotest.client.shared import error


def run_virsh_find_storage_pool_sources_as(test, params, env):
    """
    Test command: virsh find-storage-pool-sources-as

    1. Prepare env to provide source storage:
       1). For 'netfs' source type, setup nfs server
       2). For 'iscsi' source type, setup iscsi server
       3). For 'logcial' type pool, setup iscsi storage to create vg
    2. Find the pool source by running virsh cmd
    """

    source_type = params.get("source_type", "")
    source_host = params.get("source_host", "localhost")
    source_port = params.get("source_port", "")
    options = params.get("extra_options", "")
    ro_flag = "yes" == params.get("readonly_mode", "no")
    status_error = "yes" == params.get("status_error", "no")

    if not source_type:
        raise error.TestFail("Command requires <type> value")

    def setup_or_cleanup_nfs(is_setup):
        """
        Set up or clean up nfs service on localhost

        :param: is_setup: Boolean value, true for setup, false for cleanup
        """
        mount_src = "127.0.0.1:" + test.tmpdir + "/nfs-export"
        mount_dir = test.tmpdir + "/nfs-mount"
        nfs_params = {"nfs_mount_dir": mount_dir,
                      "nfs_mount_options": "rw",
                      "nfs_mount_src": mount_src,
                      "setup_local_nfs": "yes",
                      "export_options": "rw,no_root_squash"}
        _nfs = nfs.Nfs(nfs_params)
        if is_setup:
            _nfs.setup()
        else:
            _nfs.unexportfs_in_clean = True
            _nfs.cleanup()

    def setup_or_cleanup_iscsi(is_setup):
        """
        Set up(and login iscsi target) or clean up iscsi service on localhost

        :param: is_setup: Boolean value, true for setup, false for cleanup
        :return: iscsi device name or nothing
        """

        emulated_image = "emulated_iscsi"
        emulated_path = os.path.join(test.tmpdir, emulated_image)
        emulated_target = "iqn.2001-01.com.virttest:%s.target" % emulated_image
        iscsi_params = {"emulated_image": emulated_path,
                        "target": emulated_target,
                        "image_size": "1G",
                        "iscsi_thread_id": "virt"}
        _iscsi = iscsi.Iscsi(iscsi_params)
        if is_setup:
            utils.run("setenforce 0")
            _iscsi.export_target()
            utils.run("setenforce 1")
            _iscsi.login()
            iscsi_device = _iscsi.get_device_name()
            logging.debug("iscsi device: %s", iscsi_device)
            return iscsi_device
        else:
            _iscsi.export_flag = True
            _iscsi.emulated_id = _iscsi.get_target_id()
            _iscsi.cleanup()
            utils.run("rm -f %s" % emulated_path)
            return ""

    cleanup_nfs = False
    cleanup_iscsi = False
    cleanup_logical = False
    vg_name = ""
    if source_host == "localhost":
        if source_type == "netfs":
            # Set up nfs
            setup_or_cleanup_nfs(True)
            cleanup_nfs = True
        if source_type in ["iscsi", "logical"]:
            # Set up iscsi
            iscsi_device = setup_or_cleanup_iscsi(True)
            cleanup_iscsi = True
            if source_type == "logical":
                # Create VG
                cmd_pv = "pvcreate %s" % iscsi_device
                vg_name = "vg_%s" % source_type
                cmd_vg = "vgcreate %s %s" % (vg_name, iscsi_device)
                utils.run(cmd_pv)
                utils.run(cmd_vg)
                cleanup_logical = True

    # Run virsh cmd
    options = "%s %s " % (source_host, source_port) + options
    if ro_flag:
        logging.debug("Readonly mode test")
    try:
        cmd_result = virsh.find_storage_pool_sources_as(
            source_type,
            options,
            ignore_status=True,
            debug=True,
            readonly=ro_flag)
        output = cmd_result.stdout.strip()
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
        if not status_error:
            if status:
                raise error.TestFail(err)
            else:
                logging.debug("Run virsh command successfully")
        elif status_error and status == 0:
            raise error.TestFail("Expect fail, but run successfully")
    finally:
        # Clean up
        if cleanup_logical:
            cmd = "pvs |grep %s |awk '{print $1}'" % vg_name
            pv_name = utils.system_output(cmd)
            utils.run("vgremove -f %s" % vg_name)
            utils.run("pvremove %s" % pv_name)
        if cleanup_iscsi:
            setup_or_cleanup_iscsi(False)
        if cleanup_nfs:
            setup_or_cleanup_nfs(False)
