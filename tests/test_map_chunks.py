import copy
import unittest

from scripts.official.map_chunks import partition_objects,material_subset


class MapChunkTests(unittest.TestCase):
    def test_source_levels_and_parents_stay_together_and_cover_every_object_once(self):
        objects=[]
        for level in range(8):
            root=f'parent{level}'
            objects.append({'id':root})
            for i in range(3):
                objects.append({'id':f'o{level}_{i}','parent':root,'triangles':(level+1)*10,
                                'properties':{'source_level':f'Level_{level}'}})
        before=copy.deepcopy(objects)
        chunks=partition_objects(objects,3)
        ids=[key for chunk in chunks for key in chunk['object_ids']]
        self.assertEqual(set(ids),{row['id'] for row in objects})
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(objects,before)
        self.assertTrue(all(chunk['object_ids'] for chunk in chunks))
        for chunk in chunks:
            owned=set(chunk['object_ids'])
            for row in objects:
                if row['id'] in owned and row.get('parent'):
                    self.assertIn(row['parent'],owned)
        self.assertEqual(chunks,partition_objects(list(reversed(objects)),3))

    def test_missing_parent_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):partition_objects([{'id':'a','parent':'missing'}],2)
        with self.assertRaises(ValueError):partition_objects([{'id':'a'},{'id':'a'}],2)

    def test_local_materials_include_parent_texture_defaults_and_actor_overrides(self):
        plan={'materials':[{'id':'m1','textures':[{'image':'t1'}]},{'id':'m2','textures':[{'image':'t2'}]},
                           {'id':'other','textures':[{'image':'unused'}]}],
              'object_materials':{'o1':['m2'],'o2':['other']},'mesh_materials':{'sm1':['m1'],'sm2':['other']}}
        instances={'instances':[{'id':'m1','parent':'master','textures':{'Texture_0':'t1'}},
                                {'id':'m2','parent':'master','textures':{'Texture_0':'t2'}},
                                {'id':'other','parent':'other_master','textures':{}}],
                   'parents':[{'id':'master','textures':[{'image':'parent_default'}]},
                              {'id':'other_master','textures':[{'image':'unused'}]}]}
        local,grouped,images=material_subset(plan,instances,[{'id':'o1'}],[{'id':'sm1'}])
        self.assertEqual({r['id'] for r in local['materials']},{'m1','m2'})
        self.assertEqual({r['id'] for r in grouped['parents']},{'master'})
        self.assertEqual(images,{'t1','t2','parent_default'})
        self.assertEqual(set(local['object_materials']),{'o1'})
