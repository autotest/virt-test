import time, logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc
from qemu.tests import drive_mirror

class DriveMirrorStress(drive_mirror.DriveMirror):

    def __init__(self, test, params, env, tag):
        super(DriveMirrorStress, self).__init__(test, params, env, tag)

    @error.context_aware
    def install_stress_app(self):
        params = self.parser_test_args()
        session = self.get_session()
        if session.cmd_status(params.get("app_check_cmd","true")) == 0:
            return True
        error.context("install stress app in guest", logging.info)
        link = params.get("download_link")
        md5sum = params.get("pkg_md5sum")
        tmp_dir = params.get("tmp_dir")
        install_cmd = params.get("install_cmd")
        config_cmd = params.get("config_cmd")
        logging.info("Fetch package: %s" % link)
        pkg = utils.unmap_url_cache(self.test.tmpdir, link, md5sum)
        self.vm.copy_files_to(pkg, tmp_dir)
        logging.info("Install app: %s" % install_cmd)
        s, o = session.cmd_status_output(install_cmd, timeout=300)
        if s != 0:
            raise error.TestError("Fail to install stress app(%s)"  % o)
        logging.info("Configure app: %s" % config_cmd)
        s, o = session.cmd_status_output(config_cmd, timeout=300)
        if s != 0:
            raise error.TestError("Fail to conifg stress app(%s)"  % o)


    @error.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memory stress in guest;
        """
        params = self.parser_test_args()
        self.install_stress_app()
        cmd = params.get("start_cmd")
        session = self.get_session()
        error.context("launch stress app in guest", logging.info)
        session.sendline(cmd)
        logging.info("Start command: %s" % cmd)
        running = utils_misc.wait_for(self.app_runing, timeout=150, step=5)
        if not running:
            raise error.TestFail("stress app isn't running")
        return None

    @error.context_aware
    def unload_stress(self):
        """
        stop stress app
        """
        def _unload_stress():
            params = self.parser_test_args()
            session = self.get_session()
            cmd = params.get("stop_cmd")
            session.sendline(cmd)
            if not self.app_runing():
                return True
            return False

        error.context("stop stress app in guest", logging.info)
        utils_misc.wait_for(_unload_stress, first=2.0,
                text="wait stress app quit", step=1.0, timeout=120)

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

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = DriveMirrorStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        stress_test.start()
        stress_test.action_before_steady()
        stress_test.action_when_steady()
        stress_test.action_after_reopen()
    finally:
        stress_test.clean()
