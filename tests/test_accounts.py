import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('accounts',ROOT/'bin/accounts.py')
accounts=importlib.util.module_from_spec(spec);spec.loader.exec_module(accounts)


class AccountsTest(unittest.TestCase):
    def test_registry_has_only_the_existing_two_credentials_and_private_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state/accounts.json';data=accounts.ensure(path)
            self.assertEqual(set(data['accounts']),{'primary','token'})
            self.assertEqual(data['accounts']['primary']['label'],'main')
            self.assertEqual(data['accounts']['token']['label'],'backup')
            self.assertTrue(data['auto_return']);self.assertEqual(path.stat().st_mode & 0o777,0o600)
            data['accounts']['token']['label']='secondary';accounts.save(data,path)
            self.assertEqual(accounts.ensure(path)['accounts']['token']['label'],'secondary')

    def test_labels_cannot_contain_credentials_controls_or_duplicate_names(self):
        for value in ['sk-'+'example','name\ncommand','x'*65,'main']:
            data=accounts.defaults();data['accounts']['token']['label']=value
            with self.assertRaises(ValueError):accounts.validate(data)
        data=accounts.defaults();data['accounts']['third']=data['accounts']['token']
        with self.assertRaises(ValueError):accounts.validate(data)
        data=accounts.defaults();data['accounts']['token']['credential']='unrecognized'
        with self.assertRaises(ValueError):accounts.validate(data)

    def test_disabling_auto_return_preserves_labels_and_authentication_references(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'accounts.json';data=accounts.defaults();data['auto_return']=False
            data['accounts']['primary']['label']='my main';accounts.save(data,path)
            restored=accounts.load(path)
            self.assertFalse(restored['auto_return']);self.assertEqual(restored['accounts']['primary']['label'],'my main')
            self.assertNotIn('secret',json.dumps(restored))

    def test_owned_accounts_precede_retained_backups_and_temporary_choice_expires(self):
        data=accounts.use_owned(accounts.defaults())
        self.assertEqual(data['priority'],['primary','secondary','token','token-last'])
        self.assertEqual(accounts.keychain_account(data,'primary'),'primary-token')
        self.assertEqual(accounts.keychain_account(data,'secondary'),'secondary-token')
        self.assertEqual(accounts.keychain_account(data,'token'),'lab')
        self.assertEqual(accounts.keychain_account(data,'token-last'),'backup-last')
        data['availability']={'primary':400,'secondary':800}
        data['temporary']={'source':'token-last','until':'1970-01-01T00:06:40+00:00'}
        self.assertEqual(accounts.initial_source(data,100),'token-last')
        self.assertEqual(accounts.initial_source(data,400),'primary')
        data['availability']['token-last']=300
        self.assertEqual(accounts.initial_source(data,200),'token')

    def test_old_registry_migrates_without_changing_the_saved_login_or_labels(self):
        old={'schema':1,'auto_return':True,'retry_delay_seconds':300,'accounts':accounts.defaults()['accounts']}
        data=accounts.validate(old)
        self.assertEqual(data['schema'],2);self.assertIsNone(accounts.keychain_account(data,'primary'))
        self.assertEqual(data['accounts']['token']['label'],'backup')
        self.assertIsNone(data['temporary'])
        with self.assertRaises(ValueError):accounts.epoch('2026-10-15T10:00:00')
        data['temporary']={'source':'unconfigured','until':'2026-10-15T10:00:00-04:00'}
        with self.assertRaises(ValueError):accounts.validate(data)
