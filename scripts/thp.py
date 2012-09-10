#!/usr/bin/python
# -*- coding: utf-8 -*-
import os, sys, time, commands, string, re, stat, shelve, random

"""
script to save and restore environment in transparent hugepage test
and khuagepaged test
"""

class THPError(Exception):
    """
    Exception from transparent hugepage preparing scripts
    """
    pass

class THP:
    def __init__(self):
        """
        Get the configuration path of transparent hugepage, ksm,
        libhugetlbfs and etc. And the option config parameters from user
        """
        if os.path.isdir("/sys/kernel/mm/redhat_transparent_hugepage"):
            self.thp_path = '/sys/kernel/mm/redhat_transparent_hugepage'
        elif os.path.isdir("/sys/kernel/mm/transparent_hugepage"):
            self.thp_path = '/sys/kernel/mm/transparent_hugepage'
        else:
            raise THPError("System don't support transparent hugepage")

        self.default_config_file = '/tmp/thp_default_config'
        # Update the test config dict from environment
        tmp_list = []
        test_cfg = {}
        test_config = str(os.environ['KVM_TEST_thp_test_config'])
        if len(test_config) > 0:
            tmp_list = re.split(';', test_config)
        while len(tmp_list) > 0:
            tmp_cfg = tmp_list.pop()
            test_cfg[re.split(":", tmp_cfg)[0]] = \
                                           re.split(":", tmp_cfg)[1]
        self.test_config = test_cfg

    def file_writeable(self, file_name):
        """
        Check if the file is writeable
        """
        s, o = commands.getstatusoutput("ls -l %s" % file_name)
        if s != 0:
            raise THPError("Can not get the access string of %s: %s" %\
                          (file_name, o))
        if re.findall("w", o[0:10]):
            return True
        return False

    def save_env(self):
        """
        Save and set the environment including related parts in kernel.
        Such as ksm and libhugetlbfs.
        """
        fd_default = shelve.open(str(self.default_config_file))
        file_list_str = []
        file_list_num = []
        for f in os.walk(self.thp_path):
            base_dir = f[0]
            if f[2]:
                for name in f[2]:
                    f_dir = os.path.join(base_dir, name)
                    parameter = file(f_dir, 'r').read()
                    if self.file_writeable(f_dir):
                        if re.findall("\[(.*)\]", parameter):
                            fd_default[f_dir] = re.findall("\[(.*)\]",
                                                           parameter)[0]
                            file_list_str.append(f_dir)
                        else:
                            fd_default[f_dir] = int(parameter)
                            file_list_num.append(f_dir)
        fd_default.close()
        
        return file_list_str, file_list_num

    def set_env(self):
        """
        After khugepaged test inuse_config is already set to an active mode of
        transparent hugepage. Get some special config of sub test and set it.
        """
        if len(self.test_config) > 0:
            for path in self.test_config.keys():
                file(path, 'w').write(self.test_config[path])


    def value_listed(self, value):
        """
        Get a parameters list from a string
        """
        value_list = []
        for i in re.split("\[|\]|\n+|\s+", value):
            if i:
                value_list.append(i)
        return value_list

    def khugepaged_test(self, file_list_str, file_list_num):
        """
        Start, stop and frequency change test for khugepaged
        """
        def check_status_with_value(action_list, file_name):
            """
            Check the status of khugepaged when set value to specify file
            """
            # ret is the (status, value)
            ret = [open(file_name, "w").write(a) or\
                   commands.getstatusoutput('pgrep khugepaged') \
                   for (a, r) in action_list]
            for i in range(len(action_list)):
                if ret[i][0] != action_list[i][1]:
                    raise THPError("khugepaged can not set to status %s" %\
                            action_list[i][0])

        for file_path in file_list_str:
            action_list = []
            if re.findall("enabled", file_path):
                # Start and stop test for khugepaged
                value_list = self.value_listed(open(file_path,"r").read())
                for i in value_list:
                    if re.match("n", i, re.I):
                        action_stop = (i, 256)
                for i in value_list:
                    if re.match("[^n]", i, re.I):
                        action = (i, 0)
                        action_list += [action_stop, action, action_stop]
                action_list += [action]
                check_status_with_value(action_list, file_path)
            else:
                value_list = self.value_listed(open(file_path,"r").read())
                for i in value_list:
                    action = (i, 0)
                    action_list.append(action)
                check_status_with_value(action_list, file_path)

        for file_path in file_list_num:
            action_list = []
            value = int(open(file_path, "r").read())
            if value != 0:
                new_value = random.random()
                action_list.append((str(int(value * new_value)),0))
                action_list.append((str(int(value * ( new_value + 1))),0))
            check_status_with_value(action_list, file_path)


    def restore_default_config(self):
        """:
        Restore the default configuration to host after test
        """
        fd = shelve.open(self.default_config_file)
        for path in fd.keys():
            file(path, 'w').write(str(fd[path]))
        fd.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise THPError("Please use -s for set and -r for restore")

    run_time = sys.argv[1][1:]
    trans_hugepage = THP()
    if run_time == "s":
        files_str, files_num = trans_hugepage.save_env()
        trans_hugepage.khugepaged_test(files_str, files_num)
        trans_hugepage.set_env()
    elif run_time == "r":
        trans_hugepage.restore_default_config()
    else:
        raise THPError("Please use -s for set and -r for restore")
