from autotest.client.shared import error


@error.context_aware
def run(test, params, env):
    """
    everything is done by client.virt module
    """
    pass
