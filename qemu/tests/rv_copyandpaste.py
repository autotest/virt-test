"""
rv_copyandpaste.py Tests copy&paste functionality between client and guest
                   using the spice vdagent daemon.

Requires: connected binaries remote-viewer, Xorg, gnome session

"""
import logging
import os
import time
from autotest.client.shared import error
from virttest import utils_misc, utils_spice, aexpect


def wait_timeout(timeout=10):
    """
    time.sleep(timeout) + logging.debug(timeout)

    :param timeout=10
    """
    logging.debug("Waiting (timeout=%ss)", timeout)
    time.sleep(timeout)


def clear_cb(session, params):
    """

    Use the clipboard script to copy an image into the clipboard.
    :param session: the ssh session where the clipboard is to be cleared
    :param params: Dictionary with the test parameters.
    """
    # Get the necessary parameters to clear the clipboard from the session
    script = params.get("guest_script")
    dst_path = params.get("dst_dir", "guest_script")
    script_clear_params = params.get("script_params_clear")
    interpreter = params.get("interpreter")
    script_call = os.path.join(dst_path, script)

    # Clear the clipboard from the client and guest
    clear_cmd = "%s %s %s" % (interpreter, script_call, script_clear_params)

    try:
        logging.info("Clearing the clipboard")
        session.cmd(clear_cmd)
    except aexpect.ShellCmdError:
        logging.debug("Clearing the clipboard, Test will continue")

    logging.info("Clipboard has been cleared.")


def place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                           script_params, dst_image_path, test_timeout):
    """
    Use the clipboard script to copy an image into the clipboard.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param dst_image_path: location of the image to be copied
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, dst_image_path)

    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "The image has been placed into the clipboard." in output:
            logging.info("Copying of the image was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")


def verify_img_paste(session_to_copy_from, interpreter, script_call,
                     script_params, final_image_path, test_timeout):
    """
    Use the clipboard script to paste an image from the clipboard.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param final_image_path: location of where the image should be pasted
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, final_image_path)

    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "Cb Image stored and saved to:" in output:
            logging.info("Copying of the image was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")
    # Get the checksum of the file
    cmd = "md5sum %s" % (final_image_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
    except aexpect.ShellCmdError:
        raise error.TestFail("Couldn't get the size of the file")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")
    # Get the size of the copied image, this will be used for
    # verification on the other session that the paste was successful
    file_checksum = output.split()[0]
    return file_checksum


def verify_img_paste_success(session_to_copy_from, interpreter, script_call,
                             script_params, final_image_path,
                             expected_checksum, test_timeout):
    """
    Verify an image paste is successful by pasting an image to a file and
    verify the checksum matches the expected value.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param final_image_path: location of where the image should be pasted
    :param expected_checksum: the checksum value of the image to be verified
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, final_image_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "Cb Image stored and saved to:" in output:
            logging.info("Copying of the image was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    finally:
        logging.info("------------ End of script output of the Pasting"
                     " Session ------------")
    # Get the checksum of the file
    cmd = "md5sum %s" % (final_image_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed.")

    logging.info("------------ End of script output of the Pasting"
                 " Session ------------")
    img_checksum = output.split()[0]
    if img_checksum == expected_checksum:
        print "PASS: The image was successfully pasted"
    else:
        raise error.TestFail("The pasting of the image failed")


def verify_img_paste_fails(session_to_copy_from, interpreter, script_call,
                           script_params, final_image_path, test_timeout):
    """
    Verify that pasting an image fails.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param final_image_path: location of where the image should be pasted
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, final_image_path)

    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "No image stored" in output:
            logging.info("PASS: Pasting the image failed as expected.")
        else:
            raise error.TestFail("Copying to the clipboard"
                                 "failed", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output of the Pasting"
                  " Session ------------")


