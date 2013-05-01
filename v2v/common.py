import os, sys
try:
    import autotest.client.setup_modules as setup_modules
    client_dir = os.path.dirname(setup_modules.__file__)
except ImportError:
    dirname = os.path.dirname(sys.modules[__name__].__file__)
    client_dir = os.path.abspath(os.path.join(dirname, "..", "..", ".."))
    sys.path.insert(0, client_dir)
    import setup_modules
    sys.path.pop(0)
    virt_test_dir = os.path.abspath(os.path.join(dirname, ".."))
    sys.path.insert(0, virt_test_dir)

setup_modules.setup(base_path=client_dir,
                    root_module_name="autotest.client")
