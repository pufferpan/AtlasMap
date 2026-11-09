import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from scripts.official.map_surfaces import surface_settings

class SurfaceTests(unittest.TestCase):
 def source(self,master,props,scalars=None):
  return {'resolved':{'MasterPath':master,'ScalarParameters':scalars or {}},'chain':[{'type':'Material','value':{'Properties':props}}]}
 def test_missing_parent_material_preserves_basic_shader(self):
  self.assertEqual(surface_settings({'resolved':{'MasterPath':None,'Path':None},'chain':[]}),{})
  source=self.source(None,{'BlendMode':'BLEND_Translucent'})
  self.assertEqual(surface_settings(source)['kind'],'translucent')
 def test_native_glass_and_foliage_do_not_share_blend_mode(self):
  glass=surface_settings(self.source('M_NRMAC_Translucent',{'BlendMode':'BLEND_Translucent'},{'OpacityMaskMax':.6,'OpacityMaskMin':0}))
  leaves=surface_settings(self.source('M_Foliage',{'BlendMode':'BLEND_Masked'}))
  self.assertEqual(glass['kind'],'translucent');self.assertAlmostEqual(glass['opacity'],.3)
  source=self.source('M_NRMAC_Translucent',{'BlendMode':'BLEND_Translucent','PhysMaterial':{'ObjectName':"PhysicalMaterial'GlassNoDecal'"}})
  self.assertTrue(surface_settings(source)['thin_glass'])
  self.assertEqual(leaves['kind'],'masked')
 def test_water_tank_is_not_a_water_surface(self):
  source=self.source('M_Prop_Master',{'BlendMode':'BLEND_Opaque'})
  source['resolved']['Path']='MI_ContainerWaterTank'
  self.assertEqual(surface_settings(source)['kind'],'opaque')
 def test_native_water_preserves_units_and_roughness(self):
  source=self.source('M_WaterHD',{'ShadingModel':'MSM_SingleLayerWater'},{'WaterRoughnessMin':.05})
  source['resolved']['VectorParameters']={'SurfaceAbsorption0':[.5,1,.25,500],'SurfaceScattering0':[.2,.2,.05,.0005]}
  water=surface_settings(source)
  self.assertEqual(water['kind'],'water');self.assertEqual(water['roughness'],.05)
  self.assertEqual(water['absorption'],[.004,.002,.008])
  self.assertAlmostEqual(water['scattering'][0],.0001)
 def test_instance_overrides_require_the_native_override_flag(self):
  source=self.source('M_Glass',{'BlendMode':'BLEND_Translucent'})
  source['chain'].insert(0,{'value':{'Properties':{'BasePropertyOverrides':{'BlendMode':'BLEND_Opaque'}}}})
  self.assertEqual(surface_settings(source)['kind'],'translucent')
  source['chain'][0]['value']['Properties']['BasePropertyOverrides']['bOverride_BlendMode']=True
  self.assertEqual(surface_settings(source)['kind'],'opaque')
 def test_export_grouping_keeps_water_glass_and_masked_shaders_distinct(self):
  scripts=Path(__file__).resolve().parents[1]/'scripts/official'
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'material_graphs').mkdir()
   materials=[]
   for i,kind in enumerate(('water','translucent','masked','opaque')):
    settings={'kind':kind,'opacity':.3,'roughness':.1,'ior':1.45,'specular':.5}
    materials.append({'id':str(i),'source_name':kind,'source_path':kind,'use_nodes':False,'diffuse_color':[1,1,1,.3],'metallic':0,'roughness':.1,'backface_culling':False,'nodes':[],'surface':settings})
   manifest={'materials':materials,'images':[],'meshes':[{'id':'mesh','materials':['0','1','2','3'],'uv_layers':[],'active_render_uv':0}],'objects':[]}
   (root/'manifest.json').write_text(json.dumps(manifest))
   env=dict(os.environ,ATLASMAP_UE_ROOT=str(root))
   for name in ('compile_iceland_ue_materials.py','group_iceland_ue_materials.py'):
    subprocess.run([sys.executable,str(scripts/name)],env=env,check=True,stdout=subprocess.DEVNULL)
   compiled=json.loads((root/'material_plan.json').read_text())['materials']
   self.assertEqual([x['surface_kind'] for x in compiled],['water','translucent','masked','opaque'])
   self.assertEqual([x['masked'] for x in compiled],[False,False,True,False])
   self.assertIn('OutAlpha=saturate(1.0)',compiled[-1]['code'])
   grouped=json.loads((root/'material_instance_plan.json').read_text())
   self.assertEqual(len(grouped['parents']),4)
   self.assertEqual(grouped['equivalence_verified'],4)
