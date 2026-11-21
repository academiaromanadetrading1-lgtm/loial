"""Wallet tokens must not be derivable from a public enrollment QR.

Only ephemeral in-memory SQLite and synthetic wallets; no external services.
"""
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from loial_inbox import InboxBase, WalletInboxAccess, issue_wallet_access, access_hash

class WalletPrivateAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine("sqlite+pysqlite:///:memory:")
        InboxBase.metadata.create_all(self.engine)
        self.db=Session(self.engine)
    def tearDown(self):
        self.db.close()
        self.engine.dispose()
    def test_new_wallet_secret_is_hash_only(self):
        token=issue_wallet_access(self.db,"wallet-100",True)
        self.db.commit()
        self.assertTrue(40<=len(token)<=180)
        record=self.db.query(WalletInboxAccess).one()
        self.assertNotEqual(record.token_hash,token)
        self.assertEqual(record.token_hash,access_hash(token))
        self.assertNotIn(token,str(record.__dict__))
    def test_public_wallet_identifier_cannot_reissue_secret(self):
        token=issue_wallet_access(self.db,"wallet-100",True)
        self.db.commit()
        self.assertIsNone(issue_wallet_access(self.db,"wallet-100",False))
        self.assertIsNone(issue_wallet_access(self.db,"wallet-100",True))
        self.assertEqual(issue_wallet_access(self.db,"wallet-100",False,token),token)
    def test_two_wallets_get_independent_credentials(self):
        first=issue_wallet_access(self.db,"wallet-100",True)
        second=issue_wallet_access(self.db,"wallet-200",True)
        self.db.commit()
        self.assertNotEqual(first,second)
        self.assertIsNone(issue_wallet_access(self.db,"wallet-100",False,second))
        self.assertIsNone(issue_wallet_access(self.db,"wallet-200",False,first))
    def test_unenrolled_wallet_never_issues_token(self):
        self.assertIsNone(issue_wallet_access(self.db,"wallet-public-qr",False))
        self.assertEqual(self.db.query(WalletInboxAccess).count(),0)
    def test_invalid_device_tokens_rejected(self):
        for token in ("short"," ","not-really-random","x"*181):
            with self.subTest(length=len(token)),self.assertRaises(ValueError):
                issue_wallet_access(self.db,"wallet-100",True,token)
        self.assertEqual(self.db.query(WalletInboxAccess).count(),0)
if __name__=="__main__":
    unittest.main()
