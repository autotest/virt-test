"""
rv_input.py - test keyboard inputs through spice

Requires: Two VMs - client and guest and remote-viewer session
          from client VM to guest VM created by rv_connect test.
          Deployed PyGTK on guest VM.

          Presumes the numlock state at startup is 'OFF'.
"""

import logging
import os
from autotest.client.shared import error
from virttest.aexpect import ShellCmdError
from virttest import utils_misc, utils_spice, aexpect


def install_pygtk(guest_session, params):
    """
    Install PyGTK to a VM with yum package manager.

    :param guest_session - ssh session to guest VM
    :param params
    """

    cmd = "rpm -q pygtk2"
    try:
        guest_session.cmd(cmd)
    except ShellCmdError:
        cmd = "yum -y install pygtk2 --nogpgcheck > /dev/null"
        logging.info("Installing pygtk2 package to %s",
                    params.get("guest_vm"))
        guest_session.cmd(cmd, timeout=60)


def deploy_test_form(test, guest_vm, params):
    """
    Copy wxPython Test form to guest VM.
    Test form is copied to /tmp directory.

    :param test
    :param guest_vm - vm object
    :param params
    """

    script = params.get("guest_script")
    scriptdir = os.path.join("scripts", script)
    script_path = utils_misc.get_path(test.virtdir, scriptdir)
    guest_vm.copy_files_to(script_path, "/tmp/%s" % params.get("guest_script"),
                           timeout=60)


def run_test_form(guest_session, params):
    """
    Start wxPython simple test form on guest VM.
    Test form catches KeyEvents and is located in /tmp.

    :param guest_session - ssh session to guest VM
    :param params
    """

    logging.info("Starting test form for catching key events on guest")
    cmd = "python /tmp/%s &> /dev/null &" % params.get("guest_script")
    guest_session.cmd(cmd)
    cmd = "disown -ar"
    guest_session.cmd(cmd)


def get_test_results(guest_vm):
    """
    :param guest_vm - vm object
    """

    path = "/tmp/autotest-rv_input"
    guest_vm.copy_files_from(path, path, timeout=60)

    return path


def test_type_and_func_keys(client_vm, guest_session, params):
    """
    Test typewriter and functional keys.
    Function sends various keys through qemu monitor to client VM.

    :param client_vm - vm object
    :param guest_session - ssh session to guest VM
    :param params
    """

    run_test_form(guest_session, params)
    utils_spice.wait_timeout(3)

    # Send typewriter and functional keys to client machine based on scancodes
    logging.info("Sending typewriter and functional keys to client machine")
    for i in range(1, 69):
        # Avoid Ctrl, RSH, LSH, PtScr, Alt, CpsLk
        if not (i in [29, 42, 54, 55, 56, 58]):
            client_vm.send_key(str(hex(i)))
            utils_spice.wait_timeout(0.3)


def test_leds_and_esc_keys(client_vm, guest_session, params):
    """
    Test LEDS and Escaped keys.
    Function sends various keys through qemu monitor to client VM.

    :param client_vm - vm object
    :param guest_session - ssh session to guest VM
    :param params
    """

    #Run PyGTK form catching KeyEvents on guest
    run_test_form(guest_session, params)
    utils_spice.wait_timeout(3)

    # Prepare lists with the keys to be sent to client machine
    leds = ['a', 'caps_lock', 'a', 'caps_lock', 'num_lock', 'kp_1', 'num_lock',
            'kp_1']
    shortcuts = ['a', 'shift-a', 'shift_r-a', 'ctrl-a', 'ctrl-c', 'ctrl-v',
                 'alt-x']
    escaped = ['insert', 'delete', 'home', 'end', 'pgup', 'pgdn', 'up',
               'down', 'right', 'left']

    test_keys = leds + shortcuts + escaped

    # Send keys to client machine
    logging.info("Sending leds and escaped keys to client machine")
    for key in test_keys:
        client_vm.send_key(key)
        utils_spice.wait_timeout(0.3)


def test_nonus_layout(client_vm, guest_session, params):
    """
    Test some keys of non-us keyboard layouts (de, cz).
    Function sends various keys through qemu monitor to client VM.

    :param client_vm - vm object
    :param guest_session - ssh session to guest VM
    :param params
    """

    #Run PyGTK form catching KeyEvents on guest
    run_test_form(guest_session, params)
    utils_spice.wait_timeout(3)

    # Czech layout - test some special keys
    cmd = "setxkbmap cz"
    guest_session.cmd(cmd)
    test_keys = ['7', '8', '9', '0', 'alt_r-x', 'alt_r-c', 'alt_r-v']
    logging.info("Sending czech keys to client machine")
    for key in test_keys:
        client_vm.send_key(key)
        utils_spice.wait_timeout(0.3)

    # German layout - test some special keys
    cmd = "setxkbmap de"
    guest_session.cmd(cmd)
    test_keys = ['minus', '0x1a', 'alt_r-q', 'alt_r-m']
    logging.info("Sending german keys to client machine")
    for key in test_keys:
        client_vm.send_key(key)
        utils_spice.wait_timeout(0.3)

    cmd = "setxkbmap us"
    guest_session.cmd(cmd)


