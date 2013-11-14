"""
rv_video.py - Starts video player
Video is played in a loop, usually kill_app
test should be called later to close totem.

Requires: binaries Xorg, totem, gnome-session
          Test starts video player

"""
import logging
import os
from virttest import utils_misc, remote


def launch_totem(guest_session, params):
    """
    Launch Totem player

    :param guest_vm - vm object
    """

    totem_version = guest_session.cmd('totem --version')
    logging.info("Totem version: %s", totem_version)

    # repeat parameters for totem
    logging.info("Set up video repeat to '%s' to the Totem.",
                 params.get("repeat_video"))

    if params.get("repeat_video") == "yes":
        cmd = "gconftool-2 --set /apps/totem/repeat -t bool true"
    else:
        cmd = "gconftool-2 --set /apps/totem/repeat -t bool false"

    guest_session.cmd(cmd)

    cmd = "export DISPLAY=:0.0"
    guest_session.cmd(cmd)

    # fullscreen parameters for totem
    if params.get("fullscreen"):
        fullscreen = " --fullscreen "
    else:
        fullscreen = ""

    cmd = "nohup totem %s %s --display=:0.0 --play &> /dev/null &" \
        % (fullscreen, params.get("destination_video_file_path"))
    guest_session.cmd(cmd)


def deploy_video_file(test, vm_obj, params):
    """
    Deploy video file into destination on vm

    :param vm_obj - vm object
    :param params: Dictionary with the test parameters.
    """
    source_video_file = params.get("source_video_file")
    video_dir = os.path.join("deps", source_video_file)
    video_path = utils_misc.get_path(test.virtdir, video_dir)

    remote.copy_files_to(vm_obj.get_address(), 'scp',
                         params.get("username"),
                         params.get("password"),
                         params.get("shell_port"),
                         video_path,
                         params.get("destination_video_file_path"))


def run(test, params, env):
    """
    Test of video through spice

    :param test: KVM test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))
    deploy_video_file(test, guest_vm, params)

    launch_totem(guest_session, params)
    guest_session.close()
