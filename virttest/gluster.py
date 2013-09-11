"""
GlusterFS Support
This file has the functions that helps
* To create/check gluster volume.
* To start/check gluster services.
* To create gluster uri which can be used as disk image file path.
"""

import logging
import os
import re
from autotest.client.shared import utils, error


@error.context_aware
def glusterd_start():
    """
    Check for glusterd status
    """
    cmd = "service glusterd status"
    output = utils.system_output(cmd, ignore_status=True)
    if 'stopped' in output:
        cmd = "service glusterd start"
        error.context("Starting gluster dameon failed")
        output = utils.system_output(cmd)


def is_gluster_vol_started(vol_name):
    """
    Returns if the volume is started, if not send false
    """
    cmd = "gluster volume info %s" % vol_name
    error.context("Gluster volume info failed for volume: %s" % vol_name)
    vol_info = utils.system_output(cmd)
    volume_status = re.findall(r'Status: (\S+)', vol_info)
    if 'Started' in volume_status:
        return True
    else:
        return False


def gluster_vol_start(vol_name):
    """
    Starts the volume if it is stopped
    """
    # Check if the volume is stopped, if then start
    if not is_gluster_vol_started(vol_name):
        error.context("Gluster volume start failed for volume; %s" % vol_name)
        cmd = "gluster volume start %s" % vol_name
        utils.system(cmd)
        return True
    else:
        return True


def is_gluster_vol_avail(vol_name):
    """
    Returns if the volume already available
    """
    cmd = "gluster volume info"
    error.context("Gluster volume info failed")
    output = utils.system_output(cmd)
    volume_name = re.findall(r'Volume Name: (%s)\n' % vol_name, output)
    if volume_name:
        return gluster_vol_start(vol_name)


def gluster_brick_create(brick_path):
    """
    Creates brick
    """
    if not os.path.isdir(brick_path):
        try:
            os.mkdir(brick_path)
            return True
        except OSError, details:
            logging.error("Not able to create brick folder %s", details)


def gluster_vol_create(vol_name, hostname, brick_path):
    """
    Gluster Volume Creation
    """
    # Create a brick
    gluster_brick_create(brick_path)

    cmd = "gluster volume create %s %s:/%s" % (vol_name, hostname,
                                               brick_path)
    error.context("Volume creation failed")
    utils.system(cmd)


def create_gluster_uri(params):
    """
    Find/create gluster volume
    """
    vol_name = params.get("gluster_volume_name")
    brick_path = params.get("gluster_brick")
    error.context("Host name lookup failed")
    hostname = utils.system_output("hostname -f")
    cmd = "ip addr show|grep -A2 'state UP'|grep inet|awk '{print $2}'|cut -d'/' -f1"
    if not hostname:
        ip_addr = utils.system_output(cmd).split()
        hostname = ip_addr[0]

    # Start the gluster dameon, if not started
    glusterd_start()
    # Check for the volume is already present, if not create one.
    if not is_gluster_vol_avail(vol_name):
        gluster_vol_create(vol_name, hostname, brick_path)

    # Building gluster uri
    gluster_uri = "gluster://%s:0/%s/" % (hostname, vol_name)
    return gluster_uri


def get_image_filename(params, image_name, image_format):
    """
    Form the image file name using gluster uri
    """

    img_name = image_name.split('/')[-1]
    gluster_uri = create_gluster_uri(params)
    image_filename = "%s%s.%s" % (gluster_uri, img_name, image_format)
    return image_filename
