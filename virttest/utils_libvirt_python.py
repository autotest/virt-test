"""
Module to wrap functions of libvirt bindings for python.
"""
from autotest.client.shared import error

try:
    import libvirt
    libvirtError = libvirt.libvirtError
except ImportError:
    libvirt = None


def get_connect(params={}):
    """
    Get a virConnect object with libvirt.open() function.

    :param params: Dict contain connect_
    """
    if libvirt is None:
        raise error.TestNAError("Please make sure libvirt_python is already "
                                "installed.")
    # Default value for open() is "".
    connect_uri = params.get("connect_uri", "")
    if connect_uri == "default":
        connect_uri = ""
    return libvirt.open(connect_uri)


def get_domain(name, params={}):
    conn = get_connect(params)
    return conn.lookupByName(name)


def get_network(name, params={}):
    conn = get_connect(params)
    return conn.networkLookupByName(name)


def get_interface(name, params={}):
    conn = get_connect(params)
    return conn.interfaceLookupByName(name)


def get_domain_snapshot(name, params={}):
    conn = get_connect(params)
    return conn.snapshotLookupByName(name)


def get_node_device(name, params={}):
    conn = get_connect(params)
    return conn.nodeDeviceLookupByName(name)


def get_network_filter(name, params={}):
    conn = get_connect(params)
    return conn.nwfilterLookupByName(name)


def get_secret(uuid, params={}):
    conn = get_connect(params)
    return conn.secretLookupByUUIDString(str(uuid))


def get_storage_pool(name, params={}):
    conn = get_connect(params)
    return conn.storagePoolLookupByName(name)


def get_storage_vol(name, params={}):
    conn = get_connect(params)
    return conn.storageVolLookupByName(name)
