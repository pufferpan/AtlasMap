import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core.full_parallel_export import merge_source_states
from core.parallel_export import write


class EnvironmentMergeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.roots=[self.base/'first',self.base/'second']
        self.out=self.base/'merged'
        self.row=dict(source_texture='Game/Reflection.Shared',kind='cube',eligible=False,
                      selection_basis='capture Actor_A',texture=dict(RelativePath='environment/shared.dds',Width=128,Height=128))
        self.enrich=patch('core.scene_state.enrich',return_value={'complete':True})
        self.enrich.start();self.addCleanup(self.enrich.stop)

    def fixture(self, rows=None, blobs=(b'DDS same cube',b'DDS same cube'), filename='environment.json',field='skies'):
        rows=rows or [self.row,dict(self.row,selection_basis='capture Actor_B')]
        for index,root in enumerate(self.roots):
            write(root/'source-render/state-index.json',dict(complete=True,exporter={'sha256':'same'},levels=[],packages={},preservedAssets=[]))
            write(root/'source-render'/filename,{field:[rows[index]]})
            texture=root/'source-render/environment/shared.dds';texture.parent.mkdir(exist_ok=True)
            texture.write_bytes(blobs[index])

    def merge(self, roots=None):
        merge_source_states(roots or self.roots,self.out,'Test')
        return json.loads((self.out/'source-render/environment.json').read_text())

    def test_shared_cube_keeps_all_actor_provenance_and_is_order_independent(self):
        self.fixture()
        first=self.merge()
        self.assertEqual(len(first['skies']),1)
        row=first['skies'][0]
        self.assertEqual(row['selection_bases'],['capture Actor_A','capture Actor_B'])
        self.assertEqual(row['selection_basis'],'capture Actor_A')
        self.assertFalse(row['eligible'])
        self.assertEqual((self.out/'source-render/environment/shared.dds').read_bytes(),b'DDS same cube')
        self.assertEqual(self.merge(list(reversed(self.roots))),first)

    def test_identical_metadata_with_conflicting_pixels_is_rejected(self):
        self.fixture(rows=[self.row,self.row],blobs=(b'DDS good',b'DDS corrupt'))
        with self.assertRaisesRegex(ValueError,'环境贴图冲突'):self.merge()

    def test_duplicate_texture_must_exist_in_every_shard(self):
        self.fixture(rows=[self.row,self.row])
        (self.roots[1]/'source-render/environment/shared.dds').unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):self.merge()

    def test_rendering_metadata_conflicts_are_not_ignored(self):
        for field,value in [('eligible',True),('kind','latlong')]:
            with self.subTest(field=field):
                changed=copy.deepcopy(self.row);changed[field]=value
                self.fixture(rows=[self.row,changed])
                with self.assertRaisesRegex(ValueError,'环境资源在分块间不一致'):self.merge()

    def test_reflection_cubes_still_validate_duplicate_bytes(self):
        row=dict(guid='a'*32,source='assets/Test.uexp',texture='environment/shared.dds',brightness=1)
        self.fixture(rows=[row,row],filename='reflection-cubemaps.json',field='captures')
        merge_source_states(self.roots,self.out,'Test')
        document=json.loads((self.out/'source-render/reflection-cubemaps.json').read_text())
        self.assertEqual(document['captures'],[row])
        (self.roots[1]/'source-render/environment/shared.dds').write_bytes(b'wrong bytes')
        with self.assertRaisesRegex(ValueError,'环境贴图冲突'):merge_source_states(self.roots,self.out,'Test')
