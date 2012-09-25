======================================
Linux Virtualization Tests (virt-test)
======================================

Actual documentation website
----------------------------

https://github.com/autotest/virt-test/wiki

Description
-----------

virt-test is a Linux virtualization test suite, intended to be used in
conjunction with the autotest framework [1], although it can be also used
separately, on a virt developer's machine, to run tests quicker and smaller
in scope, as an auxiliary tool of the development process.

This test suite aims to have test tools for a wide range of testing scenarios:

-  Guest OS install, for both Windows (WinXP - Win7) and Linux (RHEL,
   Fedora, OpenSUSE) and any generic one, through a 'step engine' mechanism.
-  Serial output for Linux guests
-  Migration, networking, timedrift and other types of tests
-  Monitor control for both human and QMP protocols
-  Build and use qemu using various methods (source tarball, git repo,
   rpm)
-  Performance testing
-  Call other kvm test projects, such as kvm-unit-tests

We support x86\_64 hosts with hardware virtualization support (AMD and
Intel), and Intel 32 and 64 bit guest operating systems, and work is underway
to support PPC hosts.

[1] http://autotest.github.com/ - Autotest is a project that aims to
provide tools and libraries to perform automated testing on the linux
platform. Autotest is a modular framework, and this suite can be used as
a submodule of the client module. If you do not want to use or know about
autotest, this is fine too, and we'll provide documentation and tools to
perform development style testing with it.
