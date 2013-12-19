"""
rv_audio.py - play audio playback / record on guest
and detect any pauses in the audio stream.

Requires: rv_connect test

"""
import logging
from autotest.client.shared import error, utils


def verify_recording(recording, params):
    """Tests whether something was actually recorded

    Threshold is a number of bytes which have to be zeros, in order to
    record an unacceptable pause.
    11000 bytes is ~ 0.06236s (at 44100 Hz sampling, 16 bit depth
    and stereo)
    """
    rec = open(recording).read()

    disable_audio = params.get("disable_audio", "no")
    threshold = int(params.get("rv_audio_threshold", "25000"))
    config_test = params.get("config_test", None)

    if (len(rec) - rec.count('\0') < 50):
        logging.info("Recording is empty")
        if disable_audio != "yes":
            return False
        else:
            return True

    pauses = []
    pause = False
    try:
        for index, value in enumerate(rec):
            if value == '\0':
                if not pause:
                    pauses.append([index])
                    pause = True
            else:
                if pause:
                    pauses[-1].append(index - 1)
                    pause = False
                    if (pauses[-1][1] - pauses[-1][0]) < threshold:
                        pauses.pop()

        if len(pauses):
            logging.error("%d pauses detected:", len(pauses))
            for i in pauses:
                logging.info("start: %10fs     duration: %10fs" % (
                             (float(i[0]) / (2 * 2 * 44100)),
                             (float(i[1] - i[0]) / (2 * 2 * 44100))
                             ))
            # Two small hiccups are allowed when migrating
            if len(pauses) < 3 and config_test == "migration":
                return True
            else:
                return False
        else:
            logging.info("No pauses detected")

    except IndexError:
        # Too long pause, overflow in index
        return False

    return True


def run(test, params, env):

    guest_vm = env.get_vm(params["guest_vm"])
    guest_vm.verify_alive()
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    if(guest_session.cmd_status("ls %s" % params.get("audio_tgt"))):
        print params.get("audio_src")
        print params.get("audio_tgt")
        guest_vm.copy_files_to(
            params.get("audio_src"),
            params.get("audio_tgt"))
    if(client_session.cmd_status("ls %s" % params.get("audio_tgt"))):
        client_vm.copy_files_to(
            params.get("audio_src"),
            params.get("audio_tgt"))

    if params.get("rv_record") == "yes":
        logging.info("rv_record set; Testing recording")
        player = client_vm.wait_for_login(
            timeout=int(params.get("login_timeout", 360)))
        recorder_session = guest_vm.wait_for_login(
            timeout=int(params.get("login_timeout", 360)))
        recorder_session_vm = guest_vm
    else:
        logging.info("rv_record not set; Testing playback")
        player = guest_vm.wait_for_login(
            timeout=int(params.get("login_timeout", 360)))
        recorder_session = client_vm.wait_for_login(
            timeout=int(params.get("login_timeout", 360)))
        recorder_session_vm = client_vm

    player.cmd("aplay %s &> /dev/null &" %  # starts playback
               params.get("audio_tgt"), timeout=30)

    if params.get("config_test", "no") == "migration":
        bg = utils.InterruptedThread(guest_vm.migrate, kwargs={})
        bg.start()

    recorder_session.cmd("arecord -d %s -f cd -D hw:0,1 %s" % (  # records
        params.get("audio_time", "200"),  # duration
        params.get("audio_rec")),  # target
        timeout=500)

    if params.get("config_test", "no") == "migration":
        bg.join()

    recorder_session_vm.copy_files_from(
        params.get("audio_rec"), "./recorded.wav")
    if not verify_recording("./recorded.wav", params):
        raise error.TestFail("Test failed")
