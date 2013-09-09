import logging
from autotest.client.shared import error
from virttest import guest_agent
from tests.guest_suspend import GuestSuspendBaseTest
from qemu.tests.qemu_guest_agent import QemuGuestAgentTest


class SuspendViaGA(GuestSuspendBaseTest):

    guest_agent = None
    suspend_mode = ""

    @error.context_aware
    def start_suspend(self, **args):
        """
        Start suspend via qemu guest agent.
        """
        error.context("Suspend guest via guest agent", logging.info)
        if self.guest_agent:
            self.guest_agent.suspend(self.suspend_mode)


class QemuGASuspendTest(QemuGuestAgentTest):

    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Create QemuAgent object.
    4) Run suspend test with guest agent.
    """

    def run_once(self, test, params, env):
        QemuGuestAgentTest.run_once(self, test, params, env)

        error.context("Suspend guest to memory", logging.info)
        gs = SuspendViaGA(params, self.vm)
        gs.guest_agent = self.gagent
        gs.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_RAM
        gs.guest_suspend_mem(params)

        error.context("Suspend guest to disk", logging.info)
        gs.suspend_mode = guest_agent.QemuAgent.SUSPEND_MODE_DISK
        gs.guest_suspend_disk(params)

        # Reset guest agent object to None after guest reboot.
        self.gagent = None
        error.context("Check if guest agent work again.", logging.info)
        self.gagent_start(params, self.vm, *[params.get("gagent_start_cmd")])
        args = [params.get("gagent_serial_type"), params.get("gagent_name")]
        self.gagent_create(params, self.vm, *args)
        self.gagent.verify_responsive()


@error.context_aware
def run_qemu_guest_agent_suspend(test, params, env):
    """
    Test suspend commands in qemu guest agent.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    gagent_test = QemuGASuspendTest(test, params, env)
    gagent_test.execute(test, params, env)
