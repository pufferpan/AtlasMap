import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
import numpy as np
from scripts.official.map_geometry import audit_triangles,expected_triangles,expected_face_slots
from core import exporter,ue_pipeline


class MeshTopologyTests(unittest.TestCase):
    def source(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/watch_float32_faces.json').read_text())
        points=np.array(fixture['positions']).reshape(-1,3)
        points=np.concatenate([points,[[0.,0.,0.],[1.,0.,0.],[0.,1.,0.]]])
        return points,np.arange(9).reshape(-1,3),np.array([0,1,1])

    def test_real_watch_faces_collapse_only_after_centimetre_float32_conversion(self):
        v,i,s=self.source()
        cross=np.cross(v[i][:,1]-v[i][:,2],v[i][:,0]-v[i][:,2])
        self.assertTrue(np.all(np.linalg.norm(cross,axis=1)>0))
        audit=audit_triangles(v,i,s)
        self.assertEqual(audit['ue_degenerate_triangles'],2)
        row=dict(triangles=3,face_slot_counts={'0':1,'1':2},**audit)
        self.assertEqual(expected_triangles(row),1)
        self.assertEqual(expected_face_slots(row),{'1':1})

    def test_visible_geometry_is_not_treated_as_degenerate(self):
        v,i,s=self.source();v[:6]*=.001
        self.assertEqual(audit_triangles(v,i,s)['ue_degenerate_triangles'],0)

    def test_invalid_geometry_and_negative_face_counts_are_rejected(self):
        v,i,s=self.source();v[0,0]=np.nan
        with self.assertRaises(ValueError):audit_triangles(v,i,s)
        with self.assertRaises(ValueError):expected_triangles(dict(triangles=3,ue_degenerate_triangles=4))
        with self.assertRaises(ValueError):expected_face_slots(dict(face_slot_counts={'0':1},ue_degenerate_face_slot_counts={'0':2}))

    def test_legacy_manifests_preserve_strict_counts(self):
        self.assertEqual(expected_triangles(dict(triangles=10,repeated_index_triangles=2)),8)
        self.assertEqual(expected_triangles(dict(triangles=10,zero_area_triangles=3)),7)
        self.assertEqual(expected_face_slots(dict(face_slot_counts={'0':10},zero_area_face_slot_counts={'0':3})),{'0':7})


class MapCatalogueTests(unittest.TestCase):
    def test_export_config_is_immutable_when_default_scan_config_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            current=str(Path(directory)/'scan.json');job=str(Path(directory)/'job.json')
            with patch.object(exporter,'exporter_config_path',return_value=current):
                exporter.write_exporter_config(dict(paks='GameA/Content/Paks'),path=job)
                exporter.write_exporter_config(dict(paks='GameB/Content/Paks'))
            self.assertEqual(json.loads(Path(job).read_text())['PaksDirectory'],'GameA/Content/Paks')
            self.assertEqual(json.loads(Path(current).read_text())['PaksDirectory'],'GameB/Content/Paks')

    def test_wegame_base_paks_also_mount_downloaded_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            game=Path(directory)/'DeltaForce';base=game/'Content'/'Paks';base.mkdir(parents=True)
            self.assertEqual(exporter.game_resource_root(str(base)),str(base))
            hotfix=game/'Saved'/'Dolphin'/'1.101.37117.36'/'Paks';hotfix.mkdir(parents=True)
            (hotfix/'update.pak').write_bytes(b'pak')
            self.assertEqual(exporter.game_resource_root(str(base)),str(game))
            self.assertEqual(exporter.game_resource_root(str(hotfix)),str(hotfix))
            with patch.object(exporter,'exporter_config_path',return_value=str(Path(directory)/'config.json')):
                config=exporter.write_exporter_config(dict(paks=str(base)))
                self.assertEqual(json.loads(Path(config).read_text())['PaksDirectory'],str(game).replace('\\','/'))

    def test_scan_covers_authored_and_streamed_maps_without_engine_templates(self):
        text='\n'.join(['1 DeltaForce/Content/Maps/Brakkesh_Long3/Base.umap',
                       '1 DeltaForce/Content/Maps/BuildMaps_HD/Collapse/Runtime/Cell.umap',
                       '1 DeltaForce/Content/Maps/BuildMaps/Collapse/Runtime/Cell2.umap',
                       '1 DeltaForce/Content/Maps/BuildMaps_HD/PhysXShared_Collapse/Cell.umap',
                       '1 Engine/Content/Maps/Templates/Default/Default.umap'])
        self.assertEqual(exporter.parse_maps(text),{'Brakkesh_Long3':1,'Collapse':2})
        from core import mapnames
        self.assertEqual(mapnames.cn_of('Brakkesh_Long3')[0],'Brakkesh Long3')
        self.assertEqual(mapnames.cn_of('Collapse')[0],'Collapse')
        self.assertNotIn('Brakkesh',mapnames.known())
        self.assertEqual(mapnames.cn_of('Brakkesh_Level22')[0],'Brakkesh')
        self.assertIn('DeltaForce/Content/Maps/Brakkesh_Long3/',ue_pipeline.map_roots('Brakkesh_Long3'))

    def test_failed_or_truncated_inventory_does_not_report_scan_success(self):
        with patch.object(exporter,'_base_cmd',return_value=['map-export.exe']):
            with patch.object(exporter,'run_blocking',return_value=(1,'codec missing')):
                with self.assertRaisesRegex(RuntimeError,'codec missing'):exporter.list_maps('map-export.exe')
            with patch.object(exporter,'run_blocking',return_value=(0,'== 500000 files matching "Maps" (showing 400000) ==')):
                with self.assertRaisesRegex(RuntimeError,'截断'):exporter.list_maps('map-export.exe')

    def test_scan_requires_levels_and_rejects_physics_only_folders(self):
        text='\n'.join(['12 DeltaForce/Content/Maps/BuildMaps_HD/BombDefusal_Mansion/Runtime/LV.umap',
                        '32 DeltaForce/Content/Maps/BuildMaps_HD/BombDefusal_Mansion/Mesh.uasset',
                        '42 DeltaForce/Content/Maps/BuildMaps_HD/PhysXShared_BombDefusal_Mansion/Mesh.uasset',
                        '52 DeltaForce/Content/Maps/BuildMaps_HD/OnlyTextures/Texture.uasset'])
        with patch.object(exporter,'run_blocking',return_value=(0,text)),patch.object(exporter,'_base_cmd',return_value=['map-export.exe']):
            self.assertEqual(exporter.list_maps('map-export.exe'),{'BombDefusal_Mansion':2})

    def test_typed_physics_only_directory_is_rejected_before_export(self):
        with self.assertRaisesRegex(ValueError,'请选择 BombDefusal_Mansion'):
            ue_pipeline.map_roots('PhysXShared_BombDefusal_Mansion')
