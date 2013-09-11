import logging
import os
import re
from virttest import utils_misc, env_process
from autotest.client.shared import error


@error.context_aware
def run_sysprep(test, params, env):
    """
    KVM sysprep test:
    1) Log into a guest
    2) Clean guest with sysprep tools.
    3) Boot guest up again.
    4) Check that SID in guest has changed.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    unattended_file = params.get("unattended_file")
    unattended_file_link = os.path.join(test.virtdir,
                                        unattended_file)
    tmp_path = params.get("tmp_path", "c:\\")
    vm.copy_files_to(unattended_file_link, tmp_path, verbose=True)
    sysprep_cmd = params.get("sysprep_cmd")
    check_sid_cmd = params.get("check_sid_cmd", "whoami /user")
    extend_vm = params.get("extend_vm")
    re_sid = params.get("re-sid", "(S[0-9-]{20,})")

    vms = []
    sids = {}
    sid_same = []
    error.context("Check guest's System ID.", logging.info)
    output = session.cmd_output(check_sid_cmd, timeout=60)
    try:
        sid = re.findall(re_sid, output)[0]
    except IndexError:
        msg = "Fail to get guest's System ID. "
        msg += "Output from check System ID command: %s" % output
        raise error.TestFail(msg)
    logging.info("VM guest System ID is: %s", sid)
    sids[sid] = ["pre_%s" % vm.name]
    file_dir = tmp_path + unattended_file
    sysprep_cmd = sysprep_cmd % file_dir
    error.context("Run sysprep command in guest. %s" % sysprep_cmd,
                  logging.info)
    session.sendline(sysprep_cmd)
    error.context("Waiting guest power down.....", logging.info)
    status = utils_misc.wait_for(vm.is_dead, timeout * 3, 3)
    if not status:
        raise error.TestFail("VM did not shutdown after sysprep command")
    params['image_snapshot'] = "yes"
    params['vms'] += extend_vm
    restart_timeout = timeout * len(params['vms'].split()) * 2
    for vm_i in params['vms'].split():
        vm_params = params.object_params(vm_i)
        env_process.preprocess_vm(test, vm_params, env, vm_i)
        vm = env.get_vm(vm_i)
        vm.verify_alive()
        vms.append(vm)
    for vm_i in vms:
        session = vm_i.wait_for_login(timeout=restart_timeout)
        vm_i_ip = vm_i.get_address()
        logging.info("VM: %s got IP: %s", vm_i.name, vm_i_ip)
        error.context("Check guest's System ID.", logging.info)
        output = session.cmd_output(check_sid_cmd, timeout=60)
        try:
            sid = re.findall(re_sid, output)[0]
        except IndexError:
            msg = "Fail to get System ID of %s" % vm_i.name
            msg += "Output from check System ID command: %s" % output
            raise error.TestError(msg)
        logging.info("VM:%s System ID is: %s", vm_i.name, sid)
        if sid in sids.keys():
            logging.error("VM: %s have duplicate System ID: %s",
                          vm_i.name,
                          sid)
            sid_same.append(sid)
            sids[sid].append(vm_i.name)
        else:
            sids[sid] = [vm_i.name]

    if sid_same:
        msg = ""
        for sid in sid_same:
            msg += "VM(s): %s have duplicate System ID: %s\n" % \
                (" ".join(sids[sid]), sid)
        raise error.TestFail(msg)
