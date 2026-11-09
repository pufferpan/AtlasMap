import unittest
import numpy as np
from scripts.official.map_affine import world_matrices,BASIS,check_bounds,gltf_bounds

class AffineTests(unittest.TestCase):
 def test_parent_transforms_and_nonorthogonal_residual_are_retained(self):
  local=np.eye(4);local[0,1]=.002;local[:3,3]=[10,20,30]
  document={'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'translation':[100,200,300],'children':[1]},{'mesh':0,'matrix':local.T.reshape(-1).tolist(),'extras':{'dfmap':{'sourceId':'SOURCE'}}}]}
  parent=np.eye(4);parent[:3,3]=[100,200,300]
  result=world_matrices(document)['SOURCE']
  np.testing.assert_array_equal(result,BASIS@parent@local@BASIS.T)
  self.assertNotEqual(np.dot(result[:3,0],result[:3,2]),0)
 def test_gltf_trs_order_scales_before_translation(self):
  d={'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0,'name':'n','translation':[10,20,30],'scale':[2,3,4]}]}
  m=world_matrices(d)['n'];point=m@np.array([1,2,3,1])
  expected=BASIS@(np.diag([2,3,4,1])@BASIS.T@np.array([1,2,3,1])+np.array([10,20,30,0]))
  np.testing.assert_allclose(point,expected)

class BoundsTests(unittest.TestCase):
 def fixture(self,scale=1e7):
  vertices=np.array([[-.14410068,-.00409176,-.1441081],[.14429828,.15222248,.14429074]],dtype='<f4')
  document={'scenes':[{'nodes':[0]}], 'nodes':[{'name':'sky','mesh':0,'scale':[scale]*3}],
   'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
   'accessors':[{'componentType':5126,'type':'VEC3','count':2,'bufferView':0}],
   'bufferViews':[{'byteLength':vertices.nbytes}]}
  binary=vertices.tobytes();lower,upper=gltf_bounds(document,binary)
  # Reproduce native float32 bounds differing by 19 cm at a 1,440 km sky radius.
  ue_lo=lower[[0,1,2]].copy()*100;ue_hi=upper.copy()*100
  ue_lo[1],ue_hi[1]=-upper[1]*100,-lower[1]*100
  entry=dict(ueBoundsMin=ue_lo.tolist(),ueBoundsMax=ue_hi.tolist())
  entry['ueBoundsMin'][0]-=19
  return document,binary,lower,upper,entry
 def test_large_sky_is_checked_against_original_vertices(self):
  d,b,lo,hi,entry=self.fixture()
  result=check_bounds(lo,hi,entry,d,b)
  self.assertTrue(result['bounds_valid'])
  self.assertEqual(result['bounds_reference'],'gltf')
  self.assertAlmostEqual(result['source_glb_delta_m'],0)
  self.assertAlmostEqual(result['bounds_delta_m'],.19)
 def test_sky_placement_error_is_still_rejected(self):
  d,b,lo,hi,entry=self.fixture()
  self.assertFalse(check_bounds(lo+.1,hi+.1,entry,d,b)['bounds_valid'])
 def test_ordinary_geometry_keeps_five_centimetre_limit(self):
  d,b,lo,hi,entry=self.fixture(scale=100)
  self.assertFalse(check_bounds(lo,hi,entry,d,b)['bounds_valid'])
  entry['ueBoundsMin'][0]+=19
  self.assertTrue(check_bounds(lo,hi,entry,d,b)['bounds_valid'])
  self.assertFalse(check_bounds(lo+.06,hi+.06,entry,d,b)['bounds_valid'])
 def test_sky_difference_beyond_native_precision_is_rejected(self):
  d,b,lo,hi,entry=self.fixture()
  entry['ueBoundsMin'][0]-=100
  self.assertFalse(check_bounds(lo,hi,entry,d,b)['bounds_valid'])