def test_leds_migration(client_vm, guest_vm, guest_session, params):
    """
    Check LEDS after migration.
    Function sets LEDS (caps, num) to ON and send scancodes of "a" and "1 (num)"
    and expected to get keycodes of "A" and "1" after migration.

    :param client_vm - vm object
    :param guest_vm - vm object
    :param guest_session - ssh session to guest VM
    :param params
    """

    # Turn numlock on RHEL6 on before the test begins:
    grep_ver_cmd = "grep -o 'release [[:digit:]]' /etc/redhat-release"
    rhel_ver = guest_session.cmd(grep_ver_cmd).strip()

    logging.info("RHEL version: #{0}#".format(rhel_ver))

    if rhel_ver == "release 6":
        client_vm.send_key('num_lock')

    #Run PyGTK form catching KeyEvents on guest
    run_test_form(guest_session, params)
    utils_spice.wait_timeout(3)

    # Tested keys before migration
    test_keys = ['a', 'kp_1', 'caps_lock', 'num_lock', 'a', 'kp_1']
    logging.info("Sending leds keys to client machine before migration")
    for key in test_keys:
        client_vm.send_key(key)
        utils_spice.wait_timeout(0.3)

    guest_vm.migrate()
    utils_spice.wait_timeout(8)

    #Tested keys after migration
    test_keys = ['a', 'kp_1', 'caps_lock', 'num_lock']
    logging.info("Sending leds keys to client machine after migration")
    for key in test_keys:
        client_vm.send_key(key)
        utils_spice.wait_timeout(0.3)
    utils_spice.wait_timeout(30)


def analyze_results(file_path, test_type):
    """
    Analyze results - compare caught keycodes and expected keycodes.

    :param file_path - path to file with results
    :param test_type - type of the test
    """

    if test_type == "type_and_func_keys":
        #List of expected keycodes from guest machine
        correct_keycodes = ['65307', '49', '50', '51', '52', '53', '54', '55',
                            '56', '57', '48', '45', '61', '65288', '65289',
                            '113', '119', '101', '114', '116', '121', '117',
                            '105', '111', '112', '91', '93', '65293', '97',
                            '115', '100', '102', '103', '104', '106', '107',
                            '108', '59', '39', '96', '92', '122', '120', '99',
                            '118', '98', '110', '109', '44', '46', '47', '32',
                            '65470', '65471', '65472', '65473', '65474',
                             '65475', '65476', '65477', '65478', '65479']
    elif test_type == "leds_and_esc_keys":
        correct_keycodes = ['97', '65509', '65', '65509', '65407', '65457',
                            '65407', '65436', '97', '65505', '65', '65506',
                            '65', '65507', '97', '65507', '99', '65507', '118',
                            '65513', '120', '65379', '65535', '65360', '65367',
                            '65365', '65366', '65362', '65364', '65363',
                            '65361']
    elif test_type == "nonus_layout":
        correct_keycodes = ['253', '225', '237', '233', '65027', '35', '65027',
                            '38', '65027', '64', '223', '252', '65027', '64',
                            '65027', '181']
    elif test_type == "leds_migration":
        correct_keycodes = ['97', '65457', '65509', '65407', '65', '65436',
                            '65', '65436', '65509', '65407']

    # Read caught keycodes on guest machine
    fileobj = open(file_path, "r")
    keycodes = fileobj.read()
    fileobj.close()

    #Compare caught keycodes with expected keycodes
    test_keycodes = keycodes.split()
    logging.info("Caught keycodes:%s", test_keycodes)
    for i in range(len(correct_keycodes)):
        if not (test_keycodes[i] == correct_keycodes[i]):
            return correct_keycodes[i]

    return None


def run_rv_input(test, params, env):
    """
    Test for testing keyboard inputs through spice.
    Test depends on rv_connect test.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()

    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))
    guest_root_session = guest_vm.wait_for_login(
              timeout=int(params.get("login_timeout", 360)),
              username="root", password="123456")

    # Verify that gnome is now running on the guest
    try:
        guest_session.cmd("ps aux | grep -v grep | grep gnome-session")
    except aexpect.ShellCmdError:
        raise error.TestWarn("gnome-session was probably not corretly started")

    guest_session.cmd("export DISPLAY=:0.0")

    install_pygtk(guest_root_session, params)

    deploy_test_form(test, guest_vm, params)

    # Get test type and perform proper test
    test_type = params.get("config_test")
    test_mapping = {'type_and_func_keys': test_type_and_func_keys,
                    'leds_and_esc_keys': test_leds_and_esc_keys,
                    'nonus_layout': test_nonus_layout,
                    'leds_migration': test_leds_migration}
    test_parameters = {
        'type_and_func_keys': (client_vm, guest_session, params),
        'leds_and_esc_keys': (client_vm, guest_session, params),
        'nonus_layout': (client_vm, guest_session, params),
        'leds_migration': (client_vm, guest_vm, guest_session, params)}

    try:
        func = test_mapping[test_type]
        args = test_parameters[test_type]
    except:
        raise error.TestFail("Unknown type of test")

    func(*args)

    # Get file with caught keycodes from guest
    result_path = get_test_results(guest_vm)
    # Analyze results and raise fail exp. If sent scancodes
    # do not match with expected keycodes
    result = analyze_results(result_path, test_type)
    if result is not None:
        raise error.TestFail("Testing of sending keys failed:"
                             "  Expected keycode = %s" % result)

    guest_session.close()
