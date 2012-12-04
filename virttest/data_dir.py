#!/usr/bin/python
"""
Library used to provide the appropriate data dir for virt test.
"""
import os, sys, tempfile

_ROOT_PATH = os.path.join(sys.modules[__name__].__file__, "..", "..")
ROOT_DIR = os.path.abspath(_ROOT_PATH)
DATA_DIR = os.path.join(ROOT_DIR, 'shared', 'data')
TMP_DIR = os.path.join(ROOT_DIR, 'tmp')
BACKING_DATA_DIR = None

def get_backing_data_dir():
    if os.path.islink(DATA_DIR):
        if os.path.isdir(DATA_DIR):
            return os.readlink(DATA_DIR)
        else:
            # Invalid symlink
            os.unlink(DATA_DIR)
    elif os.path.isdir(DATA_DIR):
        return DATA_DIR

    try:
        return os.environ['VIRT_TEST_DATA_DIR']
    except KeyError:
        pass

    data_dir = '/var/lib/virt_test'
    if os.path.isdir(data_dir):
        try:
            fd, path = tempfile.mkstemp(dir=data_dir)
            os.close(fd)
            os.unlink(path)
            return data_dir
        except OSError:
            pass
    else:
        try:
            os.makedirs(data_dir)
            return data_dir
        except OSError:
            pass

    data_dir = os.path.expanduser('~/virt_test')
    if not os.path.isdir(data_dir):
        os.makedirs(data_dir)
    return os.path.realpath(data_dir)


def set_backing_data_dir(backing_data_dir):
    if os.path.islink(DATA_DIR):
        os.unlink(DATA_DIR)
    backing_data_dir = os.path.expanduser(backing_data_dir)
    if not os.path.isdir(backing_data_dir):
        os.makedirs(backing_data_dir)
    if not backing_data_dir == DATA_DIR:
        os.symlink(backing_data_dir, DATA_DIR)

BACKING_DATA_DIR = get_backing_data_dir()
set_backing_data_dir(BACKING_DATA_DIR)

def get_root_dir():
    return ROOT_DIR

def get_data_dir():
    return DATA_DIR

def get_tmp_dir():
    return TMP_DIR

if __name__ == '__main__':
    print "root dir:         " + ROOT_DIR
    print "tmp dir:          " + TMP_DIR
    print "data dir:         " + DATA_DIR
    print "backing data dir: " + BACKING_DATA_DIR
