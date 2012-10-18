import logging
from autotest.client.shared import error
from virttest import guest_agent


class BaseVirtTest(object):
    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env


    def initialize(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def setup(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def run_once(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env


    def before_run_once(self, test, params, env):
        pass


    def after_run_once(self, test, params, env):
        pass

    def cleanup(self, test, params, env):
        pass


    def execute(self, test, params, env):
        self.initialize(test, params, env)
        self.setup(test, params, env)
        try:
            self.before_run_once(test, params, env)
            self.run_once(test, params, env)
            self.after_run_once(test, params, env)
        finally:
            self.cleanup(test, params, env)


class QemuGuestAgentTest(BaseVirtTest):

    def __init__(self, test, params, env):
        BaseVirtTest.__init__(self, test, params, env)

        self._open_session_list = []
        self.gagent = None
        self.vm = None


    def _get_session(self, params, vm):
        if not vm:
            vm = self.vm
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        return session


    def _session_cmd_close(self, session, cmd):
        try:
            return session.cmd_status_output(cmd)
        finally:
            try:
                session.close()
            except Exception:
                pass


    def _cleanup_open_session(self):
        try:
            for s in self._open_session_list:
                if s:
                    s.close()
        except Exception:
            pass


    @error.context_aware
    def gagent_install(self, params, vm, *args):
        if args and isinstance(args, tuple):
            gagent_install_cmd = args[0]
        else:
            raise error.TestError("Missing config 'gagent_install_cmd'")

        if not gagent_install_cmd:
            return

        error.context("Try to install 'qemu-guest-agent' package.",
                      logging.info)
        session = self._get_session(params, vm)
        s, _ = self._session_cmd_close(session, gagent_install_cmd)
        if bool(s):
            raise error.TestError("Could not install qemu-guest-agent package")


    @error.context_aware
    def gagent_start(self, params, vm, *args):
        if args and isinstance(args, tuple):
            gagent_start_cmd = args[0]
        else:
            raise error.TestError("Missing config 'gagent_start_cmd'")

        if not gagent_start_cmd:
            return

        error.context("Try to start 'qemu-guest-agent'.", logging.info)
        session = self._get_session(params, vm)
        s, _ = self._session_cmd_close(session, gagent_start_cmd)
        if bool(s):
            raise error.TestError("Could not start qemu-guest-agent in VM '%s'",
                                  vm.name)


    @error.context_aware
    def gagent_create(self, params, vm, *args):
        if self.gagent:
            return self.gagent

        error.context("Create a QemuAgent object.", logging.info)
        if not (args and isinstance(args, tuple) and len(args) == 2):
            raise error.TestError("Got invalid arguments for guest agent")

        gagent_serial_type = args[0]
        gagent_name = args[1]
        gagent = guest_agent.QemuAgent(vm, gagent_name, gagent_serial_type,
                                       get_supported_cmds=True)
        self.gagent = gagent

        return self.gagent


    @error.context_aware
    def setup_gagent_in_guest(self, params, vm):
        error.context("Setup guest agent in VM '%s'" % vm.name)
        self.gagent_install(params, vm, *[params.get("gagent_install_cmd")])
        self.gagent_start(params, vm, *[params.get("gagent_start_cmd")])
        args = [params.get("gagent_serial_type"), params.get("gagent_name")] 
        self.gagent_create(params, vm, *args)


    @error.context_aware
    def gagent_verify(self, params, vm):
        error.context("Check if guest agent work.", logging.info)

        if not self.gagent:
            raise error.TestError("Could not find guest agent object"
                                  "for VM '%s'" % vm.name)

        self.gagent.verify_responsive()
        logging.info(self.gagent.cmd("guest-info"))


    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)

        if not self.vm:
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm
        self.setup_gagent_in_guest(params, self.vm)


    def run_once(self, test, params, env):
        BaseVirtTest.run_once(self, test, params, env)

        if not self.vm:
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm

        self.gagent_verify(self.params, self.vm)


    def cleanup(self, test, params, env):
        self._cleanup_open_session()


def run_qemu_guest_agent(test, params, env):
    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Create QemuAgent object and test if virt agent works.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """
    gagent_test = QemuGuestAgentTest(test, params, env)
    gagent_test.execute(test, params, env)
