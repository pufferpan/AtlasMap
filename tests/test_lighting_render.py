import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import ue_pipeline

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_lighting', ROOT/'scripts/official/map_lighting.py')
lighting = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lighting)


class LightTests(unittest.TestCase):
    def test_signed_game_intensities_and_partition_independent_identity(self):
        row={'Type':'Spot','Name':'Component','Intensity':-97500,'InnerCone':-20,
             'Source':{'level':'Map/A','object':{'ObjectPath':'Map/A.42'}}}
        alone=list(lighting.records({'lights':[row]}))[0]
        together=list(lighting.records({'lights':[{'Type':'Sky','Name':'Other'},row]}))[1]
        self.assertEqual(alone[0],together[0])
        self.assertEqual(alone[1]['intensity'],-97500)
        self.assertEqual(alone[1]['innercone'],-20)
        changed=dict(row,Source={'level':'Map/B','object':{'ObjectPath':'Map/B.42'}})
        self.assertNotEqual(alone[0],list(lighting.records({'lights':[changed]}))[0][0])
    def test_source_coordinates_zero_values_and_coincident_lights_survive(self):
        row = {'Type':'Point','Name':'Off','Loc':[123,-456,789], 'Rot':[7,-8,9],
               'Color':[.05,.2,.8], 'Intensity':0, 'Radius':0}
        records = list(lighting.records({'lights':[row,row]}))
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0][0], records[1][0])
        self.assertEqual(records[0][1]['loc'], row['Loc'])
        self.assertEqual(records[0][1]['rot'], row['Rot'])
        self.assertEqual(records[0][1]['color'], row['Color'])
        self.assertEqual(records[0][1]['intensity'], 0)
        self.assertEqual(records[0][1]['radius'], 0)
        self.assertEqual(records, list(lighting.records({'lights':[row,row]})))

    def test_invalid_source_is_reported_instead_of_silently_guessed(self):
        for row in ({'Type':'Point','Loc':[0,1]}, {'Type':'Point','Intensity':float('nan')},
                    {'Type':'Unknown'}, {'Type':'Spot','Radius':-1}):
            with self.subTest(row=row), self.assertRaises(ValueError):
                list(lighting.records({'lights':[row]}))

    def test_preview_uses_gpu_native_renderer_and_current_map_identity(self):
        p = {'root':'G:/Export/Test','scripts':'G:/path with spaces/scripts',
             'engine':'E:/UE/UnrealEditor.exe','project':'G:/test/My Project.uproject',
             'dest':'/Game/AtlasMaps/Test'}
        step = ue_pipeline.render_step(p)
        self.assertIn('-RenderOffscreen', step.cmd)
        self.assertNotIn('-nullrhi', step.cmd)
        self.assertEqual(step.env['ATLASMAP_UE_LEVEL'],'/Game/AtlasMaps/Test/LV_Map')
        self.assertEqual(step.env['ATLASMAP_LIGHTING_MODE'],'source')
        self.assertEqual(step.env['ATLASMAP_SCRIPTS'],p['scripts'])
        # UE splits ExecCmds on commas; embedded double quotes are truncated.
        command = next(a for a in step.cmd if a.startswith('-ExecCmds='))
        self.assertNotIn('"',command)
        self.assertNotIn(',',command)


class WizardPathsTests(unittest.TestCase):
    def test_model_style_wizard_writes_map_settings_only(self):
        from app import wizard
        with tempfile.TemporaryDirectory() as folder:
            paks = Path(folder)/'DeltaForce/Content/Paks'
            paks.mkdir(parents=True)
            (paks/'test.pak').touch()
            saved = {'ue_map':'SafeHouse', 'outdir':'G:/Exports'}
            with patch.object(wizard.exporter,'load_settings',return_value=dict(saved)), \
                 patch.object(wizard.exporter,'save_settings') as save, \
                 patch.object(wizard.exporter,'write_exporter_config') as config:
                wizard.L.set_game_root(folder)
                result = save.call_args.args[0]
                self.assertEqual(result['ue_map'],'SafeHouse')
                self.assertEqual(result['outdir'],'G:/Exports')
                self.assertEqual(result['paks'],str(paks).replace('\\','/'))
                config.assert_called_once_with(result)
            cfg = Path(folder)/'settings.json'
            cfg.write_text(json.dumps(saved))
            with patch.object(wizard,'CONFIG',str(cfg)):
                wizard.mark_done()
            result = json.loads(cfg.read_text())
            self.assertTrue(result['wizard_done'])
            self.assertEqual(result['ue_map'],'SafeHouse')

