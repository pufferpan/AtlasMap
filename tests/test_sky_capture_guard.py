"""Avoid an always-black realtime SkyLight without inventing a new sky."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE=Path(__file__).resolve().parents[1]/'scripts/official/ue_sky_capture.py'
spec=importlib.util.spec_from_file_location('sky_capture_guard',SOURCE)
sky=importlib.util.module_from_spec(spec);spec.loader.exec_module(sky)


class Object:
    def __init__(self,**values):self.values=values
    def get_editor_property(self,name):return self.values[name]
    def set_editor_property(self,name,value):self.values[name]=value
    def get_path_name(self):return '/Test/'+self.__class__.__name__


class Cube(Object):pass
class Atmosphere(Object):pass
class Cloud(Object):pass
class Mesh(Object):
    def get_materials(self):return self.values.get('materials',[])
class Material(Object):
    def get_base_material(self):return self
class Sky(Object):
    def recapture_sky(self):self.values['capture_count']=self.values.get('capture_count',0)+1
class Actor(Object):
    def __init__(self,components=(),tags=(),**values):
        super().__init__(**{'hidden':False,**values});self.components=list(components);self.tags=list(tags)
    def get_components_by_class(self,cls):return [c for c in self.components if isinstance(c,cls)]
    def get_component_by_class(self,cls):return next(iter(self.get_components_by_class(cls)),None)
    def is_hidden_ed(self):return self.values.get('hidden_editor',False)


UE=SimpleNamespace(SkyLightSourceType=SimpleNamespace(SLS_CAPTURED_SCENE='scene',SLS_SPECIFIED_CUBEMAP='cube'),
    TextureCube=Cube,SkyLightComponent=Sky,SkyAtmosphereComponent=Atmosphere,VolumetricCloudComponent=Cloud,MeshComponent=Mesh)


class SkyCaptureGuardTests(unittest.TestCase):
    def component(self,**kwargs):
        return Sky(**{'source_type':'scene','cubemap':None,'real_time_capture':True,'visible':True,**kwargs})

    def finalize(self,component,providers=(),source_props=None,no_render=False):
        light=Actor([component],['AtlasMapLighting_sky'])
        actors=[light,*providers];eas=SimpleNamespace(get_all_level_actors=lambda:actors)
        row={'type':'Sky','name':'Authored Sky','source':{'properties':source_props or {}}}
        report={'errors':[],'compatibility':[]}
        sky.finalize_skies(UE,eas,report,[('sky',row)],no_render)
        return report

    def test_preparation_preserves_an_existing_specified_cube(self):
        cube=Cube();component=self.component(source_type='cube',cubemap=cube)
        sky.prepare_sky(UE,component)
        self.assertEqual(component.values['source_type'],'cube')
        self.assertIs(component.values['cubemap'],cube)
        self.assertFalse(component.values['real_time_capture'])

    def test_no_sky_disables_realtime_but_does_not_claim_environment_restored(self):
        component=self.component();report=self.finalize(component)
        self.assertFalse(component.values['real_time_capture'])
        self.assertFalse(report['environment_complete'])
        self.assertFalse(report['sky_capture']['environment_complete'])
        self.assertNotIn('capture_count',component.values)
        self.assertIn('may still be dark',report['compatibility'][0])

    def test_specified_cube_needs_no_atmosphere_and_is_never_scene_recaptured(self):
        cube=Cube();component=self.component(source_type='cube',cubemap=cube)
        report=self.finalize(component,source_props={'SourceType':'SLS_SpecifiedCubemap'})
        self.assertEqual(component.values['source_type'],'cube')
        self.assertIs(component.values['cubemap'],cube)
        self.assertFalse(component.values['real_time_capture'])
        self.assertTrue(report['sky_capture']['environment_complete'])
        self.assertEqual(report['errors'],[])
        self.assertNotIn('capture_count',component.values)

    def test_visible_atmosphere_allows_captured_scene(self):
        component=self.component();provider=Actor([Atmosphere(visible=True)])
        report=self.finalize(component,[provider])
        self.assertTrue(component.values['real_time_capture'])
        self.assertEqual(component.values['capture_count'],1)
        self.assertEqual(report['sky_capture']['providers'][0]['kind'],'SkyAtmosphere')

    def test_explicit_is_sky_material_qualifies_without_mutation(self):
        component=self.component();material=Material(is_sky=True)
        mesh=Mesh(visible=True,visible_in_real_time_sky_captures=True,materials=[material])
        before=dict(material.values)
        report=self.finalize(component,[Actor([mesh])])
        self.assertTrue(component.values['real_time_capture'])
        self.assertEqual(report['sky_capture']['providers'][0]['kind'],'IsSkyMesh')
        self.assertEqual(material.values,before)

    def test_unlit_or_unreadable_material_does_not_qualify(self):
        for material in [Material(shading_model='unlit'),Material(is_sky=False)]:
            component=self.component()
            mesh=Mesh(visible=True,visible_in_real_time_sky_captures=True,materials=[material])
            report=self.finalize(component,[Actor([mesh])])
            self.assertFalse(component.values['real_time_capture'])
            self.assertFalse(report['environment_complete'])
            self.assertNotIn('is_sky',material.values) if 'shading_model' in material.values else None

    def test_missing_visibility_api_hidden_and_capture_excluded_providers_are_rejected(self):
        providers=[Actor([Atmosphere()]),Actor([Atmosphere(visible=True)],hidden=True),
            Actor([Atmosphere(visible=True)],hidden_editor=True),
            Actor([Mesh(visible=True,visible_in_real_time_sky_captures=False,materials=[Material(is_sky=True)])])]
        for provider in providers:
            component=self.component();report=self.finalize(component,[provider])
            self.assertFalse(component.values['real_time_capture'])
            self.assertEqual(report['sky_capture']['providers'],[])

    def test_missing_authored_cube_stays_unresolved_even_if_an_unrelated_atmosphere_exists(self):
        component=self.component();report=self.finalize(component,[Actor([Atmosphere(visible=True)])],
            {'SourceType':'SLS_SpecifiedCubemap','Cubemap':{'ObjectPath':'MissingCube.0'}})
        self.assertFalse(component.values['real_time_capture'])
        self.assertFalse(report['environment_complete'])
        self.assertTrue(report['sky_capture']['lights'][0]['missing_authored_cubemap'])

    def test_nullrhi_defers_capture_but_retains_valid_realtime_dependency(self):
        component=self.component();report=self.finalize(component,[Actor([Atmosphere(visible=True)])],no_render=True)
        self.assertTrue(component.values['real_time_capture'])
        self.assertNotIn('capture_count',component.values)
        self.assertTrue(report['sky_capture']['lights'][0]['recapture_deferred'])

    def test_silent_setter_failure_is_reported(self):
        class Silent(Sky):
            def set_editor_property(self,name,value):
                if name!='real_time_capture':super().set_editor_property(name,value)
        component=Silent(source_type='scene',cubemap=None,real_time_capture=True,visible=True)
        report=self.finalize(component)
        self.assertEqual(report['errors'][0]['phase'],'sky_capture_readback')
        self.assertFalse(report['environment_complete'])


if __name__=='__main__':unittest.main()
