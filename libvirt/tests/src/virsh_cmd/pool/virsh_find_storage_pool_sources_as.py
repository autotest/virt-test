import logging
import os
from virttest import virsh, utils_test
from autotest.client import utils, lv_utils
from autotest.client.shared import error


def run(test, params, env):
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
    vg_name = params.get("vg_name", "virttest_vg_0")
    ro_flag = "yes" == params.get("readonly_mode", "no")
    status_error = "yes" == params.get("status_error", "no")

    if not source_type:
        raise error.TestFail("Command requires <type> value")

    cleanup_nfs = False
    cleanup_iscsi = False
    cleanup_logical = False

    if source_host == "localhost":
        if source_type == "netfs":
            # Set up nfs
            utils_test.libvirt.setup_or_cleanup_nfs(True)
            cleanup_nfs = True
        if source_type in ["iscsi", "logical"]:
            # Set up iscsi
            iscsi_device = utils_test.libvirt.setup_or_cleanup_iscsi(True)
            cleanup_iscsi = True
            if source_type == "logical":
                # Create VG by using iscsi device
                lv_utils.vg_create(vg_name, iscsi_device)
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
                logging.debug("Command outout:\n%s", output)
        elif status_error and status == 0:
            raise error.TestFail("Expect fail, but run successfully")
    finally:
        # Clean up
        if cleanup_logical:
            cmd = "pvs |grep %s |awk '{print $1}'" % vg_name
            pv_name = utils.system_output(cmd)
            lv_utils.vg_remove(vg_name)
            utils.run("pvremove %s" % pv_name)
        if cleanup_iscsi:
            utils_test.libvirt.setup_or_cleanup_iscsi(False)
        if cleanup_nfs:
            utils_test.libvirt.setup_or_cleanup_nfs(False)
