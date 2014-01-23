import logging
from autotest.client.shared import error
from virttest import storage, data_dir

from qemu.tests.qemu_guest_agent import QemuGuestAgentBasicCheck


class QemuGuestAgentSnapshotTest(QemuGuestAgentBasicCheck):

    @error.context_aware
    def _action_before_fsfreeze(self, *args):
        error.context("Create a file in guest.")
        session = self._get_session(self.params, None)
        cmd = self.params["gagent_fs_test_cmd"]
        self._session_cmd_close(session, cmd)

    @error.context_aware
    def _action_after_fsfreeze(self, *args):
        error.context("Run live snapshot for guest.", logging.info)

        image1 = self.params.get("image", "image1")
        image_params = self.params.object_params(image1)
        sn_params = image_params.copy()
        sn_params["image_name"] += "-snapshot"
        sn_file = storage.get_image_filename(sn_params,
                                             data_dir.get_data_dir())
        base_file = storage.get_image_filename(image_params,
                                               data_dir.get_data_dir())
        snapshot_format = image_params["image_format"]

        self.vm.live_snapshot(base_file, sn_file, snapshot_format)

    @error.context_aware
    def _action_before_fsthaw(self, *args):
        pass

    @error.context_aware
    def _action_after_fsthaw(self, *args):
        error.context("Check if the file created exists in the guest.")
        session = self._get_session(self.params, None)
        cmd = self.params["gagent_fs_check_cmd"]
        s, _ = self._session_cmd_close(session, cmd)
        if bool(s):
            raise error.TestFail("The file created in guest is gone")

        error.context("Reboot and shutdown guest.")
        self.vm.reboot()
        self.vm.destroy()


def run(test, params, env):
    """
    Freeze guest + create live snapshot + thaw guest

    Test steps:
    1) Create a big file inside guest.
    2) Send commands in the host side to freeze guest.
    3) Create live snapshot.
    4) Thaw guest.
    5) Check if the created exists in the guest.
    6) Reboot and shutdown guest.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    gagent_test = QemuGuestAgentSnapshotTest(test, params, env)
    gagent_test.execute(test, params, env)
