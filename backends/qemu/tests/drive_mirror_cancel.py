import logging
from autotest.client.shared import utils
from autotest.client.shared import error
from qemu.tests import drive_mirror


@error.context_aware
def run_drive_mirror_cancel(test, params, env):
    """
    Test block mirroring functionality

    1). boot vm then mirror $source_image to nfs/iscsi target
    2). block nfs/iscsi serivce port via iptables rules
    3). cancel block job and check it not cancel immedicatly
    4). flush iptables chain then check job canceled in 10s

    """
    tag = params.get("source_images", "image1")
    mirror_test = drive_mirror.DriveMirror(test, params, env, tag)
    try:
        mirror_test.start()
        error.context("Block network connection with iptables", logging.info)
        utils.run(params["start_firewall_cmd"])
        bg = utils.InterruptedThread(mirror_test.cancel,)
        bg.start()
        job = mirror_test.get_status()
        if job["type"] != "mirror":
            raise error.TestFail("Job cancel immediacatly")
        error.context("Cleanup rules in iptables", logging.info)
        utils.run(params["stop_firewall_cmd"])
        bg.join(timeout=int(params["cancel_timeout"]))
    finally:
        mirror_test.vm.destroy()
        mirror_test.clean()
