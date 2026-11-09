import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from core import activation
from tools.activation_owner import issue


IDENTITY='2f62e140-041a-4647-94ca-22ef559c8c33'
OTHER='bfbd6541-a5d7-44f3-8c73-f4e0bb2695b6'


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate()
        self.public=self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.machine=activation.machine_code(IDENTITY)

    def test_machine_code_stable_and_normalizes_copy_whitespace(self):
        self.assertEqual(self.machine,activation.machine_code('{'+IDENTITY.upper()+'}'))
        self.assertEqual(self.machine,activation.normalize_machine(' \n'+self.machine.lower()+'\n'))
        self.assertNotEqual(self.machine,activation.machine_code(OTHER))
        self.assertNotIn(IDENTITY,self.machine)
        with self.assertRaises(activation.ActivationError):activation.normalize_machine(self.machine[:-1]+'Z')
        with self.assertRaises(activation.ActivationError):activation.machine_code('')

    def test_signed_license_only_accepts_its_machine_and_key(self):
        token=issue(self.key,self.machine,0)
        self.assertEqual(activation.verify(token,self.machine,self.public)['machine'],self.machine)
        with self.assertRaisesRegex(activation.ActivationError,'本机'):
            activation.verify(token,activation.machine_code(OTHER),self.public)
        other=Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        with self.assertRaises(activation.ActivationError):activation.verify(token,self.machine,other)

    def test_tampered_claims_signature_and_invalid_formats_are_rejected(self):
        token=issue(self.key,self.machine);prefix,payload,signature=token.split('.')
        claims=json.loads(activation.unb64(payload));claims['machine']=activation.machine_code(OTHER)
        modified=prefix+'.'+activation.b64(activation.canonical(claims))+'.'+signature
        for invalid in ('',token+'.extra','DFMA1.!.$',modified,token[:-20],token+'A','X'*5000):
            with self.subTest(invalid=invalid[:20]),self.assertRaises(activation.ActivationError):
                activation.verify(invalid,self.machine,self.public)

    def test_signed_but_incompatible_or_noncanonical_claims_are_rejected(self):
        for payload in (b'[]',b'{"v":1}',json.dumps(dict(v=1,machine=self.machine,product=activation.PRODUCT,issued_at=1)).encode()):
            token='DFMA1.'+activation.b64(payload)+'.'+activation.b64(self.key.sign(activation.DOMAIN+payload))
            with self.assertRaises(activation.ActivationError):activation.verify(token,self.machine,self.public)

    def test_save_reload_corruption_wrong_machine_and_invalid_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'activation.json';token=issue(self.key,self.machine)
            self.assertEqual(activation.saved_license(self.machine,self.public,path),(False,''))
            activation.save_license(token,self.machine,self.public,path)
            self.assertTrue(activation.saved_license(self.machine,self.public,path)[0])
            with self.assertRaises(activation.ActivationError):activation.save_license('bad',self.machine,self.public,path)
            self.assertTrue(activation.saved_license(self.machine,self.public,path)[0])
            self.assertFalse(activation.saved_license(activation.machine_code(OTHER),self.public,path)[0])
            path.write_text('damaged');self.assertFalse(activation.saved_license(self.machine,self.public,path)[0])

    def test_packaged_public_configuration_is_valid_and_has_no_private_material(self):
        config=activation.public_config()
        self.assertEqual(len(activation.unb64(config['public_key'])),32)
        self.assertEqual(set(config),{'algorithm','public_key','issuer_url'})


class ActivationUiTests(unittest.TestCase):
    setUp=ActivationTests.setUp
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def dialog(self):
        from app.activation import activation_dialog
        return activation_dialog(self.machine,dict(public_key=activation.b64(self.public),issuer_url='https://example.com'))

    def test_native_controls_and_failed_code_keep_gate_open(self):
        from fluentpy import widgets as W
        dialog=self.dialog();self.addCleanup(dialog.deleteLater)
        self.assertIs(type(dialog),W.FramelessDialog)
        self.assertIs(type(dialog.machine_edit),W.LineEdit)
        self.assertFalse(dialog.machine_edit._show_clear_button)
        self.assertEqual(dialog.machine_edit.cursorPosition(),0)
        self.assertIs(type(dialog.code_edit),W.TextEdit)
        self.assertIs(type(dialog.copy_button),W.Button)
        self.assertIs(type(dialog.notice),W.InfoBar)
        self.assertFalse(dialog.yes_button.isEnabled())
        dialog.code_edit.setPlainText('bad');dialog.yes_button.click()
        self.assertEqual(dialog.result(),0);self.assertTrue(dialog.notice.detail())
        dialog.copy_button.click();self.assertEqual(self.app.clipboard().text(),self.machine)

    def test_valid_activation_saves_before_accepting_dialog(self):
        dialog=self.dialog();self.addCleanup(dialog.deleteLater)
        with tempfile.TemporaryDirectory() as directory,patch.object(activation,'license_path',return_value=Path(directory)/'activation.json'):
            dialog.code_edit.setPlainText(issue(self.key,self.machine));dialog.yes_button.click()
            self.assertEqual(dialog.result(),dialog.DialogCode.Accepted)
            self.assertTrue(activation.saved_license(self.machine,self.public)[0])

    def test_gate_only_skips_dialog_for_verified_saved_license(self):
        from app.activation import require_activation
        config=dict(public_key=activation.b64(self.public),issuer_url='https://example.com')
        with tempfile.TemporaryDirectory() as directory,patch.object(activation,'license_path',return_value=Path(directory)/'activation.json'),\
                patch.object(activation,'machine_code',return_value=self.machine),patch.object(activation,'public_config',return_value=config),\
                patch('app.activation.activation_dialog') as factory:
            factory.return_value.exec.return_value=0;factory.return_value.DialogCode.Accepted=1
            self.assertFalse(require_activation());factory.assert_called_once();factory.reset_mock()
            activation.save_license(issue(self.key,self.machine),self.machine,self.public)
            self.assertTrue(require_activation());factory.assert_not_called()

    def test_gate_precedes_main_window_and_environment_shortcuts(self):
        import inspect
        from app.__main__ import run
        source=inspect.getsource(run)
        gate=source.index('if not require_activation()')
        self.assertLess(gate,source.index('from app.main_window import MapViewerWindow'))
        self.assertLess(gate,source.index('ATLASMAP_SELF_TEST_OUTPUT'))
        self.assertLess(gate,source.index('ATLASMAP_NOSPLASH'))
