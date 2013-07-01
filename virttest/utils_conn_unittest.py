#!/usr/bin/python
import common, unittest, os
import utils_conn

class UtilsConnTestBase(unittest.TestCase):
    pass

class UtilsConnTest(UtilsConnTestBase):
    def test_connbase(self):
        connbase = utils_conn.ConnectionBase()
        self.assertRaises(utils_conn.ConnNotImplementedError,
                                            connbase.conn_setup)
        self.assertRaises(utils_conn.ConnNotImplementedError,
                                            connbase.conn_check)
        self.assertRaises(utils_conn.ConnNotImplementedError,
                                            connbase.conn_finish)

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


if __name__ == "__main__":
    unittest.main()
