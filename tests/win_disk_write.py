import logging
from autotest.client.shared import error


@error.context_aware
def run_win_disk_write(test, params, env):
    """
    KVM virtio viostor heavy random write load:
    1) Log into a guest
    2) Instaill Crystal Disk Mark
    3) Start Crystal Disk Mark with heavy write load

    @param test: kvm test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environment.
    """
    error.context("Try to log into guest.", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    crystal_install_cmd = params.get("crystal_install_cmd")
    crystal_run_cmd = params.get("crystal_run_cmd")
    test_timeout = float(params.get("test_timeout", "7200"))

    error.context("Install Crystal Disk Mark", logging.info)
    if crystal_install_cmd:
        session.cmd(crystal_install_cmd, timeout=test_timeout)
    else:
        raise error.TestError("Can not get the crystal disk mark"
                              " install command.")

    error.context("Start the write load", logging.info)
    if crystal_run_cmd:
        session.cmd(crystal_run_cmd, timeout=test_timeout)
    else:
        raise error.TestError("Can not get the load start command.")

    session.close()
