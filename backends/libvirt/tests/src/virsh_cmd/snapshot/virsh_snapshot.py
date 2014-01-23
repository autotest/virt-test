import logging
import re
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test snapshot handling

    1) Verify that guest does not have any snapshot (snapshot-list)
    2) Create snapshot hierarchy (snapshot-create, snapshot-current)
    3) Check snapshot hierarchy (snapshot-info)
    4) Test snapshot switching (snapshot-revert)
    5) Remove all snapshots (snapshot-delete)
    """
    def remove_snapshots(vm):
        remove_failed = 0
        snaps = virsh.snapshot_list(vm)
        for snap in snaps:
            try:
                virsh.snapshot_delete(vm, snap)
            except error.CmdError:
                logging.debug("Can not remove snapshot %s.", snaps)
                remove_failed = remove_failed + 1

        return remove_failed

    def test_file(session, filename, result):
        if filename is None:
            return
        cmd = "ls %s" % filename
        rv = session.cmd_status(cmd)
        if rv != result:
            raise error.TestFail("Failed file existence test - %s" % filename)

    def handle_error(errorstr, vm):
        rf = remove_snapshots(vm)
        if rf == 0:
            raise error.TestFail(errorstr)
        else:
            raise error.TestFail("%s (Failed to remove %d snapshots)"
                                 % (errorstr, rf))

    def normalize_state(domstate):
        if domstate in ["offline", "shutoff", "shut off"]:
            return "shutoff"
        elif domstate in ["online", "running"]:
            return "running"
        elif domstate in ["paused"]:
            return "paused"
        else:
            return domstate

    def check_info(i1, i2, errorstr="Values differ"):
        if normalize_state(i1) != normalize_state(i2):
            error.TestFail("%s (%s != %s)" % (errorstr, i1, i2))

    vm_name = params.get("main_vm")
    offline = (params.get("snapshot_shutdown", "no") == "yes")
    vm = env.get_vm(vm_name)
    snapshot_halt = ("yes" == params.get("snapshot_halt", "no"))

    logging.info("Verify that no snapshot exist for %s", vm_name)

    snl = virsh.snapshot_list(vm_name)
    if len(snl) != 0:
        if bool(remove_snapshots(vm_name)):
            raise error.TestFail("Snapshot on guest can not be removed.")

    logging.info("Create snapshot hierarchy for %s", vm_name)
    snapshot_info = [{"Domain": vm_name, "State": normalize_state("running"),
                      "Children": "1", "Descendants": "3", "to_create": None,
                      "to_delete": None},
                     {"Domain": vm_name, "State": normalize_state("paused"),
                      "Children": "1", "Descendants": "2",
                      "to_create": "/root/sn1", "to_delete": None},
                     {"Domain": vm_name, "State": normalize_state("running"),
                      "Children": "1", "Descendants": "1",
                      "to_create": "/root/sn2", "to_delete": None},
                     {"Domain": vm_name, "State": normalize_state("paused"),
                      "Children": "0", "Descendants": "0", "to_create": None,
                      "to_delete": "/root/sn1"}]
    last_snapshot = None
    options = ""
    if snapshot_halt:
        options += " --halt"
    for sni in snapshot_info:
        sni["Parent"] = last_snapshot
        session = vm.wait_for_login()
        if sni["to_create"] is not None:
            session.cmd("touch %s" % sni["to_create"])
        if sni["to_delete"] is not None:
            session.cmd("rm -rf %s" % sni["to_delete"])
        if offline:
            sni["State"] = normalize_state("shutoff")
            vm.shutdown()
        elif sni["State"] == normalize_state("paused"):
            vm.pause()

        snapshot_result = virsh.snapshot_create(vm_name, options)
        if snapshot_result.exit_status:
            raise error.TestFail("Failed to create snapshot. Error:%s."
                                 % snapshot_result.stderr.strip())
        if ((snapshot_halt) and (not vm.is_dead())):
            raise error.TestFail("VM is not dead after virsh.snapshot_create"
                                 "with '--halt'")
        if snapshot_halt:
            vm.start()
        last_snapshot = re.search(
            "\d+", snapshot_result.stdout.strip()).group(0)
        sni["Name"] = last_snapshot

        if sni["State"] == normalize_state("paused"):
            vm.resume()
        elif sni["State"] == normalize_state("shutoff"):
            vm.start()
        session.close()
        logging.info("Snapshot %s created" % last_snapshot)

    logging.info("Check snapshot hierarchy")
    for sni in snapshot_info:
        try:
            infos = virsh.snapshot_info(vm_name, sni["Name"])
            check_info(infos["Name"], sni["Name"], "Incorrect snapshot name")
            check_info(infos["Domain"], sni["Domain"], "Incorrect domain name")
            check_info(infos["State"], sni[
                       "State"], "Incorrect snapshot state")
            check_info(infos["Parent"], sni["Parent"],
                       "Incorrect snapshot parent")
            check_info(infos["Children"], sni["Children"],
                       "Incorrect children count")
            check_info(infos["Descendants"], sni["Descendants"],
                       "Incorrect descendants count")

        except error.CmdError:
            handle_error("Failed getting snapshots info", vm_name)
        except error.TestFail, e:
            handle_error(str(e), vm_name)
        logging.info("Snapshot %s verified", sni["Name"])

    logging.info("Test snapshot switching")
    for sni in snapshot_info:
        try:
            # Assure VM is shut off before revert.
            virsh.destroy(vm_name)
            result = virsh.snapshot_revert(vm_name, sni["Name"])
            if result.exit_status:
                raise error.TestFail("Snapshot revert failed.\n"
                                     "Error: %s." % result.stderr)
            state = normalize_state(virsh.domstate(vm_name).stdout.strip())
            if state != sni["State"]:
                raise error.TestFail("Incorrect state after revert - %s"
                                     % (sni["Name"]))
            if state == normalize_state('shutoff'):
                vm.start()
            elif state == normalize_state('paused'):
                vm.resume()

            session = vm.wait_for_login()
            test_file(session, sni["to_create"], 0)
            test_file(session, sni["to_delete"], 2)
        except error.CmdError:
            handle_error("Failed to revert snapshot", vm_name)
        except error.TestFail, e:
            handle_error(str(e), vm_name)
        logging.info("Snapshot %s successfully reverted", sni["Name"])

    logging.info("Remove all snapshots")
    rf = remove_snapshots(vm_name)
    if rf != 0:
        error.TestFail("Failed to remove %d snapshots" % rf)
