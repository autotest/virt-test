import os
import subprocess
from autotest.client.shared import error
from virttest import virsh


def run(test, params, env):
    """
    Test command: virsh domjobabort.

    The command can abort the currently running domain job.
    1.Prepare test environment,destroy or suspend a VM.
    2.Do action to get a subprocess(dump, save, managedsave).
    3.Perform virsh domjobabort operation to abort VM's job.
    4.Recover the VM's status and wait for the subprocess over.
    5.Confirm the test result.
    """

    vm_name = params.get("main_vm", "vm1")
    vm = env.get_vm(vm_name)
    start_vm = params.get("start_vm")
    pre_vm_state = params.get("pre_vm_state", "start")
    if start_vm == "no" and vm.is_alive():
        vm.destroy()

    # Instead of "paused_after_start_vm", use "pre_vm_state".
    # After start the VM, wait for some time to make sure the job
    # can be created on this domain.
    if start_vm == "yes":
        vm.wait_for_login()
        if params.get("pre_vm_state") == "suspend":
            vm.pause()

    domid = vm.get_id()
    domuuid = vm.get_uuid()

    def get_subprocess(action, vm_name, file):
        """
        Execute background virsh command, return subprocess w/o waiting for exit()

        :param cmd : virsh command.
        :param guest_name : VM's name
        :param file_source : virsh command's file option.
        """
        if action == "managedsave":
            file = ""
        command = "virsh %s %s %s" % (action, vm_name, file)
        p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        return p

    action = params.get("jobabort_action", "dump")
    status_error = params.get("status_error", "no")
    job = params.get("jobabort_job", "yes")
    tmp_file = os.path.join(test.tmpdir, "domjobabort.tmp")
    tmp_pipe = os.path.join(test.tmpdir, "domjobabort.fifo")
    vm_ref = params.get("jobabort_vm_ref")
    saved_data = None

    if action == "managedsave":
        tmp_pipe = '/var/lib/libvirt/qemu/save/%s.save' % vm.name

    if action == "restore":
        virsh.save(vm_name, tmp_file, ignore_status=True)

    if vm_ref == "id":
        vm_ref = domid
    elif vm_ref == "hex_id":
        vm_ref = hex(int(domid))
    elif vm_ref == "uuid":
        vm_ref = domuuid
    elif vm_ref.find("invalid") != -1:
        vm_ref = params.get(vm_ref)
    elif vm_ref == "name":
        vm_ref = vm_name

    # Get the subprocess of VM.
    # The command's effect is to abort the currently running domain job.
    # So before do "domjobabort" action, we must create a job on the domain.
    process = None
    if job == "yes" and start_vm == "yes" and status_error == "no":
        if os.path.exists(tmp_pipe):
            os.unlink(tmp_pipe)
        os.mkfifo(tmp_pipe)

        process = get_subprocess(action, vm_name, tmp_pipe)

        saved_data = None
        if action == "restore":
            saved_data = file(tmp_file, 'r').read(10 * 1024 * 1024)
            f = open(tmp_pipe, 'w')
            f.write(saved_data[:1024 * 1024])
        else:
            f = open(tmp_pipe, 'r')
            dummy = f.read(1024 * 1024)

    ret = virsh.domjobabort(vm_ref, ignore_status=True)
    status = ret.exit_status

    if process:
        if saved_data:
            f.write(saved_data[1024 * 1024:])
        else:
            dummy = f.read()
        f.close()

        if os.path.exists(tmp_pipe):
            os.unlink(tmp_pipe)
        if os.path.exists(tmp_file):
            os.unlink(tmp_file)

    # Recover the environment.
    if pre_vm_state == "suspend":
        vm.resume()
    if process:
        if process.poll():
            try:
                process.kill()
            except OSError:
                pass

    # check status_error
    if status_error == "yes":
        if status == 0:
            raise error.TestFail("Run successfully with wrong command!")
    elif status_error == "no":
        if status != 0:
            raise error.TestFail("Run failed with right command")