def verify_text_copy(session_to_copy_from, interpreter, script_call,
                     script_params, string_length, final_text_path,
                     test_timeout):
    """
    Verify copying a large amount of textual data to the clipboard and to
    a file is successful, and return the checksum of the file.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param final_text_path: location of where the text file is created
    :param test_timeout: timeout time for the cmd

    :return: file_checksum: checksum of the textfile that was created.
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, string_length)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "The string has also been placed in the clipboard" in output:
            logging.info("Copying of the large text file was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")
    # Get the checksum of the file
    cmd = "md5sum %s" % (final_text_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
    except aexpect.ShellCmdError:
        raise error.TestFail("Couldn't get the size of the file")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")
    # Get the size of the copied image, this will be used for
    # verification on the other session that the paste was successful
    file_checksum = output.split()[0]
    return file_checksum


def verify_txt_paste_success(session_to_paste_to, interpreter,
                             script_call, script_params,
                             final_text_path, textfile_checksum, test_timeout):
    """
    Use the clipboard script to copy text into the clipboard.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param final_image_path: location of where the image should be pasted
    :param image_size: the size of the image to be verified
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, final_text_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_paste_to.cmd(cmd, print_func=logging.info,
                                         timeout=test_timeout)
        if "Writing of the clipboard text is complete" in output:
            logging.info("Copying of the large text file was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    finally:
        logging.info("------------ End of script output of the Pasting"
                     " Session ------------")
    # Get the checksum of the file
    cmd = "md5sum %s" % (final_text_path)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_paste_to.cmd(cmd, print_func=logging.info,
                                         timeout=test_timeout)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed.")

    logging.info("------------ End of script output of the Pasting"
                 " Session ------------")
    file_checksum = output.split()[0]
    if file_checksum == textfile_checksum:
        print "PASS: The large text file was successfully pasted"
    else:
        raise error.TestFail("The pasting of the large text file failed")


def place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout):
    """
    Use the clipboard script to copy text into the clipboard.

    :param session_to_copy_from: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param testing_text: text to be pasted
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s %s %s" % (interpreter, script_call,
                           script_params, testing_text)

    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if "The text has been placed into the clipboard." in output:
            logging.info("Copying of text was successful")
        else:
            raise error.TestFail("Copying to the clipboard failed", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output of the Copying"
                  " Session ------------")

    # Verify the clipboard of the session that is being copied from,
    # before continuing the test
    cmd = "%s %s" % (interpreter, script_call)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_copy_from.cmd(cmd, print_func=logging.info,
                                          timeout=test_timeout)
        if testing_text in output:
            logging.info("Text was successfully copied to the clipboard")
        else:
            raise error.TestFail("Copying to the clipboard Failed ", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Copying to the clipboard failed")

    logging.debug("------------ End of script output ------------")


def verify_paste_fails(session_to_paste_to, testing_text, interpreter,
                       script_call, test_timeout):
    """
    Test that pasting to the other session fails (negative testing:
    spice-vdagentd stopped or copy-paste-disabled is set on the VM

    :param session_to_paste_to: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param testing_text: text to be pasted
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s" % (interpreter, script_call)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_paste_to.cmd(cmd, print_func=logging.info,
                                         timeout=test_timeout)
        if testing_text in output:
            raise error.TestFail("Pasting from the clipboard was"
                                 " successful, text was copied from the other"
                                 " session with vdagent stopped!!", output)
        else:
            logging.info("PASS: Pasting from the clipboard was not"
                         " successful, as EXPECTED")
    except aexpect.ShellCmdError:
        raise error.TestFail("Pasting from the clipboard failed.")

    logging.debug("------------ End of script output ------------")


def verify_paste_successful(session_to_paste_to, testing_text, interpreter,
                            script_call, test_timeout):
    """
    Test that pasting to the other session fails (negative testing -
    spice-vdagentd stopped or copy-paste-disabled is set on the VM

    :param session_to_paste_to: VM ssh session where text is to be copied
    :param interpreter: script param
    :param script_call: script param
    :param script_params: script param
    :param testing_text: text to be pasted
    :param test_timeout: timeout time for the cmd
    """
    cmd = "%s %s" % (interpreter, script_call)
    try:
        logging.debug("------------ Script output ------------")
        output = session_to_paste_to.cmd(cmd, print_func=logging.info,
                                         timeout=test_timeout)
        if testing_text in output:
            logging.info("Pasting from the clipboard is successful")
        else:
            raise error.TestFail("Pasting from the clipboard failed, "
                                 "nothing copied from other session", output)
    except aexpect.ShellCmdError:
        raise error.TestFail("Pasting from the clipboard failed.")

    logging.debug("------------ End of script output ------------")


