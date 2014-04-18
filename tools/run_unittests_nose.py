#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = 'Lucas Meneghel Rodrigues <lmr@redhat.com>'

from nose.selector import Selector

from nose.plugins import Plugin
from nose.plugins.attrib import AttributeSelector
from nose.plugins.xunit import Xunit
from nose.plugins.cover import Coverage

import logging
import os
import nose
import sys


logger = logging.getLogger(__name__)


class VirtTestSelector(Selector):

    def wantDirectory(self, dirname):
        return True

    def wantModule(self, module):
        if module.__name__ == 'virttest.utils_test':
            return False
        return True

    def wantFile(self, filename):
        if not filename.endswith('_unittest.py'):
            return False

        skip_tests = []
        if self.config.options.skip_tests:
            skip_tests = self.config.options.skip_tests.split()

        if os.path.basename(filename)[:-3] in skip_tests:
            logger.debug('Skipping test: %s' % filename)
            return False

        if self.config.options.debug:
            logger.debug('Adding %s as a valid test' % filename)

        return True


class VirtTestRunner(Plugin):

    enabled = True
    name = 'virt_test_runner'

    def configure(self, options, config):
        self.result_stream = sys.stdout

        config.logStream = self.result_stream
        self.testrunner = nose.core.TextTestRunner(stream=self.result_stream,
                                                   descriptions=True,
                                                   verbosity=2,
                                                   config=config)

    def options(self, parser, env):
        parser.add_option("--virttest-skip-tests",
                          dest="skip_tests",
                          default=[],
                          help='A space separated list of tests to skip')

    def prepareTestLoader(self, loader):
        loader.selector = VirtTestSelector(loader.config)


def run_test():
    nose.main(addplugins=[VirtTestRunner(),
                          AttributeSelector(),
                          Xunit(),
                          Coverage()])


def main():
    run_test()


if __name__ == '__main__':
    main()
