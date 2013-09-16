import urllib2
import logging
import os
import glob
import ConfigParser
from autotest.client import utils
import data_dir
import re


def get_all_assets():
    asset_data_list = []
    download_dir = data_dir.get_download_dir()
    for asset in glob.glob(os.path.join(download_dir, '*.ini')):
        asset_name = os.path.basename(asset).split('.')[0]
        asset_data_list.append(get_asset_info(asset_name))
    return asset_data_list


def get_file_asset(title, src_path, destination):
    if not os.path.isabs(destination):
        destination = os.path.join(data_dir.get_data_dir(), destination)

    for ext in (".xz", ".gz", ".7z", ".bz2"):
        if os.path.exists(src_path + ext):
            destination = destination + ext
            logging.debug('Found source image %s', destination)
            return {
                'url': None, 'sha1_url': None, 'destination': src_path + ext,
                'destination_uncompressed': destination,
                'uncompress_cmd': None, 'shortname': title, 'title': title,
                'downloaded': True}

    if os.path.exists(src_path):
        logging.debug('Found source image %s', destination)
        return {'url': src_path, 'sha1_url': None, 'destination': destination,
                'destination_uncompressed': None, 'uncompress_cmd': None,
                'shortname': title, 'title': title,
                'downloaded': os.path.exists(destination)}

    return None


def get_asset_info(asset):
    asset_path = os.path.join(data_dir.get_download_dir(), '%s.ini' % asset)
    asset_cfg = ConfigParser.ConfigParser()
    asset_cfg.read(asset_path)

    url = asset_cfg.get(asset, 'url')
    try:
        sha1_url = asset_cfg.get(asset, 'sha1_url')
    except ConfigParser.NoOptionError:
        sha1_url = None
    title = asset_cfg.get(asset, 'title')
    destination = asset_cfg.get(asset, 'destination')
    if not os.path.isabs(destination):
        destination = os.path.join(data_dir.get_data_dir(), destination)
    asset_exists = os.path.isfile(destination)

    # Optional fields
    try:
        destination_uncompressed = asset_cfg.get(asset,
                                                 'destination_uncompressed')
        if not os.path.isabs(destination_uncompressed):
            destination_uncompressed = os.path.join(data_dir.get_data_dir(),
                                                    destination_uncompressed)
    except:
        destination_uncompressed = None

    try:
        uncompress_cmd = asset_cfg.get(asset, 'uncompress_cmd')
    except:
        uncompress_cmd = None

    return {'url': url, 'sha1_url': sha1_url, 'destination': destination,
            'destination_uncompressed': destination_uncompressed,
            'uncompress_cmd': uncompress_cmd, 'shortname': asset,
            'title': title,
            'downloaded': asset_exists}


def uncompress_asset(asset_info, force=False):
    destination = asset_info['destination']
    uncompress_cmd = asset_info['uncompress_cmd']
    destination_uncompressed = asset_info['destination_uncompressed']

    archive_re = re.compile(r".*\.(gz|xz|7z|bz2)$")
    if destination_uncompressed is not None:
        if uncompress_cmd is None:
            match = archive_re.match(destination)
            if match:
                if match.group(1) == 'gz':
                    uncompress_cmd = ('gzip -cd %s > %s' %
                                      (destination_uncompressed, destination))
                elif match.group(1) == 'xz':
                    uncompress_cmd = ('xz -cd %s > %s' %
                                      (destination_uncompressed, destination))
                elif match.group(1) == 'bz2':
                    uncompress_cmd = ('bzip2 -cd %s > %s' %
                                      (destination_uncompressed, destination))
                elif match.group(1) == '7z':
                    uncompress_cmd = '7za -y e %s' % destination
        else:
            uncompress_cmd = "%s %s" % (uncompress_cmd, destination)

    if uncompress_cmd is not None:
        uncompressed_file_exists = os.path.exists(destination_uncompressed)
        force = (force or not uncompressed_file_exists)

        if os.path.isfile(destination) and force:
            os.chdir(os.path.dirname(destination_uncompressed))
            utils.run(uncompress_cmd)


