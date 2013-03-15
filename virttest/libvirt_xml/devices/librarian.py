"""
Device class librarian to standardize handling across many device type classes

Always raises ValueError for bad/unknown/unsupported type names
"""

import os, imp
from virttest.libvirt_xml import base, xcepts
from virttest.libvirt_xml.devices import base as device_base

# Avoid accidental names like __init__, librarian, and/or other support modules
device_types = ['disk', 'filesystem', 'controller', 'lease',
                'hostdev', 'redirdev', 'smartcard', 'interface', 'input',
                'hub', 'graphics', 'video', 'parallel', 'serial', 'console',
                'channel', 'sound', 'watchdog', 'memballoon', 'rng',
                'seclabel', 'address']


def get(name):
    # Module names and device-tags are always all lower-case
    name = str(name).lower()
    errmsg = ("Unknown/unsupported type '%s', supported types %s"
              % (str(name), device_types))
    if name not in device_types:
        raise xcepts.LibvirtXMLError(errmsg)
    mod_path = os.path.abspath(os.path.dirname(__file__))
    try:
        filename, pathname, description = imp.find_module(name,
                                                          [mod_path])
        mod_obj = imp.load_module(name, filename, pathname, description)
        # Enforce capitalized class names
        return getattr(mod_obj, name.capitalize())
    except TypeError, detail:
        raise xcepts.LibvirtXMLError(errmsg + ': %s' % str(detail))
    except ImportError, detail:
        raise xcepts.LibvirtXMLError("Can't find module %s in %s: %s"
                                     % (name, mod_path, str(detail)))
    except AttributeError, detail:
        raise xcepts.LibvirtXMLError("Can't find class %s in %s module in "
                                     "%s: %s"
                                     % (name.capitalize(), name, mod_path,
                                        str(detail)))
