import time
import logging
from autotest.client.shared import error
from autotest.client import utils
from virttest import utils_misc
from qemu.tests import blk_stream


class BlockStreamStress(blk_stream.BlockStream):

    def __init__(self, test, params, env, tag):
        super(BlockStreamStress, self).__init__(test, params, env, tag)

    def parser_test_args(self):
        """
        set default values and check core commands has configured;
        """
        params = super(BlockStreamStress, self).parser_test_args()
        for param in ["start_cmd", "stop_cmd", "check_cmd"]:
            if not params.get(param):
                raise error.TestFail("%s not configured,please check your"
                                     "configuration at first")
        return params

    @error.context_aware
    def install_stress_app(self):
        params = self.parser_test_args()
        session = self.get_session()
        if session.cmd_status(params.get("app_check_cmd", "true")) == 0:
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
            raise error.TestError("Fail to install stress app(%s)" % o)
        logging.info("Configure app: %s" % config_cmd)
        s, o = session.cmd_status_output(config_cmd, timeout=300)
        if s != 0:
            raise error.TestError("Fail to conifg stress app(%s)" % o)

    @error.context_aware
    def load_stress(self):
        """
        load IO/CPU/Memoery stress in guest;
        """
        params = self.parser_test_args()
        self.install_stress_app()
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
                                     step=1.0, timeout=params["wait_timeout"])
        if not stoped:
            raise error.TestFail("stress app is still running")

    def app_runing(self):
        """
        check stress app really run in background;
        """
        session = self.get_session()
        params = self.parser_test_args()
        cmd = params.get("check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        return status == 0


def run(test, params, env):
    """
    block_stream_stress test:
    1). load stress in guest
    2). stream block device and wait to finished
    7). quit stress app
    8). reboot and verify guest can response correctly

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    stress_test = BlockStreamStress(test, params, env, tag)
    try:
        stress_test.create_snapshots()
        stress_test.action_before_start()
        stress_test.start()
        stress_test.action_after_finished()
    finally:
        stress_test.clean()
