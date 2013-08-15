import os, re, logging
from autotest.client.shared import error, utils
from virttest import utils_misc, storage, data_dir


def speed2byte(speed):
    """
    convert speed to Bytes/s
    """
    if str(speed).isdigit():
        speed = "%sB" % speed
    speed = utils_misc.normalize_data_size(speed, "B")
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
        self.data_dir = data_dir.get_data_dir()
        self.device = self.get_device()
        self.image_file = self.get_image_file()


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
        root_dir = self.data_dir
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
        def is_cancelled():
            ret = not bool(self.get_status())
            if self.vm.monitor.protocol == "qmp":
                ret &= bool(self.vm.monitor.get_event("BLOCK_JOB_CANCELLED"))
            return ret

        error.context("cancel block copy job", logging.info)
        params = self.parser_test_args()
        timeout = params.get("cancel_timeout")
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_CANCELLED")
        self.vm.cancel_block_job(self.device)
        cancelled = utils_misc.wait_for(is_cancelled, timeout=timeout)
        if not cancelled:
            msg = "Cancel block job timeout in %ss" % timeout
            raise error.TestFail(msg)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_CANCELLED")


    @error.context_aware
    def set_speed(self):
        """
        set limited speed for block job;
        """
        params = self.parser_test_args()
        max_speed = params.get("max_speed")
        error.context("set max speed to %s B/s" % max_speed, logging.info)
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


    @error.context_aware
    def reboot(self, method="shell", boot_check=True):
        """
        reboot VM, alias of vm.reboot();
        """
        error.context("reboot vm", logging.info)
        params = self.parser_test_args()
        timeout = params["login_timeout"]

        if boot_check:
            session = self.get_session()
            return self.vm.reboot(session=session,
                                  timeout=timeout, method=method)
        if self.vm.monitor.protocol == "qmp":
            error.context("reset guest via system_reset", logging.info)
            self.vm.monitor.clear_event("RESET")
            self.vm.monitor.cmd("system_reset")
            reseted = utils_misc.wait_for(lambda:
                                          self.vm.monitor.get_event("RESET"),
                                          timeout=timeout)
            if not reseted:
                raise error.TestFail("No RESET event recived after"
                                     "execute system_reset %ss" % timeout)
            self.vm.monitor.clear_event("RESET")
        else:
            self.vm.monitor.cmd("system_reset")
        return None


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


    def get_image_file(self):
        """
        return file associated with $device device
        """
        blocks = self.vm.monitor.info("block")
        image_file = None
        if isinstance(blocks, str):
            image_file = re.findall('%s.*\s+file=(\S*)' % self.device, blocks)
            if image_file:
                return image_file[0]
        else:
            for block in blocks:
                if block['device'] == self.device:
                    try:
                        image_file = block['inserted']['file']
                    except KeyError:
                        continue
        return image_file


    def get_backingfile(self, method="monitor"):
        """
        return backingfile of the device, if not return None;
        """
        backing_file = None
        if method == "monitor":
            backing_file = self.vm.monitor.get_backingfile(self.device)
        else:
            cmd = utils_misc.get_qemu_img_binary(self.params)
            image_file = self.get_image_file()
            cmd += " info %s " % image_file
            info = utils.system_output(cmd)
            matched = re.search(r"backing file: +(.*)", info, re.M)
            if matched:
                backing_file = matched.group(1)
        if backing_file:
            backing_file = os.path.abspath(backing_file)
        return backing_file


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
