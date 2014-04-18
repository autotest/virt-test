
file\_transfer\_client
======================

Description
-----------

Sets the kind of application, thus protocol, that will be spoken when
transfering files to and from the guest.

virt-test currently allows for two options: 'scp' or 'rss'.

For Linux VMs, we default to SSH:

::

    variants:
        - @Linux:
            file_transfer_client = scp

And for Microsoft Windows VMs we default to rss:

::

    variants:
        - @Windows:
            file_transfer_client = rss

Defined On
----------

-  `client/tests/kvm/guest-os.cfg.sample <https://github.com/autotest/autotest/blob/master/client/tests/kvm/guest-os.cfg.sample>`_

Used By
-------

-  `client/virt/kvm\_vm.py <https://github.com/autotest/autotest/blob/master/client/virt/kvm_vm.py>`_

Referenced By
-------------

No other documentation currently references this configuration key.

See Also
--------

-  `redirs <redirs>`_
-  `file\_transfer\_port <file_transfer_port>`_
-  `guest\_port\_file\_transfer <guest_port_file_transfer>`_

