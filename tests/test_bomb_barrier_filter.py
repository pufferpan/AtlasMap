"""Source-class omission must not turn into a global Plane/white-mesh filter."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.export_filter import filter_export,is_start_barrier,remove_glb_nodes,_glb_parts,merge_filter_reports
from core import exporter,ue_pipeline


LEVEL='DeltaForce/Content/Maps/BombDefusal_Watch/GameplayConfig/BombDefusal_Watch_GameplayConfig.umap'


def instance(identity,klass='BP_BlockWall_BombDefusal_C',level=LEVEL):
    return {'mesh':'Engine/Content/BasicShapes/Plane.Plane',
        'name':f"BombDefusal_Watch_GameplayConfig/{klass}'Map:PersistentLevel.StartBlockWall19'/StaticMeshComponent0",
        'dfmap':{'sourceId':identity,'sourceLevel':level}}


def glb(identities):
    binary=struct.pack('<9f',0,0,0,1,0,0,0,0,1)
    nodes=[{'name':'Level','children':list(range(1,len(identities)+1))}]
    for i,identity in enumerate(identities):
        nodes.append({'name':identity,'mesh':0,'translation':[i*1000,0,0],
            'extras':{'dfmap':{'sourceId':identity}}})
    document={'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':nodes,
        'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
        'accessors':[{'bufferView':0,'componentType':5126,'type':'VEC3','count':3}],
        'bufferViews':[{'buffer':0,'byteLength':len(binary)}],'buffers':[{'byteLength':len(binary)}]}
    encoded=json.dumps(document).encode();encoded+=b' '*((-len(encoded))%4)
    body=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
    return struct.pack('<III',0x46546c67,2,12+len(body))+body


def fixture(root,only_barrier=False):
    root=Path(root);(root/'split').mkdir(parents=True)
    objects=[instance('DFI_Barrier')]
    if not only_barrier:objects.append(instance('DFI_OrdinaryPlane','StaticMeshActor'))
    (root/'scene.json').write_text(json.dumps({'mapRoot':' + '.join(ue_pipeline.map_roots('BombDefusal_Watch')),'instances':objects}))
    (root/'split/level.glb').write_bytes(glb([o['dfmap']['sourceId'] for o in objects]))
    (root/'split/manifest.json').write_text(json.dumps({'levels':[{'level':LEVEL,'sourceLevel':LEVEL,'glb':'level.glb','instances':len(objects),
        'ueBoundsMin':[0,0,0],'ueBoundsMax':[100100,100,0]}]}))
    (root/'merge_report.json').write_text(json.dumps({'Instances':len(objects),'Levels':[{'Level':LEVEL,'Include':True,'Instances':len(objects)}]}))
    (root/'lights.json').write_text('{"lights":[]}')
    return root


class BarrierFilterTests(unittest.TestCase):
    def test_only_the_confirmed_blueprint_class_in_a_bombdefusal_map_matches(self):
        self.assertTrue(is_start_barrier(instance('DFI_1')))
        self.assertFalse(is_start_barrier(instance('DFI_2','StaticMeshActor')))
        self.assertFalse(is_start_barrier(instance('DFI_3','BP_BlockWall_Other_C')))
        self.assertFalse(is_start_barrier(instance('DFI_4','BP_BlockWall_BombDefusal_C_Other')))
        self.assertFalse(is_start_barrier(instance('DFI_5',level='DeltaForce/Content/Maps/Iceland/Gameplay.umap')))

    def test_removed_nodes_and_indices_change_but_binary_payload_is_identical(self):
        raw=glb(['DFI_Barrier','DFI_Keep'])
        result,geometry,count=remove_glb_nodes(raw,{'DFI_Barrier'})
        self.assertEqual(count,1)
        document,binary=geometry
        self.assertEqual(document['nodes'][0]['children'],[1])
        self.assertEqual(document['nodes'][1]['name'],'DFI_Keep')
        self.assertEqual(_glb_parts(raw)[1:],_glb_parts(result)[1:])
        self.assertEqual(struct.unpack_from('<I',result,8)[0],len(result))

    def test_manifest_counts_and_true_retained_bounds_are_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary);report=filter_export(root)
            self.assertTrue(report['complete']);self.assertEqual(report['removed_instances'],1)
            scene=json.loads((root/'scene.json').read_text())
            self.assertEqual([x['dfmap']['sourceId'] for x in scene['instances']],['DFI_OrdinaryPlane'])
            entry=json.loads((root/'split/manifest.json').read_text())['levels'][0]
            self.assertEqual(entry['instances'],1)
            self.assertEqual(entry['blenderBoundsMinM'],[1000,-1,0])
            self.assertEqual(entry['blenderBoundsMaxM'],[1001,0,0])
            merge=json.loads((root/'merge_report.json').read_text())
            self.assertEqual(merge['Instances'],1);self.assertEqual(merge['Levels'][0]['Instances'],1)

    def test_repeated_filter_is_bytewise_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary);first=filter_export(root)
            hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(filter_export(root),first)
            self.assertEqual(hashes,{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()})

    def test_level_containing_only_barriers_is_not_imported_as_an_empty_glb(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary,True);filter_export(root)
            self.assertEqual(json.loads((root/'split/manifest.json').read_text())['levels'],[])
            self.assertEqual(json.loads((root/'merge_report.json').read_text())['Levels'][0]['Instances'],0)

    def test_merged_manifest_root_relative_glb_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary);chunk=root/'chunks/Chunk_002/split';chunk.mkdir(parents=True)
            (root/'split/level.glb').replace(chunk/'level.glb')
            manifest=json.loads((root/'split/manifest.json').read_text());manifest['levels'][0]['glb']='chunks/Chunk_002/split/level.glb'
            (root/'split/manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(filter_export(root)['removed_instances'],1)

    def test_incomplete_matching_source_raises_before_any_geometry_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary);raw=(root/'split/level.glb').read_bytes()
            (root/'split/level.glb').write_bytes(glb(['DFI_Unrelated']))
            before=(root/'scene.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'absent'):filter_export(root)
            self.assertEqual((root/'scene.json').read_bytes(),before)

    def test_a_foreign_child_is_not_accidentally_removed(self):
        raw=glb(['DFI_Barrier','DFI_Keep']);parts=_glb_parts(raw);doc=json.loads(parts[0][1]);doc['nodes'][1]['children']=[2]
        data=json.dumps(doc).encode();data+=b' '*((-len(data))%4)
        body=struct.pack('<II',len(data),0x4e4f534a)+data+struct.pack('<II',len(parts[1][1]),parts[1][0])+parts[1][1]
        raw=struct.pack('<III',0x46546c67,2,len(body)+12)+body
        with self.assertRaisesRegex(ValueError,'separate source child'):remove_glb_nodes(raw,{'DFI_Barrier'})

    def test_serial_ue_export_validation_applies_the_filter_before_blender(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary)
            ue_pipeline.validate_export(str(root),'BombDefusal_Watch')
            self.assertEqual(json.loads((root/'filter_report.json').read_text())['removed_instances'],1)

    def test_normal_gui_merge_completion_applies_the_filter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=fixture(temporary)
            with patch.object(exporter,'source_state_command',return_value=None):
                job=exporter.start([sys.executable,'-c','pass','merge','BombDefusal_Watch',str(root)])
                job._threads[0].join(10)
            self.assertEqual(job.code,0)
            self.assertEqual(json.loads((root/'filter_report.json').read_text())['removed_instances'],1)

    def test_chunk_audit_preserves_the_total_at_the_merged_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);chunk=fixture(base/'chunk');filter_export(chunk)
            merged=base/'merged';merged.mkdir();(merged/'scene.json').write_bytes((chunk/'scene.json').read_bytes())
            report=merge_filter_reports([chunk],merged)
            self.assertEqual(report['removed_instances'],1)
            self.assertEqual(report['instances_before'],2)
            self.assertEqual(filter_export(merged),report)
