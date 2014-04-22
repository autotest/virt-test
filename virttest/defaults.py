DEFAULT_MACHINE_TYPE = "i440fx"
DEFAULT_GUEST_OS = "JeOS.19"

def get_default_guest_os_info():
    """
    Gets the default asset and variant information depending on host OS
    """
    os_info = {'asset': 'jeos-19-64', 'variant': DEFAULT_GUEST_OS}

    from autotest.client import utils

    issue_contents = utils.read_file('/etc/issue')
    if 'Fedora' in issue_contents and '20' in issue_contents:
        os_info = {'asset': 'jeos-20-64', 'variant': 'JeOS.20'}

    return os_info

