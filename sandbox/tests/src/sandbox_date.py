import logging, datetime
from autotest.client.shared import error, utils

def run_sandbox_date(test, params, env):
    cmdresult = utils.run('virt-sandbox -c lxc:/// -- /usr/bin/date +%s')
    test_dt = datetime.datetime.fromtimestamp(float(cmdresult.stdout))
    local_dt = datetime.datetime.now()
    delta = local_dt - test_dt
    if delta.days < 0:
        delta = test_dt - local_dt
    tenseconds = datetime.timedelta(seconds=5)
    if delta > tenseconds:
        raise error.TestFail("Time difference greater than %s" % tenseconds)