def copy_and_paste_neg(session_to_copy_from, session_to_paste_to,
                       guest_session, params):
    """
    Negative Test: Sending the commands to copy from one session to another,
    and make sure it does not work, because spice vdagent is off

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_params = params.get("script_params", "")
    dst_path = params.get("dst_dir", "guest_script")
    script_call = os.path.join(dst_path, script)
    testing_text = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is installed and the
    # daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Stop vdagent for this negative test
    utils_spice.stop_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout)
    # Now test to see if the copied text from the one session can
    # be pasted on the other
    verify_paste_fails(session_to_paste_to, testing_text, interpreter,
                       script_call, test_timeout)


def copy_and_paste_pos(session_to_copy_from, session_to_paste_to,
                       guest_session, params):
    """
    Sending the commands to copy from one session to another, and make
    sure it works correctly

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_params = params.get("script_params", "")
    dst_path = params.get("dst_dir", "guest_script")
    script_call = os.path.join(dst_path, script)
    testing_text = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout)
    # Now test to see if the copied text from the one session can be
    # pasted on the other
    verify_paste_successful(session_to_paste_to, testing_text, interpreter,
                            script_call, test_timeout)


def restart_cppaste(session_to_copy_from, session_to_paste_to,
                    guest_session, params):
    """
    Sending the commands to copy from one session to another, and make
    sure it works correctly after Restarting vdagent

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_params = params.get("script_params", "")
    dst_path = params.get("dst_dir", "guest_script")
    script_call = os.path.join(dst_path, script)
    testing_text = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout)
    # Now test to see if the copied text from the one session can be
    # pasted on the other
    verify_paste_successful(session_to_paste_to, testing_text, interpreter,
                            script_call, test_timeout)
    # Restart vdagent, clear the clipboard, verify cp and paste still works
    utils_spice.restart_vdagent(guest_session, test_timeout)

    clear_cb(session_to_paste_to, params)
    clear_cb(session_to_copy_from, params)
    wait_timeout(5)

    # Command to copy text and put it in the keyboard, copy on the client
    place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout)

    wait_timeout(5)
    # Now test to see if the copied text from the one session can be
    # pasted on the other
    verify_paste_successful(session_to_paste_to, testing_text, interpreter,
                            script_call, test_timeout)


def copy_and_paste_cpdisabled_neg(session_to_copy_from, session_to_paste_to,
                                  guest_session, params):
    """
    Negative Test: Sending the commands to copy from one session to another,
    for this test cp/paste will be disabled from qemu-kvm, Verify with vdagent
    started that copy/paste will fail.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_params = params.get("script_params", "")
    dst_path = params.get("dst_dir", "guest_script")
    script_call = os.path.join(dst_path, script)
    testing_text = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is installed and the
    # daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_text_in_clipboard(session_to_copy_from, interpreter, script_call,
                            script_params, testing_text, test_timeout)
    # Now test to see if the copied text from the one session can be pasted
    # on the other session
    verify_paste_fails(session_to_paste_to, testing_text, interpreter,
                       script_call, test_timeout)


