import copy
import json
import unittest
from scripts.official.map_lod import apply_manifest, covered_proxies


def instance(identity, level, **visibility):
    return {'dfmap':dict(sourceId=identity, sourceLevel=level, visibility=visibility)}


BASE='DeltaForce/Content/Maps/BuildMaps_HD/BombDefusal_Dock/Runtime/'


class LodPolicyTests(unittest.TestCase):
    def test_only_matching_map_cell_and_lod0_is_suppressed(self):
        rows=[instance('detail',BASE+'BigMeshGroup/BigMeshGroup_7_-4.umap'),
              instance('covered',BASE+'HLOD/HLOD0_7_-4.umap'),
              instance('far',BASE+'HLOD/HLOD0_8_-4.umap'),
              instance('other',BASE.replace('Dock','Watch')+'HLOD/HLOD0_7_-4.umap'),
              instance('lod1',BASE+'HLOD/HLOD1_7_-4.umap')]
        self.assertEqual(set(covered_proxies(rows)), {'covered'})

    def test_hidden_detail_is_not_a_valid_replacement(self):
        for visibility in ({'renderable':False},{'hiddenInGame':True},{'visible':False},{'ownerHidden':True}):
            rows=[instance('detail',BASE+'MidMeshGroup/MidMeshGroup_7_-4.umap',**visibility),
                  instance('proxy',BASE+'HLOD/HLOD0_7_-4.umap')]
            self.assertEqual(covered_proxies(rows), {})

    def test_global_scene_suppresses_proxy_in_a_different_worker(self):
        rows=[instance('detail',BASE+'SmallMeshGroup/SmallMeshGroup_7_-4.umap'),
              instance('proxy',BASE+'HLOD/HLOD0_7_-4.umap')]
        manifest={'counts':{},'objects':[dict(id='O_proxy',type='MESH',hidden_render=False,
            hidden_editor=False,properties={'map_source':json.dumps(rows[1]['dfmap'])}),
            dict(id='O_normal',type='MESH',hidden_render=False,hidden_editor=False,properties={})]}
        report=apply_manifest(manifest,rows)
        self.assertEqual(report['suppressed'],1)
        self.assertTrue(manifest['objects'][0]['hidden_render'])
        self.assertTrue(manifest['objects'][0]['hidden_editor'])
        self.assertFalse(manifest['objects'][1]['hidden_render'])
        self.assertEqual(manifest['counts']['hidden_render_meshes'],1)
        again=copy.deepcopy(manifest)
        self.assertEqual(apply_manifest(again,rows),report)
        self.assertEqual(again,manifest)

    def test_numeric_cell_matching_and_unknown_paths(self):
        rows=[instance('detail',BASE+'BigMeshGroup/BigMeshGroup_-7_0.umap'),
              instance('proxy',BASE+'HLOD/HLOD0_-7_0.umap'),
              instance('unrelated',BASE+'Props/HLOD0_-7_0.umap')]
        self.assertEqual(set(covered_proxies(rows)),{'proxy'})
