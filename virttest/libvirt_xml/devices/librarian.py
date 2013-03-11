"""
Device class librarian to standardize handling across many device type classes

Always raises ValueError for bad/unknown/unsupported type names
"""

import os, imp

# Avoid accidental names like __init__, librarian, and/or other support modules
known_types = set(('disk', 'filesystem', 'address', 'controller', 'lease',
                   'hostdev', 'redirdev', 'smartcard', 'interface', 'input',
                   'hub', 'graphics', 'video', 'parallel', 'serial', 'console',
                   'channel', 'sound', 'watchdog', 'memballoon', 'rng',
                   'seclabel'))

def get(name):
        errmsg = "Unknown/unsupported type %s" % name
        if name not in known_types:
            raise ValueError(errmsg)
        mod_path = os.path.abspath(os.path.dirname(__file__))
        try:
            filename, pathname, description = imp.find_module(name, mod_path)
            modobj = imp.load_module(name, filename, pathname, description)
            # Enforce good class name style
            return getattr(modobj, name.capitalize())
        except (TypeError, ImportError, AttributeError):
            raise ValueError(errmsg)
