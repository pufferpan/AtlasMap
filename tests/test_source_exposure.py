"""Exposure bounds must keep their EV domain and exact source curve identity."""
import hashlib,importlib.util,json,math,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('source_exposure_plan',BASE/'scripts/official/map_exposure.py')
exposure=importlib.util.module_from_spec(spec);spec.loader.exec_module(exposure)
spec=importlib.util.spec_from_file_location('source_exposure_apply',BASE/'scripts/official/ue_source_exposure.py')
apply=importlib.util.module_from_spec(spec);spec.loader.exec_module(apply)


def key(time,value,mode='RCIM_Linear',**extra):
    return dict(Time=time,Value=value,InterpMode=mode,TangentWeightMode='RCTWM_WeightedNone',**extra)


class ExposurePlanTests(unittest.TestCase):
    def setup_source(self,folder,second_limits=None,with_curve=True):
        folder=Path(folder);source=folder/'source-render';source.mkdir()
        def tod(lo,hi):return {'type':'NZSkyBoxComponent','value':{'Properties':{'TodExposure':{
            'MinBrightnessCrv_Wtx':{'EditorCurveData':{'Keys':[key(10,lo)]}},
            'MaxBrightnessCrv_Wtx':{'EditorCurveData':{'Keys':[key(10,hi)]}},
            'CompensationCurve_Wtx':{'EditorCurveData':{'Keys':[key(10,0)]}},
            'MinBrightnessCrv_Wtx[1]':{'EditorCurveData':{'Keys':[key(10,12)]}}}}}}
        packages={'DeltaForce/Content/Maps/BombDefusal_Test/ClientConfig/BombDefusal_Test_TODLight.umap':'tod.json'}
        (source/'tod.json').write_text(json.dumps([tod(13.5,14.5)]))
        if second_limits:
            packages['DeltaForce/Content/Maps/BombDefusal_Test/ClientConfig/Other_TODLight.umap']='tod2.json'
            (source/'tod2.json').write_text(json.dumps([tod(*second_limits)]))
        (source/'state-index.json').write_text(json.dumps({'packages':packages}))
        curve_package='DeltaForce/Content/Environment/Watch_Compensation'
        if with_curve:
            curve=[{'type':'CurveFloat','value':{'Package':curve_package,'Properties':{'FloatCurve':{'Keys':[key(-3,0),key(3,4)]}}}}]
            (source/'curve.json').write_text(json.dumps(curve))
            (source/'exposure-resources.json').write_text(json.dumps({'schema':1,'resources':[{
                'source_path':curve_package+'.Watch_Compensation','role':'AutoExposureBiasCurve','kind':'curve','raw':'curve.json'}]}))
        data={'mapRoot':'DeltaForce/Content/Maps/BombDefusal_Test/','postprocess':[{'properties':{
            'Priority':1,'Settings':{'bOverride_AutoExposureBiasCurve':True,'AutoExposureBiasCurve':{'ObjectPath':curve_package+'.0'}}}}]}
        return folder,data

    def test_nonextended_limits_are_two_to_ev_not_minus_three(self):
        self.assertEqual(exposure.native_limits(13.5,14.5,False),[2**13.5,2**14.5])

    def test_extended_range_keeps_ev_values(self):
        self.assertEqual(exposure.native_limits(13.5,14.5,True,.65),[13.5,14.5])

    def test_native_ibl_mapping_requires_a_consistent_explicit_source_coefficient(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder,data=self.setup_source(temporary)
            source=folder/'source-render/tod.json';rows=json.loads(source.read_text())
            rows[0]['value']['Properties']['TodExposure']['IBLCoef']=500
            source.write_text(json.dumps(rows))
            self.assertEqual(exposure.build_plan(data,folder,False)['source_ibl_coefficient'],500)
            rows.append(json.loads(json.dumps(rows[0])))
            rows[1]['value']['Properties']['TodExposure']['IBLCoef']=100
            source.write_text(json.dumps(rows))
            self.assertIsNone(exposure.build_plan(data,folder,False)['source_ibl_coefficient'])

    def test_exact_source_bounds_curve_and_mobile_suffix_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder,data=self.setup_source(temporary)
            p=exposure.build_plan(data,folder,False)
            self.assertTrue(p['eligible']);self.assertEqual(p['source_ev_limits'],[13.5,14.5]);self.assertEqual(p['bias_ev'],0)
            self.assertEqual(p['curve']['source_package'],'deltaforce/content/environment/watch_compensation')

    def test_multiple_conflicting_source_limits_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder,data=self.setup_source(temporary,second_limits=(8,10))
            p=exposure.build_plan(data,folder,False)
            self.assertFalse(p['eligible']);self.assertIn('ambiguous',p['errors'][0])

    def test_missing_authored_curve_blocks_partial_auto_apply(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder,data=self.setup_source(temporary,with_curve=False)
            p=exposure.build_plan(data,folder,False)
            self.assertFalse(p['eligible']);self.assertIn('unavailable',p['skipped_missing'][0])

    def test_dynamic_tod_curve_requires_a_time_policy(self):
        with self.assertRaisesRegex(ValueError,'single-key'):
            exposure.constant_curve({'EditorCurveData':{'Keys':[key(0,10),key(24,12)]}},'Minimum')

    def test_linear_constant_cubic_and_clamped_endpoints(self):
        self.assertEqual(exposure.evaluate_curve([key(0,0),key(2,4)],1),2)
        self.assertEqual(exposure.evaluate_curve([key(0,2,'RCIM_Constant'),key(2,4)],1),2)
        self.assertAlmostEqual(exposure.evaluate_curve([key(0,0,'RCIM_Cubic',LeaveTangent=2),key(2,4,ArriveTangent=2)],1),2)
        self.assertEqual(exposure.evaluate_curve([key(0,2),key(2,4)],-20),2)
        self.assertEqual(exposure.evaluate_curve([key(0,2),key(2,4)],20),4)

    def test_unsupported_weighted_tangents_are_explicit(self):
        k=key(0,1);k['TangentWeightMode']='RCTWM_WeightedBoth'
        with self.assertRaisesRegex(ValueError,'Weighted'):exposure.validate_keys([k])

    def test_constant_interval_uses_right_key_value_at_exact_key_time(self):
        keys=[key(0,2,'RCIM_Constant'),key(1,5,'RCIM_Constant'),key(2,9)]
        self.assertEqual(exposure.evaluate_curve(keys,.999),2)
        self.assertEqual(exposure.evaluate_curve(keys,1),5)
        self.assertEqual(exposure.evaluate_curve(keys,1.001),5)

    def test_nan_and_duplicate_time_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'nonfinite'):exposure.validate_keys([key(0,float('nan'))])
        with self.assertRaisesRegex(ValueError,'Duplicate'):exposure.validate_keys([key(0,0),key(0,1)])


class Object:
    def __init__(self,**values):self.values=values
    def get_editor_property(self,name):return self.values.get(name)
    def set_editor_property(self,name,value):self.values[name]=value
    def get_path_name(self):return '/Game/Test/Curve'


class Curve(Object):
    def get_float_value(self,time):return exposure.evaluate_curve(self.values['keys'],time)


class ExposureApplyTests(unittest.TestCase):
    def fixture(self):
        keys=[key(0,0),key(1,1)];curve=Curve(keys=keys)
        library=SimpleNamespace(get_metadata_tag=lambda *args:'expected-hash')
        ue=SimpleNamespace(load_asset=lambda path:curve,Object=Object,EditorAssetLibrary=library,
            AutoExposureMethod=SimpleNamespace(AEM_HISTOGRAM='Histogram'))
        component=Object(settings=Object(auto_exposure_meter_mask='ExistingMeter'))
        plan={'eligible':True,'source_ev_limits':[13.5,14.5],'native_limits':[2**13.5,2**14.5],
            'bias_ev':0,'curve':{'source_package':'curve','sha256':'expected-hash','keys':keys,'file':'unused.json'}}
        return ue,component,plan

    def test_apply_preserves_existing_meter_and_reads_back_fields(self):
        ue,component,plan=self.fixture()
        with tempfile.TemporaryDirectory() as temporary:
            result=apply.apply_to_component(ue,component,plan,'/Game/Test',temporary)
        self.assertTrue(result['passed']);self.assertFalse(result['meter_mask_changed'])
        self.assertEqual(component.values['settings'].values['auto_exposure_meter_mask'],'ExistingMeter')
        self.assertEqual(component.values['settings'].values['auto_exposure_min_brightness'],2**13.5)

    def test_ineligible_plan_is_rejected_before_mutation(self):
        ue,component,plan=self.fixture();plan['eligible']=False
        with self.assertRaisesRegex(ValueError,'not eligible'):apply.apply_to_component(ue,component,plan,'/Game/Test')
        self.assertNotIn('auto_exposure_min_brightness',component.values['settings'].values)

    def test_silent_settings_setter_failure_fails_readback(self):
        ue,component,plan=self.fixture()
        original=component.values['settings'].set_editor_property
        component.values['settings'].set_editor_property=lambda key,value:None if key=='auto_exposure_min_brightness' else original(key,value)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises((RuntimeError,TypeError)):apply.apply_to_component(ue,component,plan,'/Game/Test',temporary)


class ChunkExposureRoutingTests(unittest.TestCase):
    def test_chunk_local_actor_uses_global_exposure_evidence_and_assets(self):
        def load(name,file):
            spec=importlib.util.spec_from_file_location(name,BASE/'scripts/official'/file)
            result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
        contract=load('exposure_route_contract','map_lighting.py')
        profile=load('exposure_route_profile','map_game_lighting.py')
        with patch.dict(sys.modules,{'unreal':SimpleNamespace(),'map_lighting':contract,'map_game_lighting':profile}):
            importer=load('exposure_route_importer','ue_ensure_lighting.py')
        with tempfile.TemporaryDirectory() as temporary:
            global_root,data=ExposurePlanTests().setup_source(temporary)
            chunk_root=global_root/'Chunk_006';chunk_root.mkdir()
            local_row=dict(data['postprocess'][0],name='SourceForVideo',level='Original/TODLight.umap')
            local={'mapRoot':'DeltaForce/Content/Maps/BombDefusal_Test/Runtime/Tree/TreeStreamer.umap',
                'postprocess':[local_row]}
            self.assertFalse(exposure.build_plan(local,chunk_root,False)['eligible'])
            tag=importer.TAG+'post_'+hashlib.sha256((local_row['level']+local_row['name']).encode()).hexdigest()[:20]
            component=Object(settings=Object())
            actor=SimpleNamespace(tags=[tag],get_component_by_class=lambda cls:component,get_path_name=lambda:'/Game/Chunk/LocalPost')
            eas=SimpleNamespace(get_all_level_actors=lambda:[actor])
            apply_call=Mock(return_value={'passed':True})
            ue=SimpleNamespace(PostProcessComponent=object,SystemLibrary=SimpleNamespace(
                get_console_variable_int_value=lambda name:1,get_console_variable_float_value=lambda name:.78))
            with patch.object(importer,'unreal',ue),patch.dict(sys.modules,{
                'map_exposure':exposure,'ue_source_exposure':SimpleNamespace(apply_to_component=apply_call)}):
                report={}
                importer._source_exposure(eas,local,chunk_root,report,plan_data=data,plan_root=global_root)
            self.assertEqual(apply_call.call_count,1)
            self.assertIs(apply_call.call_args.args[1],component)
            plan=apply_call.call_args.args[2]
            self.assertEqual(plan['native_limits'],[13.5,14.5])
            self.assertEqual(Path(plan['curve']['file']).resolve(),(global_root/'source-render/curve.json').resolve())
            self.assertEqual(apply_call.call_args.kwargs['work_directory'],chunk_root/'source-render/exposure-curves')
            self.assertTrue(report['source_exposure']['eligible'])
            self.assertEqual(len(report['source_exposure']['applied']),1)


class NativeIBLCompatibilityTests(unittest.TestCase):
    """The explicit native unit adapter must never multiply its last result."""
    def fixture(self,temporary,ignore_setter=False,source_type='specified'):
        def load(name,file):
            spec=importlib.util.spec_from_file_location(name,BASE/'scripts/official'/file)
            result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
        contract=load('ibl_contract','map_lighting.py')
        profile=load('ibl_profile','map_game_lighting.py')
        with patch.dict(sys.modules,{'unreal':SimpleNamespace(),'map_lighting':contract,'map_game_lighting':profile}):
            importer=load('ibl_importer','ue_ensure_lighting.py')
        root,data=ExposurePlanTests().setup_source(temporary)
        raw=root/'source-render/tod.json';rows=json.loads(raw.read_text())
        rows[0]['value']['Properties']['TodExposure']['IBLCoef']=500
        raw.write_text(json.dumps(rows))
        data['postprocess'][0].update(level='Original/TODLight.umap',name='SourceForVideo')
        data['lights']=[{'Type':'Sky','Name':'AuthoredSky','Intensity':2,'Color':[1,1,1]}]
        source_before=json.dumps(data,sort_keys=True)
        post_row=data['postprocess'][0]
        post_tag=importer.TAG+'post_'+hashlib.sha256((post_row['level']+post_row['name']).encode()).hexdigest()[:20]
        light_tag=importer.TAG+next(contract.records(data))[0]
        post_component=Object(settings=Object())
        class Cube(Object):pass
        cube=Cube()
        light_component=Object(source_type=source_type,cubemap=cube,intensity=2)
        original_set=light_component.set_editor_property
        calls=[]
        def setter(name,value):
            calls.append((name,value))
            if not(ignore_setter and name=='intensity'):original_set(name,value)
        light_component.set_editor_property=setter
        post_class=type('PostComponent',(),{});light_class=type('SkyComponent',(),{})
        post_actor=SimpleNamespace(tags=[post_tag],get_component_by_class=lambda cls:post_component if cls is post_class else None,
            get_path_name=lambda:'/Game/Chunk/Post')
        sky_actor=SimpleNamespace(tags=[light_tag],get_component_by_class=lambda cls:light_component if cls is light_class else None,
            get_path_name=lambda:'/Game/Chunk/SourceSky')
        eas=SimpleNamespace(get_all_level_actors=lambda:[post_actor,sky_actor])
        ue=SimpleNamespace(PostProcessComponent=post_class,SkyLightComponent=light_class,TextureCube=Cube,
            SkyLightSourceType=SimpleNamespace(SLS_SPECIFIED_CUBEMAP='specified'),SystemLibrary=SimpleNamespace(
                get_console_variable_int_value=lambda name:0,get_console_variable_float_value=lambda name:.78))
        return importer,ue,eas,data,root,light_component,calls,source_before

    def test_native_ibl_adapter_is_idempotent_and_does_not_rewrite_source_energy(self):
        with tempfile.TemporaryDirectory() as temporary:
            importer,ue,eas,data,root,light,calls,source_before=self.fixture(temporary)
            with patch.object(importer,'unreal',ue),patch.dict(sys.modules,{
                'map_exposure':exposure,'ue_source_exposure':SimpleNamespace(apply_to_component=Mock(return_value={'passed':True}))}):
                reports=[]
                for _ in range(2):
                    report={};importer._source_exposure(eas,data,root,report);reports.append(report)
            self.assertEqual(light.values['intensity'],1000)
            self.assertEqual([value for name,value in calls if name=='intensity'],[1000,1000])
            self.assertEqual(data['lights'][0]['Intensity'],2)
            self.assertEqual(json.dumps(data,sort_keys=True),source_before)
            for report in reports:
                mapping=report['source_exposure']['native_ibl_unit_mapping'][0]
                self.assertEqual(mapping['source_intensity'],2)
                self.assertEqual(mapping['source_coefficient'],500)
                self.assertEqual(mapping['native_intensity'],1000)
                self.assertIn('compatibility',mapping['basis'])

    def test_native_ibl_silent_setter_failure_is_a_readback_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            importer,ue,eas,data,root,light,calls,_=self.fixture(temporary,ignore_setter=True)
            with patch.object(importer,'unreal',ue),patch.dict(sys.modules,{
                'map_exposure':exposure,'ue_source_exposure':SimpleNamespace(apply_to_component=Mock(return_value={'passed':True}))}):
                with self.assertRaisesRegex(RuntimeError,'IBL intensity readback mismatch'):
                    importer._source_exposure(eas,data,root,{})
            self.assertEqual(light.values['intensity'],2)
            self.assertEqual(data['lights'][0]['Intensity'],2)

    def test_native_ibl_adapter_does_not_scale_an_unresolved_scene_capture(self):
        with tempfile.TemporaryDirectory() as temporary:
            importer,ue,eas,data,root,light,calls,_=self.fixture(temporary,source_type='captured')
            with patch.object(importer,'unreal',ue),patch.dict(sys.modules,{
                'map_exposure':exposure,'ue_source_exposure':SimpleNamespace(apply_to_component=Mock(return_value={'passed':True}))}):
                importer._source_exposure(eas,data,root,{})
            self.assertEqual(light.values['intensity'],2)
            self.assertEqual(calls,[])


if __name__=='__main__':unittest.main()