def copy_and_paste_largetext(session_to_copy_from, session_to_paste_to,
                             guest_session, params):
    """
    Sending the commands to copy large text from one session to another, and
    make sure the data is still correct.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_write_params = params.get("script_params_writef")
    script_create_params = params.get("script_params_createf")
    dst_path = params.get("dst_dir", "guest_script")
    final_text_path = os.path.join(params.get("dst_dir"),
                                   params.get("final_textfile"))
    script_call = os.path.join(dst_path, script)
    string_length = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)

    # Command to copy text and put it in the clipboard
    textfile_checksum = verify_text_copy(session_to_copy_from, interpreter,
                                         script_call, script_create_params,
                                         string_length, final_text_path, test_timeout)
    wait_timeout(30)

    # Verify the paste on the session to paste to
    verify_txt_paste_success(session_to_paste_to, interpreter,
                             script_call, script_write_params,
                             final_text_path, textfile_checksum, test_timeout)


def restart_cppaste_lrgtext(session_to_copy_from, session_to_paste_to,
                            guest_session, params):
    """
    Sending the commands to copy large text from one session to another, and
    make sure the data is still correct after restarting vdagent.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_write_params = params.get("script_params_writef")
    script_create_params = params.get("script_params_createf")
    dst_path = params.get("dst_dir", "guest_script")
    final_text_path = os.path.join(params.get("dst_dir"),
                                   params.get("final_textfile"))
    script_call = os.path.join(dst_path, script)
    string_length = params.get("text_to_test")

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)

    # Command to copy text and put it in the clipboard
    textfile_checksum = verify_text_copy(session_to_copy_from, interpreter,
                                         script_call, script_create_params,
                                         string_length, final_text_path, test_timeout)
    wait_timeout(30)

    # Verify the paste on the session to paste to
    verify_txt_paste_success(session_to_paste_to, interpreter,
                             script_call, script_write_params,
                             final_text_path, textfile_checksum, test_timeout)
    # Restart vdagent & clear the clipboards.
    utils_spice.restart_vdagent(guest_session, test_timeout)
    clear_cb(session_to_paste_to, params)
    clear_cb(session_to_copy_from, params)
    wait_timeout(5)

    # Command to copy text and put it in the clipboard
    textfile_checksum = verify_text_copy(session_to_copy_from, interpreter,
                                         script_call, script_create_params,
                                         string_length, final_text_path, test_timeout)
    wait_timeout(30)

    # Verify the paste on the session to paste to
    verify_txt_paste_success(session_to_paste_to, interpreter,
                             script_call, script_write_params,
                             final_text_path, textfile_checksum, test_timeout)


def copy_and_paste_image_pos(session_to_copy_from, session_to_paste_to,
                             guest_session, params):
    """
    Sending the commands to copy an image from one session to another.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    image_type = params.get("image_type")
    script_set_params = params.get("script_params_img_set")
    script_save_params = params.get("script_params_img_save")
    dst_path = params.get("dst_dir", "guest_script")
    dst_image_path = os.path.join(params.get("dst_dir"),
                                  params.get("image_tocopy_name"))
    dst_image_path_bmp = os.path.join(params.get("dst_dir"),
                                      params.get("image_tocopy_name_bmp"))
    final_image_path = os.path.join(params.get("dst_dir"),
                                    params.get("final_image"))
    final_image_path_bmp = os.path.join(params.get("dst_dir"),
                                        params.get("final_image_bmp"))
    script_call = os.path.join(dst_path, script)

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)

    if "png" in image_type:
        # Command to copy text and put it in the keyboard, copy on the client
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path, test_timeout)
        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path, image_size, test_timeout)
    else:
        # Testing bmp
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path_bmp, test_timeout)

        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path_bmp, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path_bmp, image_size, test_timeout)


def restart_cppaste_image(session_to_copy_from, session_to_paste_to,
                          guest_session, params):
    """
    Sending the commands to copy an image from one session to another.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    image_type = params.get("image_type")
    script_set_params = params.get("script_params_img_set")
    script_save_params = params.get("script_params_img_save")
    dst_path = params.get("dst_dir", "guest_script")
    dst_image_path = os.path.join(params.get("dst_dir"),
                                  params.get("image_tocopy_name"))
    dst_image_path_bmp = os.path.join(params.get("dst_dir"),
                                      params.get("image_tocopy_name_bmp"))
    final_image_path = os.path.join(params.get("dst_dir"),
                                    params.get("final_image"))
    final_image_path_bmp = os.path.join(params.get("dst_dir"),
                                        params.get("final_image_bmp"))
    script_call = os.path.join(dst_path, script)

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)

    if "png" in image_type:
        # Command to copy text and put it in the keyboard, copy on the client
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path, test_timeout)
        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path, image_size, test_timeout)
    else:
        # Testing bmp
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path_bmp, test_timeout)

        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path_bmp, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path_bmp, image_size, test_timeout)
    # Restart vdagent & clear the clipboards.
    utils_spice.restart_vdagent(guest_session, test_timeout)
    clear_cb(session_to_paste_to, params)
    clear_cb(session_to_copy_from, params)
    wait_timeout(5)

    if "png" in image_type:
        # Command to copy text and put it in the keyboard, copy on the client
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path, test_timeout)
        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path, image_size, test_timeout)
    else:
        # Testing bmp
        place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                               script_set_params, dst_image_path_bmp, test_timeout)

        # Now test to see if the copied text from the one session can be
        # pasted on the other
        image_size = verify_img_paste(session_to_copy_from, interpreter,
                                      script_call, script_save_params,
                                      final_image_path_bmp, test_timeout)
        wait_timeout(30)

        # Verify the paste on the session to paste to
        verify_img_paste_success(session_to_paste_to, interpreter,
                                 script_call, script_save_params,
                                 final_image_path_bmp, image_size, test_timeout)


