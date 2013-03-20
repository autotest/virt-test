import logging
from autotest.client.shared import error, utils
from autotest.client.virt import utils_misc, storage

def speed2byte(speed):
    """
    convert speed to Bytes/s
    """
    if str(speed).isdigit():
       speed = "%sB" % speed
    speed = utils_misc.standard_value(speed, "B")
    return int(float(speed))

class BlockCopy(object):
    """
    Base class for block copy test;
    """
    sessions = []
    trash = []

    def __init__(self, test, params, env, tag):
        self.test = test
        self.env = env
        self.params = params
        self.tag = tag
        self.vm = self.get_vm()
        self.device = self.get_device()

    def parser_test_args(self):
        """
        parser test args, unify speed unit to B/s and set default values;
        """
        params = self.params.object_params(self.tag)
        params["cancel_timeout"] = int(params.get("cancel_timeout", 1))
        params["wait_timeout"] = int(params.get("wait_timeout", 600))
        params["fsck_timeout"] = int(params.get("fsck_timeout", 300))
        params["login_timeout"] = int(params.get("login_timeout", 360))
        params["check_timeout"] = int(params.get("check_timeout", 0))
        params["max_speed"] = speed2byte(params.get("max_speed", 0))
        params["default_speed"] = speed2byte(params.get("default_speed", 0))
        return params

    def get_vm(self):
        """
        return live vm object;
        """
        vm = self.env.get_vm(self.params["main_vm"])
        vm.verify_alive()
        return vm

    def get_device(self):
        """
        according configuration get target device ID;
        """
        root_dir = self.test.bindir
        params = self.parser_test_args()
        image_file = storage.get_image_filename(params, root_dir)
        device = self.vm.get_block({"file": image_file})
        return device

    def get_session(self):
        """
        get a session object;
        """
        params = self.parser_test_args()
        timeout = params.get("login_timeout")
        session = self.vm.wait_for_login(timeout=timeout)
        self.sessions.append(session)
        return session

    def get_status(self):
        """
        return block job info dict;
        """
        return self.vm.get_job_status(self.device)

    def do_steps(self, tag=None):
        if not tag:
            return
        params = self.parser_test_args()
        for step in params.get(tag, "").split():
            if step and hasattr(self, step):
                fun = getattr(self, step)
                fun()
            else:
                error.TestError("undefined step %s" % step)

    @error.context_aware
    def cancel(self):
        """
        cancel active job on given image;
        """
        params = self.parser_test_args()
        timeout = params.get("cancel_timeout")

        def is_cancelled():
            if self.vm.monitor.protocol == "qmp":
                return self.vm.monitor.get_event("BLOCK_JOB_CANCELLED")
            return not self.get_status(self.device)

        error.context("cancel block copy job", logging.info)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_events()
        self.vm.cancel_block_job(self.device)
        cancelled = utils_misc.wait_for(is_cancelled, timeout=timeout,
                    text="wait job cancelled in %ss" % timeout)
        if not cancelled:
            raise error.TestFail("Job still running after %ss" % timeout)

    @error.context_aware
    def set_speed(self):
        """
        set limited speed for block job;
        """
        params = self.parser_test_args()
        max_speed = params.get("max_speed")

        error.context("set max speed to %s" % max_speed, logging.info)
        self.vm.set_job_speed(self.device, max_speed)
        status = self.get_status()
        speed = status["speed"]
        if speed != max_speed:
            msg = "Set speed fail. (expect speed: %s B/s," % max_speed
            msg += "actual speed: %s B/s)" % speed
            raise error.TestFail(msg)

    @error.context_aware
    def fsck(self):
        """
        check filesystem status in guest;
        """
        error.context("check guest filesystem", logging.info)
        params = self.parser_test_args()
        session = self.get_session()
        cmd = params.get("fsck_cmd")
        timeout = params.get("fsck_timeout")
        status, output = session.cmd_status_output(cmd, timeout=timeout)
        if status != 0:
            msg = "guest filesystem is dirty, filesystem info: %s" % output
            raise error.TestFail(msg)

    def reboot(self, method="shell"):
        """
        reboot VM, alias of vm.reboot();
        """
        session = self.get_session()
        params = self.parser_test_args()
        timeout = params["login_timeout"]
        return self.vm.reboot(session=session, timeout=timeout, method=method)

    @error.context_aware
    def stop(self):
        """
        stop vm and verify it is really paused;
        """
        error.context("stop vm", logging.info)
        self.vm.pause()
        return self.vm.verify_status("paused")

    @error.context_aware
    def resume(self):
        """
        resume vm and verify it is really running;
        """
        error.context("resume vm", logging.info)
        self.vm.resume()
        return self.vm.verify_status("running")

    @error.context_aware
    def verify_alive(self):
        """
        check guest can response command correctly;
        """
        error.context("verify guest alive", logging.info)
        params = self.parser_test_args()
        session = self.get_session()
        cmd = params.get("alive_check_cmd", "dir")
        return session.cmd(cmd, timeout=120)

    def clean(self):
        """
        close opening connections and clean trash files;
        """
        while self.sessions:
            session = self.sessions.pop()
            if session:
                session.close()
        if self.vm.is_alive():
            self.vm.destroy()
        for _tmp in self.trash:
            utils.system("rm -f %s" % _tmp)
