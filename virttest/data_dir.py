#!/usr/bin/python
"""
Library used to provide the appropriate data dir for virt test.
"""
import os, sys, tempfile, glob, logging

_ROOT_PATH = os.path.join(sys.modules[__name__].__file__, "..", "..")
ROOT_DIR = os.path.abspath(_ROOT_PATH)
DATA_DIR = os.path.join(ROOT_DIR, 'shared', 'data')
DOWNLOAD_DIR = os.path.join(ROOT_DIR, 'shared', 'downloads')
TMP_DIR = os.path.join(ROOT_DIR, 'tmp')
BACKING_DATA_DIR = None

class SubdirList(list):
    """
    List of all non-hidden subdirectories beneath basedir
    """

    def __in_filter__(self, item):
        if self.filterlist:
            for _filter in self.filterlist:
                if item.count(str(_filter)):
                    logging.info("Filtering out %s b/c matches %s", item, _filter)
                    return True
            return False
        else:
            return False


    def __set_initset__(self):
        for dirpath, dirnames, filenames in os.walk(self.basedir):
            del filenames # not used
            for _dirname in dirnames:
                if _dirname.startswith('.') or self.__in_filter__(_dirname):
                    # Don't descend into filtered or hidden directories
                    del dirnames[dirnames.index(_dirname)]
                else:
                    self.initset.add(os.path.join(dirpath, _dirname))


    def __init__(self, basedir, filterlist=None):
        self.basedir = os.path.abspath(str(basedir))
        self.initset = set([self.basedir]) # enforce unique items
        self.filterlist = filterlist
        self.__set_initset__()
        super(SubdirList, self).__init__(self.initset)


class SubdirGlobList(SubdirList):
    """
    List of all files matching glob in all non-hidden basedir subdirectories
    """

    def __initset_to_globset__(self):
        globset = set()
        for dirname in self.initset: # dirname is absolute
            pathname = os.path.join(dirname, self.globstr)
            for filepath in glob.glob(pathname):
                if not self.__in_filter__(filepath):
                    globset.add(filepath)
        self.initset = globset


    def __set_initset__(self):
        super(SubdirGlobList, self).__set_initset__()
        self.__initset_to_globset__()


    def __init__(self, basedir, globstr, filterlist=None):
        self.globstr = str(globstr)
        super(SubdirGlobList, self).__init__(basedir, filterlist)


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
    if not os.path.isdir(TMP_DIR):
        os.makedirs(TMP_DIR)
    return TMP_DIR

def get_download_dir():
    return DOWNLOAD_DIR

if __name__ == '__main__':
    print "root dir:         " + ROOT_DIR
    print "tmp dir:          " + TMP_DIR
    print "data dir:         " + DATA_DIR
    print "backing data dir: " + BACKING_DATA_DIR
