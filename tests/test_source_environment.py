import copy
import unittest
from scripts.official.map_environment import select_sky,reflection_catalog,bind_reflections,native_intensity,ambient_weights
from scripts.official.map_surfaces import surface_settings


class SourceEnvironmentTests(unittest.TestCase):
    def test_room_preview_image_cannot_become_a_sky_even_if_labelled_eligible(self):
        billboard={'kind':'latlong','eligible':True,'parameters':{'MasterPath':'/Game/Mat/M_Billboard'}}
        self.assertIsNone(select_sky({'skies':[billboard]}))
        self.assertIsNone(select_sky({'skies':[dict(billboard,kind='reference_image')]}))

    def test_only_a_unique_supported_authored_environment_is_selected(self):
        sky={'kind':'cube','eligible':True,'source_texture':'Sky'}
        self.assertEqual(select_sky({'skies':[sky]}),sky)
        self.assertIsNone(select_sky({'skies':[sky,dict(sky,source_texture='OtherSky')]}))
        self.assertIsNone(select_sky({'skies':[dict(sky,rgbm=True)]}))

    def test_guid_binding_rejects_conflicts_and_does_not_match_by_component_name(self):
        row={'guid':'a'*32,'texture':'one.dds'}
        self.assertEqual(reflection_catalog({'captures':[row,row]}),{'a'*32:row})
        with self.assertRaises(ValueError):reflection_catalog({'captures':[row,dict(row,texture='other.dds')]})
        with self.assertRaises(ValueError):reflection_catalog({'captures':[dict(row,guid='NewReflectionComponent')]})

    def test_native_environment_energy_comes_from_source_average_not_an_arbitrary_boost(self):
        data=dict(average_brightness=.02,decoded_mean_luminance=1.0,brightness=1)
        self.assertAlmostEqual(native_intensity(data,{}),.02)
        self.assertAlmostEqual(native_intensity(data,{'Brightness':2}),.04)
        for field in ('average_brightness','decoded_mean_luminance','brightness'):
            for bad in (float('nan'),float('inf'),-1):
                with self.subTest(field=field,bad=bad),self.assertRaises(ValueError):native_intensity(dict(data,**{field:bad}),{})
        with self.assertRaises(ValueError):native_intensity(dict(data,decoded_mean_luminance=0),{})

    def test_capture_uses_its_active_bake_package_when_other_variants_share_a_guid(self):
        guid='a'*32
        capture=dict(guid=guid,properties={'LocalReflectionGroupBakeObject':{'ObjectPath':'Map/HDReflection.0'}})
        hd=dict(guid=guid,source='assets/Map/HDReflection.uexp',texture='hd.dds')
        old=dict(guid=guid,source='assets/Map/OldReflection.uexp',texture='old.dds')
        self.assertEqual(bind_reflections([capture],{'captures':[old,hd]}),{guid:hd})

    def test_overlapping_ambient_maps_are_compensated_instead_of_adding_at_full_energy(self):
        captures=[dict(guid=str(i),loc=[0,0,0],properties={'InfluenceRadius':1500}) for i in range(21)]
        self.assertAlmostEqual(sum(ambient_weights(captures).values()),1)
        captures[0]['loc']=[10000,0,0]
        self.assertEqual(ambient_weights(captures)['0'],1)

    def test_frosted_source_parameters_and_tint_survive_the_conversion(self):
        source={'resolved':{'MasterPath':'M_BlurryGlass_HD','ScalarParameters':{'BlurRoughness':.2,'Opacity':.7,'Distance':.02},
                  'VectorParameters':{'GlassTint':[.8,.9,1,1]}},
                'chain':[{'value':{'Properties':{'BlendMode':'BLEND_Translucent'}}}]}
        before=copy.deepcopy(source);glass=surface_settings(source)
        self.assertTrue(glass['frosted_glass'])
        self.assertEqual(glass['roughness'],.2)
        self.assertEqual(glass['frosted_blur_radius'],.02)
        self.assertEqual(glass['transmittance_color'],[.8,.9,1])
        self.assertEqual(source,before)
