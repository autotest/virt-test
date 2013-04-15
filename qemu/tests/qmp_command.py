import logging, time, os, commands, re
from autotest.client.shared import error
from virttest import utils_misc, qemu_monitor


def run_qmp_command(test, params, env):
    """
    Test qmp event notification, this case will:
    1) Start VM with qmp enable.
    2) Connect to qmp port then run qmp_capabilities command.
    3) make testing event in guest os.
    4) Verify that qmp through corresponding event notification.

    @param test: QEMU test object
    @param params: Dictionary with the test parameters
    @param env: Dictionary with test environmen.
    """

    if not utils_misc.qemu_has_option("qmp"):
        logging.info("Host qemu does not support qmp. Ignore this case!")
        return
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    callback = {"host_cmd": commands.getoutput,
                "guest_cmd": session.get_command_output,
                "monitor_cmd": vm.monitor.send_args_cmd,
                "qmp_cmd": vm.monitors[1].send_args_cmd}

    def send_cmd(cmd):
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            raise error.TestError("cmd_type is not supported")
            return ("")

    def check_result(qmp_o, o=None):
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
        check pattern

        @param qmp_o: output from pre_cmd, qmp_cmd or post_cmd.
        @param o: output from pre_cmd, qmp_cmd or post_cmd or an execpt
        result set in config file.
        """
        logging.debug("result_check : %s" % result_check)
        if result_check == "equal":
            value = o
            if value != str(qmp_o):
                raise error.TestFail("QMP command return value is not match"
                                     " with expect result. Expect result is %s"
                                     "\n Actual result is %s\n"
                                     % (value, qmp_o))
        elif result_check == "contain":
            values = o.split(';')
            for value in values:
                if value not in str(qmp_o):
                    raise error.TestFail("QMP command output does not contain"
                                         " expect result. Expect result is %s"
                                         "\n Actual result is %s\n"
                                          % (value, qmp_o))
        elif result_check == "not_contain":
            values = o.split(';')
            for value in values:
                if value in str(qmp_o):
                    raise error.TestFail("QMP command output contains unexpect"
                                         " result. Unexpect result is %s"
                                         "\n Actual result is %s\n"
                                          % (value, qmp_o))
        elif result_check == "m_equal_q":
            msg = "QMP command ouput is not equal to in human monitor command."
            msg += "QMP command output: %s\n" % qmp_o
            msg += "Human command output: %s\n" % o
            res = o.splitlines(True)
            if type(qmp_o) != type(res):
                len_o = 1
            else:
                len_o = len(qmp_o)
            if len(res) != len_o:
                raise error.TestFail(msg)
            re_str = r'([^ \t\n\r\f\v=]*)=([^ \t\n\r\f\v=]*)'
            if len_o > 0:
                for i in range(len(res)):
                    matches = re.findall(re_str, res[i])
                    for key, value in matches:
                        if '0x' in value:
                            value = long(value, 16)
                            if value != qmp_o[i][key]:
                                msg += "Value in human monitor: %s.  " % value
                                msg += "Value in qmp monitor:%s" % qmp_o[i][key]
                                raise error.TestFail(msg)
                        elif qmp_cmd == "query-block":
                            cmp_str = "u'%s': u'%s'" % (key, value)
                            if '0' == value:
                                cmp_str_b = "u'%s': False" % key
                            elif '1' == value:
                                cmp_str_b = "u'%s': True" % key
                            else:
                                cmp_str_b = cmp_str
                            if cmp_str not in str(qmp_o[i]) and\
                               cmp_str_b not in str(qmp_o[i]):
                                msg += "%s or %s is not in QMP command output" \
                                       % (cmp_str, cmp_str_b)
                                raise error.TestFail(msg)
                        elif qmp_cmd == "query-balloon":
                            if int(value) * 1024 * 1024 != qmp_o[key] and\
                            value not in str(qmp_o[key]):
                                msg += "%s is not in QMP command output" % value
                                raise error.TestFail(msg)

                        else:
                            if value not in str(qmp_o[i][key]) and\
                               str(bool(int(value))) not in str(qmp_o[i][key]):
                                msg += "% is not in QMP command output" % value
                                raise error.TestFail(msg)
            return True
        elif result_check == "m_in_q":
            res = o.splitlines(True)
            msg = "Key value from human monitor command is not in"
            msg += "QMP command output. QMP command output: %s\n" % qmp_o
            msg += "Human monitor command output %s\n" % o
            for i in  range(len(res)):
                params = res[0].rstrip().split()
                for param in params:
                    # use "".join to ignore space in qmp_o
                    try:
                        str_o = "".join(str(qmp_o.values()))
                    except AttributeError:
                        str_o = qmp_o
                    if param.rstrip() not in str(str_o):
                        msg += "Key value is %s" % param.rstrip()
                        raise error.TestFail(msg)
            return True
        elif result_check == "m_format_q":
            match_flag = True
            for i in qmp_o:
                if o is None:
                    raise error.TestError("QMP output pattern is missing")
                if re.match(o.strip(), str(i)) is None:
                    match_flag = False
            if not match_flag:
                raise error.TestFail("Output is not match the pattern: %s" % o)
            return True


    pre_cmd = params.get("pre_cmd")
    qmp_cmd = params.get("qmp_cmd")
    qmp_protocol = params.get("qmp")
    cmd_type = params.get("event_cmd_type")
    post_cmd = params.get("post_cmd")
    result_check = params.get("cmd_result_check")
    cmd_return_value = params.get("cmd_return_value")
    cmd_return_parttern = params.get("cmd_return_parttern")

    timeout = int(params.get("check_timeout", 360))
    if pre_cmd is not None:
        pre_o = send_cmd(pre_cmd)
        logging.debug("Pre-command is:%s\n Output is: %s\n" % (pre_cmd, pre_o))
    try:
        #vm.monitors[1] is first qmp monitor. vm.monitors[0] is human monitor
        o = vm.monitors[1].send_args_cmd(qmp_cmd)
        logging.debug("QMP command is:%s \n Output is:%s\n" % (qmp_cmd, o))
    except qemu_monitor.QMPCmdError, e:
        if params.get("negative_test") == 'yes':
            logging.debug("Negative QMP command: %s\n output:%s\n"
                           % (qmp_cmd, e))
            if params.get("negative_check_point"):
                check_point = params.get("negative_check_point")
                if check_point not in str(e):
                    raise error.TestFail("%s not in exception %s"
                                                       % (check_point, e))
        else:
            raise error.TestFail(e)
    except qemu_monitor.MonitorProtocolError, e:
        raise error.TestFail(e)
    except Exception, e:
        raise error.TestFail(e)

    if post_cmd is not None:
        post_o = send_cmd(post_cmd)
        logging.debug("Post-command:%s\n Output is:%s\n" % (post_cmd, post_o))

    if result_check is not None:
        if result_check == "equal" or result_check == "contain":
            check_result(o, cmd_return_value)
        elif result_check == "m_format_q":
            check_result(o, cmd_return_parttern)
        elif 'post' in result_check:
            result_check = '_'.join(result_check.split('_')[1:])
            check_result(post_o, cmd_return_value)
        else:
            check_result(o, post_o)
        logging.info("QMP command successfully")
    session.close()
