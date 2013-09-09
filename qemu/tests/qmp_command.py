import logging
import re
from autotest.client.shared import utils, error
from virttest import utils_misc, qemu_monitor


@error.context_aware
def run_qmp_command(test, params, env):
    """
    Test qmp event notification, this case will:
    1) Start VM with qmp enable.
    2) Connect to qmp port then run qmp_capabilities command.
    3) Initiate the qmp command defined in config (qmp_cmd)
    4) Verify that qmp command works as designed.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """
    def check_result(qmp_o, output=None):
        """
        Check test result with difference way accoriding to
        result_check.
        result_check = equal, will compare cmd_return_value with qmp
                       command output.
        result_check = contain, will try to find cmd_return_value in qmp
                       command output.
        result_check = m_equal_q, will compare key value in monitor command
                       output and qmp command output.
        result_check = m_in_q, will try to find monitor command output's key
                       value in qmp command output.
        result_check = m_format_q, will try to match the output's format with
                       check pattern.

        @param qmp_o: output from pre_cmd, qmp_cmd or post_cmd.
        @param o: output from pre_cmd, qmp_cmd or post_cmd or an execpt
        result set in config file.
        """
        if result_check == "equal":
            value = output
            if value != str(qmp_o):
                raise error.TestFail("QMP command return value does not match "
                                     "the expect result. Expect result: '%s'\n"
                                     "Actual result: '%s'" % (value, qmp_o))
        elif result_check == "contain":
            values = output.split(';')
            for value in values:
                if value.strip() not in str(qmp_o):
                    raise error.TestFail("QMP command output does not contain "
                                         "expect result. Expect result: '%s'\n"
                                         "Actual result: '%s'"
                                         % (value, qmp_o))
        elif result_check == "not_contain":
            values = output.split(';')
            for value in values:
                if value in str(qmp_o):
                    raise error.TestFail("QMP command output contains unexpect"
                                         " result. Unexpect result: '%s'\n"
                                         "Actual result: '%s'"
                                         % (value, qmp_o))
        elif result_check == "m_equal_q":
            msg = "QMP command ouput is not equal to in human monitor command."
            msg += "\nQMP command output: '%s'" % qmp_o
            msg += "\nHuman command output: '%s'" % output
            res = output.splitlines(True)
            if type(qmp_o) != type(res):
                len_o = 1
            else:
                len_o = len(qmp_o)
            if len(res) != len_o:
                raise error.TestFail(msg)
            re_str = r'([^ \t\n\r\f\v=]*)=([^ \t\n\r\f\v=]*)'
            for i in range(len(res)):
                if qmp_cmd == "query-version":
                    version = qmp_o['qemu']
                    version = "%s.%s.%s" % (version['major'], version['minor'],
                                            version['micro'])
                    package = qmp_o['package']
                    re_str = r"([0-9]+\.[0-9]+\.[0-9]+)\s*(\(\S*\))?"
                    hmp_version, hmp_package = re.findall(re_str, res[i])[0]
                    if not hmp_package:
                        hmp_package = package
                    if version != hmp_version or package != hmp_package:
                        raise error.TestFail(msg)
                else:
                    matches = re.findall(re_str, res[i])
                    for key, val in matches:
                        if '0x' in val:
                            val = long(val, 16)
                            if val != qmp_o[i][key]:
                                msg += "\nValue in human monitor: '%s'" % val
                                msg += "\nValue in qmp: '%s'" % qmp_o[i][key]
                                raise error.TestFail(msg)
                        elif qmp_cmd == "query-block":
                            cmp_str = "u'%s': u'%s'" % (key, val)
                            cmp_s = "u'%s': %s" % (key, val)
                            if '0' == val:
                                cmp_str_b = "u'%s': False" % key
                            elif '1' == val:
                                cmp_str_b = "u'%s': True" % key
                            else:
                                cmp_str_b = cmp_str
                            if (cmp_str not in str(qmp_o[i]) and
                               cmp_str_b not in str(qmp_o[i]) and
                               cmp_s not in str(qmp_o[i])):
                                msg += ("\nCan not find '%s', '%s' or '%s' in "
                                        " QMP command output."
                                        % (cmp_s, cmp_str_b, cmp_str))
                                raise error.TestFail(msg)
                        elif qmp_cmd == "query-balloon":
                            if (int(val) * 1024 * 1024 != qmp_o[key] and
                               val not in str(qmp_o[key])):
                                msg += ("\n'%s' is not in QMP command output"
                                        % val)
                                raise error.TestFail(msg)
                        else:
                            if (val not in str(qmp_o[i][key]) and
                               str(bool(int(val))) not in str(qmp_o[i][key])):
                                msg += ("\n'%s' is not in QMP command output"
                                        % val)
                                raise error.TestFail(msg)
        elif result_check == "m_in_q":
            res = output.splitlines(True)
            msg = "Key value from human monitor command is not in"
            msg += "QMP command output.\nQMP command output: '%s'" % qmp_o
            msg += "\nHuman monitor command output '%s'" % output
            for i in range(len(res)):
                params = res[i].rstrip().split()
                for param in params:
                    try:
                        str_o = str(qmp_o.values())
                    except AttributeError:
                        str_o = qmp_o
                    if param.rstrip() not in str(str_o):
                        msg += "\nKey value is '%s'" % param.rstrip()
                        raise error.TestFail(msg)
        elif result_check == "m_format_q":
            match_flag = True
            for i in qmp_o:
                if output is None:
                    raise error.TestError("QMP output pattern is missing")
                if re.match(output.strip(), str(i)) is None:
                    match_flag = False
            if not match_flag:
                msg = "Output does not match the pattern: '%s'" % output
                raise error.TestFail(msg)

    def qmp_cpu_check(output):
        """ qmp_cpu test check """
        last_cpu = int(params['smp']) - 1
        for out in output:
            cpu = out.get('CPU')
            if cpu is None:
                raise error.TestFail("'CPU' index is missing in QMP output "
                                     "'%s'" % out)
            else:
                current = out.get('current')
                if current is None:
                    raise error.TestFail("'current' key is missing in QMP "
                                         "output '%s'" % out)
                elif cpu < last_cpu:
                    if current is False:
                        pass
                    else:
                        raise error.TestFail("Attribute 'current' should be "
                                             "'False', but is '%s' instead.\n"
                                             "'%s'" % (current, out))
                elif cpu == last_cpu:
                    if current is True:
                        pass
                    else:
                        raise error.TestFail("Attribute 'current' should be "
                                             "'True', but is '%s' instead.\n"
                                             "'%s'" % (current, out))
                elif cpu <= last_cpu:
                    continue
                else:
                    raise error.TestFail("Incorrect CPU index '%s' (corrupted "
                                         "or higher than no_cpus).\n%s"
                                         % (cpu, out))

    if not utils_misc.qemu_has_option("qmp", params['qemu_binary']):
        raise error.TestNAError("Host qemu does not support qmp.")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    module = params.get("modprobe_module")
    if module:
        error.context("modprobe the module %s" % module, logging.info)
        session.cmd("modprobe %s" % module)

    qmp_ports = vm.get_monitors_by_type('qmp')
    if qmp_ports:
        qmp_port = qmp_ports[0]
    else:
        raise error.TestError("Incorrect configuration, no QMP monitor found.")
    hmp_ports = vm.get_monitors_by_type('human')
    if hmp_ports:
        hmp_port = hmp_ports[0]
    else:
        raise error.TestError("Incorrect configuration, no QMP monitor found.")
    callback = {"host_cmd": utils.system_output,
                "guest_cmd": session.get_command_output,
                "monitor_cmd": hmp_port.send_args_cmd,
                "qmp_cmd": qmp_port.send_args_cmd}

    def send_cmd(cmd):
        """ Helper to execute command on ssh/host/monitor """
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            raise error.TestError("cmd_type is not supported")

    pre_cmd = params.get("pre_cmd")
    qmp_cmd = params.get("qmp_cmd")
    cmd_type = params.get("event_cmd_type")
    post_cmd = params.get("post_cmd")
    result_check = params.get("cmd_result_check")
    cmd_return_value = params.get("cmd_return_value")

    # HOOKs
    if result_check == 'qmp_cpu':
        pre_cmd = "cpu index=%d" % (int(params['smp']) - 1)

    # Pre command
    if pre_cmd is not None:
        error.context("Run prepare command '%s'." % pre_cmd, logging.info)
        pre_o = send_cmd(pre_cmd)
        logging.debug("Pre-command: '%s'\n Output: '%s'", pre_cmd, pre_o)
    try:
        # Testing command
        error.context("Run qmp command '%s'." % qmp_cmd, logging.info)
        output = qmp_port.send_args_cmd(qmp_cmd)
        logging.debug("QMP command: '%s' \n Output: '%s'", qmp_cmd, output)
    except qemu_monitor.QMPCmdError, err:
        if params.get("negative_test") == 'yes':
            logging.debug("Negative QMP command: '%s'\n output:'%s'", qmp_cmd,
                          err)
            if params.get("negative_check_pattern"):
                check_pattern = params.get("negative_check_pattern")
                if check_pattern not in str(err):
                    raise error.TestFail("'%s' not in exception '%s'"
                                         % (check_pattern, err))
        else:
            raise error.TestFail(err)
    except qemu_monitor.MonitorProtocolError, err:
        raise error.TestFail(err)
    except Exception, err:
        raise error.TestFail(err)

    # Post command
    if post_cmd is not None:
        error.context("Run post command '%s'." % post_cmd, logging.info)
        post_o = send_cmd(post_cmd)
        logging.debug("Post-command: '%s'\n Output: '%s'", post_cmd, post_o)

    if result_check is not None:
        txt = "Verify that qmp command '%s' works as designed." % qmp_cmd
        error.context(txt, logging.info)
        if result_check == 'qmp_cpu':
            qmp_cpu_check(output)
        elif result_check == "equal" or result_check == "contain":
            check_result(output, cmd_return_value)
        elif result_check == "m_format_q":
            check_result(output, cmd_return_value)
        elif 'post' in result_check:
            result_check = result_check.split('_', 1)[1]
            check_result(post_o, cmd_return_value)
        else:
            check_result(output, post_o)
    session.close()
