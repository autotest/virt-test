#!/usr/bin/python
import unittest
import os
import tempfile
import shutil

import common
import utils_conn
import data_dir


class UtilsConnTest(unittest.TestCase):

    def test_connbase(self):
        connbase = utils_conn.ConnectionBase()
        self.assertRaises(utils_conn.ConnNotImplementedError,
                          connbase.conn_setup)
        self.assertRaises(utils_conn.ConnNotImplementedError,
                          connbase.conn_check)
        self.assertRaises(utils_conn.ConnNotImplementedError,
                          connbase.conn_recover)

        self.assertRaises(utils_conn.ConnForbiddenError,
                          connbase.set_server_session, None)
        self.assertRaises(utils_conn.ConnForbiddenError,
                          connbase.set_client_session, None)

        self.assertRaises(utils_conn.ConnForbiddenError,
                          connbase.del_server_session)
        self.assertRaises(utils_conn.ConnForbiddenError,
                          connbase.del_client_session)

        self.assertIsNotNone(connbase.tmp_dir)
        tmp_dir = connbase.tmp_dir

        self.assertTrue(os.path.isdir(tmp_dir))
        del connbase
        self.assertFalse(os.path.isdir(tmp_dir))

    def test_tmp_dir(self):
        conn_1 = utils_conn.ConnectionBase()
        tmp_dir_1 = conn_1.tmp_dir
        conn_2 = utils_conn.ConnectionBase()
        tmp_dir_2 = conn_2.tmp_dir

        self.assertTrue(os.path.isdir(tmp_dir_1))
        self.assertTrue(os.path.isdir(tmp_dir_2))
        self.assertFalse(tmp_dir_1 == tmp_dir_2)
        del conn_1
        del conn_2
        self.assertFalse(os.path.isdir(tmp_dir_1))
        self.assertFalse(os.path.isdir(tmp_dir_2))

    def test_CA(self):
        tmp_dir = tempfile.mkdtemp(dir=data_dir.get_tmp_dir())

        cakey_path = '%s/tcakey.pem' % tmp_dir
        cainfo_path = '%s/ca.info' % tmp_dir
        cacert_path = '%s/cacert.pem' % tmp_dir

        utils_conn.build_CA(tmp_dir)
        self.assertTrue(os.path.exists(cakey_path))
        self.assertTrue(os.path.exists(cainfo_path))
        self.assertTrue(os.path.exists(cacert_path))

        expect_info = ["cn = AUTOTEST.VIRT\n",
                       "ca\n",
                       "cert_signing_key\n"]
        info_file = open(cainfo_path)
        lines = info_file.readlines()
        self.assertEqual(expect_info, lines)
        shutil.rmtree(tmp_dir)

    def test_client_key(self):
        tmp_dir = tempfile.mkdtemp(dir=data_dir.get_tmp_dir())

        utils_conn.build_CA(tmp_dir)

        clientkey_path = '%s/clientkey.pem' % tmp_dir
        clientcert_path = '%s/clientcert.pem' % tmp_dir
        clientinfo_path = '%s/client.info' % tmp_dir

        utils_conn.build_client_key(tmp_dir)
        self.assertTrue(os.path.exists(clientkey_path))
        self.assertTrue(os.path.exists(clientcert_path))
        self.assertTrue(os.path.exists(clientinfo_path))

        expect_info = ["organization = AUTOTEST.VIRT\n",
                       "cn = TLSClient\n",
                       "tls_www_client\n",
                       "encryption_key\n",
                       "signing_key\n"]
        info_file = open(clientinfo_path)
        lines = info_file.readlines()
        self.assertEqual(expect_info, lines)

        shutil.rmtree(tmp_dir)

    def test_server_key(self):
        tmp_dir = tempfile.mkdtemp(dir=data_dir.get_tmp_dir())

        utils_conn.build_CA(tmp_dir)

        serverkey_path = '%s/serverkey.pem' % tmp_dir
        servercert_path = '%s/servercert.pem' % tmp_dir
        serverinfo_path = '%s/server.info' % tmp_dir

        utils_conn.build_server_key(tmp_dir)
        self.assertTrue(os.path.exists(serverkey_path))
        self.assertTrue(os.path.exists(servercert_path))
        self.assertTrue(os.path.exists(serverinfo_path))

        expect_info = ["organization = AUTOTEST.VIRT\n",
                       "cn = TLSServer\n",
                       "tls_www_server\n",
                       "encryption_key\n",
                       "signing_key\n"]
        info_file = open(serverinfo_path)
        lines = info_file.readlines()
        self.assertEqual(expect_info, lines)

        shutil.rmtree(tmp_dir)

if __name__ == "__main__":
    unittest.main()