def download_file(asset_info, interactive=False, force=False):
    """
    Verifies if file that can be find on url is on destination with right hash.

    This function will verify the SHA1 hash of the file. If the file
    appears to be missing or corrupted, let the user know.

    :param asset_info: Dictionary returned by get_asset_info
    """
    file_ok = False
    problems_ignored = False
    had_to_download = False
    sha1 = None

    url = asset_info['url']
    sha1_url = asset_info['sha1_url']
    destination = asset_info['destination']
    title = asset_info['title']

    if sha1_url is not None:
        try:
            logging.info("Verifying expected SHA1 sum from %s", sha1_url)
            sha1_file = urllib2.urlopen(sha1_url)
            sha1_contents = sha1_file.read()
            sha1 = sha1_contents.split(" ")[0]
            logging.info("Expected SHA1 sum: %s", sha1)
        except Exception, e:
            logging.error("Failed to get SHA1 from file: %s", e)
    else:
        sha1 = None

    destination_dir = os.path.dirname(destination)
    if not os.path.isdir(destination_dir):
        os.makedirs(destination_dir)

    if not os.path.isfile(destination):
        logging.warning("File %s not found", destination)
        if interactive:
            answer = utils.ask("Would you like to download it from %s?" % url)
        else:
            answer = 'y'
        if answer == 'y':
            utils.interactive_download(
                url, destination, "Downloading %s" % title)
            had_to_download = True
        else:
            logging.warning("Missing file %s", destination)
    else:
        logging.info("Found %s", destination)
        if sha1 is None:
            answer = 'n'
        else:
            answer = 'y'

        if answer == 'y':
            actual_sha1 = utils.hash_file(destination, method='sha1')
            if actual_sha1 != sha1:
                logging.info("Actual SHA1 sum: %s", actual_sha1)
                if interactive:
                    answer = utils.ask("The file seems corrupted or outdated. "
                                       "Would you like to download it?")
                else:
                    logging.info("The file seems corrupted or outdated")
                    answer = 'y'
                if answer == 'y':
                    logging.info("Updating image to the latest available...")
                    while not file_ok:
                        utils.interactive_download(url, destination, title)
                        sha1_post_download = utils.hash_file(destination,
                                                             method='sha1')
                        had_to_download = True
                        if sha1_post_download != sha1:
                            logging.error("Actual SHA1 sum: %s", actual_sha1)
                            if interactive:
                                answer = utils.ask("The file downloaded %s is "
                                                   "corrupted. Would you like "
                                                   "to try again?" %
                                                   destination)
                            else:
                                answer = 'n'
                            if answer == 'n':
                                problems_ignored = True
                                logging.error("File %s is corrupted" %
                                              destination)
                                file_ok = True
                            else:
                                file_ok = False
                        else:
                            file_ok = True
            else:
                file_ok = True
                logging.info("SHA1 sum check OK")
        else:
            problems_ignored = True
            logging.info("File %s present, but did not verify integrity",
                         destination)

    if file_ok:
        if not problems_ignored:
            logging.info("%s present, with proper checksum", destination)

    uncompress_asset(asset_info=asset_info, force=force or had_to_download)


def download_asset(asset, interactive=True, restore_image=False):
    """
    Download an asset defined on an asset file.

    Asset files are located under /shared/downloads, are .ini files with the
    following keys defined:
        title: Title string to display in the download progress bar.
        url = URL of the resource
        sha1_url = URL with SHA1 information for the resource, in the form
            sha1sum file_basename
        destination = Location of your file relative to the data directory
            (TEST_SUITE_ROOT/shared/data)
        destination = Location of the uncompressed file relative to the data
            directory (TEST_SUITE_ROOT/shared/data)
        uncompress_cmd = Command that needs to be executed with the compressed
            file as a parameter

    :param asset: String describing an asset file.
    :param interactive: Whether to ask the user before downloading the file.
    :param restore_image: If the asset is a compressed image, we can uncompress
                          in order to restore the image.
    """
    asset_info = get_asset_info(asset)
    destination = asset_info['destination']

    if (interactive and not os.path.isfile(destination)):
        answer = utils.ask("File %s not present. Do you want to download it?" %
                           asset_info['title'])
    else:
        answer = "y"

    if answer == "y":
        download_file(asset_info=asset_info, interactive=interactive,
                      force=restore_image)