def copy_and_paste_image_neg(session_to_copy_from, session_to_paste_to,
                             guest_session, params):
    """
    Negative Test: Sending the commands to copy an image from one
    session to another, with spice-vdagentd off, so copy and pasting
    the image should fail.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_set_params = params.get("script_params_img_set")
    script_save_params = params.get("script_params_img_save")
    dst_path = params.get("dst_dir", "guest_script")
    dst_image_path = os.path.join(params.get("dst_dir"),
                                  params.get("image_tocopy_name"))
    final_image_path = os.path.join(params.get("dst_dir"),
                                    params.get("final_image"))
    script_call = os.path.join(dst_path, script)

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Stop vdagent for this negative test
    utils_spice.stop_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                           script_set_params, dst_image_path, test_timeout)
    # Now test to see if the copied text from the one session can be
    # pasted on the other
    verify_img_paste(session_to_copy_from, interpreter,
                     script_call, script_save_params,
                     final_image_path, test_timeout)
    # Verify the paste on the session to paste to
    verify_img_paste_fails(session_to_paste_to, interpreter,
                           script_call, script_save_params,
                           final_image_path, test_timeout)


def copyandpasteimg_cpdisabled_neg(session_to_copy_from, session_to_paste_to,
                                   guest_session, params):
    """
    Negative Tests Sending the commands to copy an image from one
    session to another; however, copy-paste will be disabled on the VM
    so the pasting should fail.

    :param session_to_copy_from: ssh session of the vm to copy from
    :param session_to_paste_to: ssh session of the vm to paste to
    :param guest_session: guest ssh session
    :param params: Dictionary with the test parameters.
    """
    # Get necessary params
    test_timeout = float(params.get("test_timeout", 600))
    interpreter = params.get("interpreter")
    script = params.get("guest_script")
    script_set_params = params.get("script_params_img_set")
    script_save_params = params.get("script_params_img_save")
    dst_path = params.get("dst_dir", "guest_script")
    dst_image_path = os.path.join(params.get("dst_dir"),
                                  params.get("image_tocopy_name"))
    final_image_path = os.path.join(params.get("dst_dir"),
                                    params.get("final_image"))
    script_call = os.path.join(dst_path, script)

    # Before doing the copy and paste, verify vdagent is
    # installed and the daemon is running on the guest
    utils_spice.verify_vdagent(guest_session, test_timeout)
    # Make sure virtio driver is running
    utils_spice.verify_virtio(guest_session, test_timeout)
    # Command to copy text and put it in the keyboard, copy on the client
    place_img_in_clipboard(session_to_copy_from, interpreter, script_call,
                           script_set_params, dst_image_path, test_timeout)
    # Now test to see if the copied text from the one session can be
    # pasted on the other
    verify_img_paste(session_to_copy_from, interpreter,
                     script_call, script_save_params,
                     final_image_path, test_timeout)
    wait_timeout(30)

    # Verify the paste on the session to paste to
    verify_img_paste_fails(session_to_paste_to, interpreter,
                           script_call, script_save_params,
                           final_image_path, test_timeout)


def run_rv_copyandpaste(test, params, env):
    """
    Testing copying and pasting between a client and guest
    Supported configurations:
    config_test: defines the test to run (Copying image, text, large textual
    data, positive or negative, and disabled copy paste set to be true or false
    text_to_test: In config defines the text to copy, and if it is numeric it
    will copy that amount of textual data, which is generated by cb.py.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    # Collect test parameters
    test_type = params.get("config_test")
    script = params.get("guest_script")
    dst_path = params.get("dst_dir", "guest_script")
    image_type = params.get("image_type")
    dst_image_path = params.get("dst_dir", "image_tocopy_name")
    dst_image_path_bmp = params.get("dst_dir", "image_tocopy_name_bmp")
    cp_disabled_test = params.get("disable_copy_paste")
    image_name = params.get("image_tocopy_name")
    image_name_bmp = params.get("image_tocopy_name_bmp")
    testing_text = params.get("text_to_test")
    client_vm = env.get_vm(params["client_vm"])
    client_vm.verify_alive()
    client_session = client_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))

    guest_vm = env.get_vm(params["guest_vm"])
    guest_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)))
    guest_root_session = guest_vm.wait_for_login(
        timeout=int(params.get("login_timeout", 360)),
        username="root", password="123456")
    logging.info("Get PID of remote-viewer")
    client_session.cmd("pgrep remote-viewer")

    guest_vm.verify_alive()
    # The following is to copy files to the client and guest and do the test
    # copy the script to both the client and guest
    scriptdir = os.path.join("scripts", script)
    script_path = utils_misc.get_path(test.virtdir, scriptdir)

    # The following is to copy the test image to either the client or guest
    # if the test deals with images.
    imagedir = os.path.join("deps", image_name)
    imagedir_bmp = os.path.join("deps", image_name_bmp)
    image_path = utils_misc.get_path(test.virtdir, imagedir)
    image_path_bmp = utils_misc.get_path(test.virtdir, imagedir_bmp)

    logging.info("Transferring the clipboard script to client & guest,"
                 "destination directory: %s, source script location: %s",
                 dst_path, script_path)

    client_vm.copy_files_to(script_path, dst_path, timeout=60)
    guest_vm.copy_files_to(script_path, dst_path, timeout=60)

    if "image" in test_type:
        if "client_to_guest" in test_type:
            if "png" in image_type:
                logging.info("Transferring the image to client"
                             "destination directory: %s, source image: %s",
                             dst_image_path, image_path)
                client_vm.copy_files_to(image_path, dst_image_path, timeout=60)
            else:
                logging.info("Transferring a bmp image to client"
                             "destination directory: %s, source image: %s",
                             dst_image_path_bmp, image_path_bmp)
                client_vm.copy_files_to(image_path_bmp, dst_image_path_bmp,
                                        timeout=60)
        elif "guest_to_client" in test_type:
            if "png" in image_type:
                logging.info("Transferring the image to client"
                             "destination directory: %s, source image: %s",
                             dst_image_path, image_path)
                guest_vm.copy_files_to(image_path, dst_image_path, timeout=60)
            else:
                logging.info("Transferring a bmp image to client"
                             "destination directory: %s, source image: %s",
                             dst_image_path_bmp, image_path_bmp)
                guest_vm.copy_files_to(image_path_bmp, dst_image_path_bmp,
                                       timeout=60)
        else:
            raise error.TestFail("Incorrect Test_Setup")

    client_session.cmd("export DISPLAY=:0.0")

    # Verify that gnome is now running on the guest
    try:
        guest_session.cmd("ps aux | grep -v grep | grep gnome-session")
    except aexpect.ShellCmdError:
        raise error.TestWarn(
            "gnome-session was probably not correctly started")

    guest_session.cmd("export DISPLAY=:0.0")

    # Make sure the clipboards are clear before starting the test
    clear_cb(guest_session, params)
    clear_cb(client_session, params)
    wait_timeout(5)

    # Figure out which test needs to be run
    if (cp_disabled_test == "yes"):
        # These are negative tests, clipboards are not synced because the VM
        # is set to disable copy and paste.
        if "client_to_guest" in test_type:
            if "image" in test_type:
                logging.info("Negative Test Case: Copy/Paste Disabled, Copying"
                             "Image from the Client to Guest Should Not Work\n")
                copyandpasteimg_cpdisabled_neg(client_session, guest_session,
                                               guest_root_session, params)
            else:
                logging.info("Negative Test Case: Copy/Paste Disabled, Copying"
                             " from the Client to Guest Should Not Work\n")
                copy_and_paste_cpdisabled_neg(client_session, guest_session,
                                              guest_root_session, params)
        if "guest_to_client" in test_type:
            if "image" in test_type:
                logging.info("Negative Test Case: Copy/Paste Disabled, Copying"
                             "Image from the Guest to Client Should Not Work\n")
                copyandpasteimg_cpdisabled_neg(guest_session, client_session,
                                               guest_root_session, params)
            else:
                logging.info("Negative Test Case: Copy/Paste Disabled, Copying"
                             " from the Guest to Client Should Not Work\n")
                copy_and_paste_cpdisabled_neg(guest_session, client_session,
                                              guest_root_session, params)

    elif "positive" in test_type:
        # These are positive tests, where the clipboards are synced because
        # copy and paste is not disabled and the spice-vdagent is running
        if "client_to_guest" in test_type:
            if "image" in test_type:
                if "restart" in test_type:
                    logging.info("Restart Vdagent, Cp Img Client to Guest")
                    restart_cppaste_image(client_session, guest_session,
                                          guest_root_session, params)
                else:
                    logging.info("Copying an Image from the Client to Guest")
                    copy_and_paste_image_pos(client_session, guest_session,
                                             guest_root_session, params)
            elif testing_text.isdigit():
                if "restart" in test_type:
                    logging.info("Restart Vdagent, Copying a String of size "
                                 + testing_text + " from the Client to Guest")
                    restart_cppaste_lrgtext(client_session, guest_session,
                                            guest_root_session, params)
                else:
                    logging.info("Copying a String of size " + testing_text +
                                 " from the Client to Guest")
                    copy_and_paste_largetext(client_session, guest_session,
                                             guest_root_session, params)
            else:
                if "restart" in test_type:
                    logging.info(
                        "Restart Vdagent, Copying from Client to Guest\n")
                    restart_cppaste(client_session, guest_session,
                                    guest_root_session, params)
                else:
                    logging.info("Copying from the Client to Guest\n")
                    copy_and_paste_pos(client_session, guest_session,
                                       guest_root_session, params)
        if "guest_to_client" in test_type:
            if "image" in test_type:
                if "restart" in test_type:
                    logging.info("Restart Vdagent, Copy Img Guest to Client")
                    restart_cppaste_image(guest_session, client_session,
                                          guest_root_session, params)
                else:
                    logging.info("Copying an Image from the Guest to Client")
                    copy_and_paste_image_pos(guest_session, client_session,
                                             guest_root_session, params)
            elif testing_text.isdigit():
                if "restart" in test_type:
                    logging.info("Restart Vdagent, Copying a String of size "
                                 + testing_text + " from the Guest to Client")
                    restart_cppaste_lrgtext(guest_session, client_session,
                                            guest_root_session, params)
                else:
                    logging.info("Copying a String of size " + testing_text +
                                 " from the Guest to Client")
                    copy_and_paste_largetext(guest_session, client_session,
                                             guest_root_session, params)
            else:
                if "restart" in test_type:
                    logging.info("Restart Vdagent, Copying: Client to Guest\n")
                    restart_cppaste(guest_session, client_session,
                                    guest_root_session, params)
                else:
                    logging.info("Copying from the Guest to Client\n")
                    copy_and_paste_pos(guest_session, client_session,
                                       guest_root_session, params)
    elif "negative" in test_type:
        # These are negative tests, where the clipboards are not synced because
        # the spice-vdagent service will not be running on the guest.
        if "client_to_guest" in test_type:
            if "image" in test_type:
                logging.info("Negative Test Case: Copying an Image from the "
                             "Client to Guest")
                copy_and_paste_image_neg(client_session, guest_session,
                                         guest_root_session, params)
            else:
                logging.info("Negative Test Case: Copying from the Client to"
                             "Guest Should Not Work\n")
                copy_and_paste_neg(client_session, guest_session,
                                   guest_root_session, params)
        if "guest_to_client" in test_type:
            if "image" in test_type:
                logging.info("Negative Test Case: Copying an Image from the "
                             "Guest to Client")
                copy_and_paste_image_neg(guest_session, client_session,
                                         guest_root_session, params)
            else:
                logging.info("Negative Test Case: Copying from the Guest to"
                             " Client Should Not Work\n")
                copy_and_paste_neg(guest_session, client_session,
                                   guest_root_session, params)
    else:
        # The test is not supported, verify what is a supported test.
        raise error.TestFail("Couldn't Find the Correct Test To Run")
