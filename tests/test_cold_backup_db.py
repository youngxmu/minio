import unittest

from cold_backup_automation.db import parse_mysql_dsn


class DsnParsingTest(unittest.TestCase):
    def test_parse_mysql_dsn_requires_sucai_meta_database(self):
        parsed = parse_mysql_dsn("mysql://meta_user:secret@127.0.0.1:3306/sucai_meta?charset=utf8mb4")

        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(parsed["port"], 3306)
        self.assertEqual(parsed["user"], "meta_user")
        self.assertEqual(parsed["password"], "secret")
        self.assertEqual(parsed["database"], "sucai_meta")
        self.assertEqual(parsed["charset"], "utf8mb4")

    def test_parse_mysql_dsn_rejects_other_database(self):
        with self.assertRaisesRegex(ValueError, "sucai_meta"):
            parse_mysql_dsn("mysql://meta_user:secret@127.0.0.1:3306/other_meta")


if __name__ == "__main__":
    unittest.main()
