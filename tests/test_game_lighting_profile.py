import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.official.map_game_lighting import build_profile
from core import ue_pipeline


class GameLightingTests(unittest.TestCase):
    def data(self):
        return {'mapRoot':'DeltaForce/Content/Maps/CollectionRoom/', 'postprocess':[]}

    def test_profile_is_explicit_and_does_not_modify_source(self):
        source=self.data();before=copy.deepcopy(source)
        profile=build_profile(source)
        self.assertEqual(source,before)
        self.assertTrue(profile['enabled'])
        self.assertEqual(profile['map'],'CollectionRoom')
        self.assertLess(profile['fog_only_scattering_cap'],1)
        self.assertIn('not a recovered game shader',profile['basis'])

    def test_authored_exposure_is_preserved(self):
        source=self.data()
        source['postprocess']=[{'properties':{'Settings':{
            'bOverride_AutoExposureBias':True,'AutoExposureBias':2}}}]
        profile=build_profile(source)
        self.assertIsNone(profile['exposure_bias_ev'])
        self.assertTrue(profile['source_exposure_preserved'])

    def test_strict_mode_does_not_enable_the_compatibility_profile(self):
        self.assertFalse(build_profile(self.data(),mode='source')['enabled'])
        with self.assertRaises(ValueError):build_profile(self.data(),mode='unknown')

    def test_other_maps_do_not_inherit_collectionroom_exposure(self):
        self.assertEqual(build_profile({'mapRoot':'DeltaForce/Content/Maps/Iceland/'})['exposure_bias_ev'],0)

    def test_per_map_override_has_priority_and_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'game-lighting.json'
            path.write_text(json.dumps({'exposure_bias_ev':-2,'fog_only_scattering_cap':.03}))
            profile=build_profile(self.data(),directory)
            self.assertEqual(profile['exposure_bias_ev'],-2)
            self.assertEqual(profile['fog_only_scattering_cap'],.03)
            self.assertIn('per-map',profile['basis'])

    def test_invalid_overrides_fail_instead_of_silently_brightening_a_map(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'game-lighting.json'
            for values in ({'unknown':1},{'exposure_bias_ev':float('nan')},
                           {'fog_only_scattering_cap':2},{'exposure_bias_ev':True}):
                path.write_text(json.dumps(values))
                with self.subTest(values=values),self.assertRaises(ValueError):
                    build_profile(self.data(),directory)
            self.assertFalse(build_profile(self.data(),directory,mode='source')['enabled'])

    def test_preview_profile_is_explicit_in_the_native_command(self):
        values={'engine':'UnrealEditor.exe','project':'Test.uproject','root':'export',
                'dest':'/Game/Test','scripts':'scripts/official','render_profile':'source'}
        self.assertEqual(ue_pipeline.render_step(values).env['ATLASMAP_RENDER_PROFILE'],'source')
        del values['render_profile']
        self.assertEqual(ue_pipeline.render_step(values).env['ATLASMAP_RENDER_PROFILE'],'game')
