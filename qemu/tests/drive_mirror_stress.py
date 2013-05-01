import time, logging
from autotest.client.shared import error
from virttest import utils_misc
import drive_mirror

class BlockMirrorStress(drive_mirror.BlockMirror):

    def __init__(self, test, params, env, tag):
        super(BlockMirrorStress, self).__init__(test, params, env, tag)

    @error.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memoery stress in guest;
        """
        params = self.parser_test_args()
        cmd = params.get("start_cmd")
        session = self.get_session()
        error.context("Load stress in guest(%s)" % cmd, logging.info)
        session.sendline(cmd)
        if not self.app_runing():
            raise error.TestFail("stress app( %s) isn't running" % cmd)
        # sleep 10s to ensure heavyload.exe make guest under heayload really;
        time.sleep(10)
        return None

    @error.context_aware
    def unload_stress(self):
        """
        stop stress app
        """
        error.context("stop stress app in guest", logging.info)
        params = self.parser_test_args()
        def _unload_stress():
            session = self.get_session()
            cmd = params.get("stop_cmd")
            session.sendline(cmd)
            if not self.app_runing():
                return True
            return False

        stoped = utils_misc.wait_for(_unload_stress, first=2.0,
                                     text="wait stress app quit",
                                     step=1.0, timeout=120)
        if not stoped:
            raise error.TestFail("stress app is still runing")

    def app_runing(self):
        """
        check stress app really run in background;
        """
        session = self.get_session()
        params = self.parser_test_args()
        cmd = params.get("check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        return status == 0

    @error.context_aware
    def verify_steady(self):
        """
        verify offset not decreased, after block mirror job in steady status;
        """
        error.context("verify offset not decreased", logging.info)
        params = self.parser_test_args()
        timeout = int(params.get("hold_on_timeout", 600))
        offset = self.get_status()["offset"]
        start = time.time()
        while time.time() < start + timeout:
            _offset = self.get_status()["offset"]
            if _offset < offset:
                msg = "offset decreased, offset last: %s" % offset
                msg += "offset now: %s" % _offset
                raise error.TestFail(msg)
            offset = _offset


def run_drive_mirror_stress(test, params, env):
    """
    drive_mirror_stress test:
    1). load stress in guest
    2). mirror block device
    3). stop vm when mirroring job really run(optional)
    4). wait for block job in steady status
    5). check offset not decreased(optional)
    6). reopen new target image(optional)
    7). quit stress app, reboot guest(optional);
    8). verify guest can response correctly

    @param test: Kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = BlockMirrorStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        stress_test.start()
        stress_test.action_before_steady()
        stress_test.action_when_steady()
        stress_test.action_after_reopen()
    finally:
        stress_test.clean()
