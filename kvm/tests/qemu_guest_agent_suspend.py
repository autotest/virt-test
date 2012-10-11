import logging
from autotest.client.shared import error
from virttest import guest_agent
from virttest.utils_test import GuestSuspend


class SuspendViaGA(GuestSuspend):

    guest_agent = None
    suspend_mode = ""

    @classmethod
    @error.context_aware
    def start_suspend(cls, params, vm, *args):
        """
        Start suspend via qemu guest agent.
        """
        error.context("Suspend guest via guest agent", logging.info)
        if cls.guest_agent:
            cls.guest_agent.suspend(cls.suspend_mode)


@error.context_aware
def run_qemu_guest_agent_suspend(test, params, env):
    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Create QemuAgent object.
    4) Run suspend test with guest agent.

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    error.context("Try to install 'qemu-guest-agent' package.", logging.info)
    gagent_install_cmd = params.get("gagent_install_cmd")
    gagent_start_cmd = params.get("gagent_start_cmd")
    if gagent_install_cmd and bool(session.cmd_status(gagent_install_cmd)):
        session.close()
        raise error.TestError("Could not install qemu-guest-agent package")

    if gagent_start_cmd and bool(session.cmd_status(gagent_start_cmd)):
        session.close()
        raise error.TestError("Could not start qemu-guest-agent in vm '%s'",
                              vm.name)
    session.close()

    error.context("Create a QemuAgent object and try to connect it to guest.",
                  logging.info)
    serial_type = params.get("serial_type", "virtio")
    gagent_name = params.get("gagent_name", "org.qemu.guest_agent.0")
    gagent = guest_agent.QemuAgent(vm, gagent_name, serial_type,
                                   get_supported_cmds=True)

    error.context("Check if guest agent work.", logging.info)
    gagent.verify_responsive()

    error.context("Suspend guest to memory", logging.info)
    SuspendViaGA.guest_agent = gagent
    SuspendViaGA.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_RAM
    SuspendViaGA.guest_suspend_mem(params, vm)

    error.context("Suspend guest to disk", logging.info)
    SuspendViaGA.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_DISK
    SuspendViaGA.guest_suspend_disk(params, vm)

    error.context("Check if guest agent work again.", logging.info)
    gagent = guest_agent.QemuAgent(vm, gagent_name, serial_type,
                                   get_supported_cmds=True)
    gagent.verify_responsive()
