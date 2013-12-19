import logging
import re
from autotest.client.shared import utils, error
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    Check smbios table :
    1) Run the qemu command as nobody
    2) check the process is same as the user's

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def get_user_ugid(username):
        """
        return user uid and gid as a list
        """
        user_uid = utils.system_output("id -u %s" % username).split()
        user_gid = utils.system_output("id -g %s" % username).split()
        return(user_uid, user_gid)

    def get_ugid_from_processid(pid):
        """
        return a list[uid,euid,suid,fsuid,gid,egid,sgid,fsgid] of pid
        """
        grep_ugid_cmd = "cat /proc/%s/status | grep -iE '^(U|G)id'"
        o = utils.system_output(grep_ugid_cmd % pid.strip())
        ugid = re.findall("(\d+)", o)
        # real UID, effective UID, saved set UID, and file system UID
        if ugid:
            return ugid
        else:
            raise error.TestError("Could not find the correct UID for process %s"
                                  % pid)

    exec_username = params.get("user_runas", "nobody")

    error.base_context("Run QEMU %s test:" % exec_username)
    error.context("Get the user uid and gid,using 'id -u/g username'")
    (exec_uid, exec_gid) = get_user_ugid(exec_username)

    error.context("Run the qemu as user '%s'" % exec_username)
    logging.info("The user %s :uid='%s', gid='%s'" %
                (exec_username, exec_uid, exec_gid))

    params["extra_params"] = " -runas %s" % exec_username
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])

    failures = []
    for pid in utils.get_children_pids(vm.get_shell_pid()):
        error.context("Get the process '%s' u/gid, using 'cat /proc/%s/status'"
                      % (pid, pid), logging.info)
        qemu_ugid = get_ugid_from_processid(pid)
        logging.info("Process run as uid=%s,euid=%s,suid=%s,fsuid=%s"
                     % tuple(qemu_ugid[0:4]))
        logging.info("Process run as gid=%s,egid=%s,sgid=%s,fsgid=%s"
                     % tuple(qemu_ugid[4:]))

        error.context("Check if the user %s ugid is equal to the process %s"
                      % (exec_username, pid))
        # generate user uid, euid, suid, fsuid, gid, egid, sgid, fsgid
        user_ugid_extend = exec_uid * 4 + exec_gid * 4
        if cmp(user_ugid_extend, qemu_ugid) != 0:
            e_msg = ("Process %s error, expect ugid is %s, real is %s"
                     % (pid, user_ugid_extend, qemu_ugid))
            failures.append(e_msg)

    if failures:
        raise error.TestFail("FAIL: Test reported %s failures:\n%s" %
                            (len(failures), "\n".join(failures)))
