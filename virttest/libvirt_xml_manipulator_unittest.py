#!/usr/bin/env python
"""
Unit tests for Manipulator classes in libvirt_xml module.
"""
import unittest
import itertools

import common
from libvirt_xml.network_xml import NetworkXML


class NetworkXMLTest(unittest.TestCase):
    """
    Unit test class for manipulator methods in NetworkXML class.
    """
    def test_sync_and_state_dict(self):
        """
        Unit test for sync and state_dict methods of NetworkXML class.

        1) Backup current network.
        2) Traverse all possible state and call sync use the state.
        3) Check result validity.
        4) Restore network.
        """
        # Backup network.
        network_name = "default"
        try:
            backup_xml = network_xml = NetworkXML.new_from_net_dumpxml(
                network_name)
        except:
            raise unittest.SkipTest("Network %s does't exists" % network_name)
        backup_state = backup_xml.state_dict()

        #network_xml.sync()

        try:
            # Test sync without state option
            network_xml.sync()
            new_state = network_xml.state_dict()
            state = {'active': True,
                     'persistent': True,
                     'autostart': True}
            self.assertDictEqual(state, new_state)

            for values in itertools.product([True, False], repeat=3):
                # Change network to all possible states.
                keys = ['active', 'persistent', 'autostart']
                state = dict(zip(keys, values))
                network_xml.sync(state=state)

                # Check result's validity.
                new_state = network_xml.state_dict()
                # Transient network can't set autostart
                if state == {'active': True,
                             'persistent': False,
                             'autostart': True}:
                    state = {'active': True,
                             'persistent': False,
                             'autostart': False}
                # Non-exist network should return None when retieving state.
                if not state['active'] and not state['persistent']:
                    self.assertIsNone(new_state)
                else:
                    self.assertDictEqual(state, new_state)
        finally:
            # Restore network.
            backup_xml.sync(state=backup_state)

if __name__ == '__main__':
    unittest.main()
