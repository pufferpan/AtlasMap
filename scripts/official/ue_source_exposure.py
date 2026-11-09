"""Apply a validated source exposure plan to an existing postprocess component."""
from pathlib import Path
import hashlib,json,math
try:
    from map_exposure import curve_samples
except ModuleNotFoundError:
    from scripts.official.map_exposure import curve_samples


def apply_to_component(ue,component,plan,destination,work_directory=None):
    if not plan.get('eligible'):raise ValueError('Source exposure plan is not eligible: '+repr(plan.get('errors') or plan.get('skipped_missing')))
    source=plan['curve'];name='C_SourceExposure_'+hashlib.sha256(source['source_package'].encode()).hexdigest()[:16]
    folder=Path(work_directory or Path(source['file']).parent)
    folder.mkdir(parents=True,exist_ok=True);csv=folder/(name+'.csv')
    samples=curve_samples(source['keys'])
    csv.write_text(''.join(f'{x:.8f},{y:.10f}\n' for x,y in samples),encoding='utf-8')
    curve=ue.load_asset(destination+'/'+name)
    metadata=ue.EditorAssetLibrary
    if curve is None or metadata.get_metadata_tag(curve,'SourceExposureSHA256')!=source['sha256']:
        factory=ue.CSVImportFactory()
        factory.set_editor_property('automated_import_settings',ue.CSVImportSettings(
            import_type=ue.CSVImportType.ECSV_CURVE_FLOAT,import_curve_interp_mode=ue.RichCurveInterpMode.RCIM_LINEAR))
        task=ue.AssetImportTask();task.filename=str(csv);task.destination_path=destination;task.destination_name=name
        task.factory=factory;task.automated=True;task.replace_existing=True;task.save=True
        ue.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        curve=ue.load_asset(destination+'/'+name)
        if curve is None:raise RuntimeError('Source exposure curve import failed')
        metadata.set_metadata_tag(curve,'SourceExposureSHA256',source['sha256'])
        metadata.set_metadata_tag(curve,'SourceExposureCurve',source['source_package'])
        metadata.set_metadata_tag(curve,'SourceExposureOriginalKeys',json.dumps(source['keys']))
        if not metadata.save_loaded_asset(curve):raise RuntimeError('Source exposure curve save failed')
    for time,value in samples[::max(1,len(samples)//32)]:
        if not math.isclose(float(curve.get_float_value(time)),value,abs_tol=2e-5):
            raise RuntimeError('Source exposure curve sample readback mismatch')
    values={'auto_exposure_method':ue.AutoExposureMethod.AEM_HISTOGRAM,
        'auto_exposure_min_brightness':plan['native_limits'][0],
        'auto_exposure_max_brightness':plan['native_limits'][1],
        'auto_exposure_bias':plan['bias_ev'],'auto_exposure_bias_curve':curve}
    meter=plan.get('meter_mask')
    if meter:
        relative=meter['texture']['RelativePath'];base=Path(meter['base_directory']).resolve()
        filename=(base/relative).resolve()
        if not filename.is_relative_to(base) or not filename.is_file():raise ValueError('Invalid source exposure meter file')
        identity='T_SourceExposureMeter_'+hashlib.sha256(meter['source_package'].encode()).hexdigest()[:16]
        texture=ue.load_asset(destination+'/'+identity)
        file_hash=hashlib.sha256(filename.read_bytes()).hexdigest()
        if texture is None or metadata.get_metadata_tag(texture,'SourceExposureSHA256')!=file_hash:
            task=ue.AssetImportTask();task.filename=str(filename);task.destination_path=destination;task.destination_name=identity
            task.automated=True;task.replace_existing=True;task.save=True
            ue.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
            texture=ue.load_asset(destination+'/'+identity)
            if texture is None:raise RuntimeError('Source exposure meter import failed')
            texture.set_editor_property('srgb',False)
            texture.set_editor_property('compression_settings',ue.TextureCompressionSettings.TC_EDITOR_ICON)
            metadata.set_metadata_tag(texture,'SourceExposureSHA256',file_hash)
            if not metadata.save_loaded_asset(texture):raise RuntimeError('Source exposure meter save failed')
        values['auto_exposure_meter_mask']=texture
    settings=component.get_editor_property('settings')
    for key,value in values.items():
        settings.set_editor_property('override_'+key,True);settings.set_editor_property(key,value)
    component.set_editor_property('settings',settings)
    check=component.get_editor_property('settings');readback={}
    for key,expected in values.items():
        actual=check.get_editor_property(key)
        matched=math.isclose(float(actual),expected,rel_tol=1e-6,abs_tol=1e-5) if isinstance(expected,(int,float)) else actual==expected
        if not check.get_editor_property('override_'+key) or not matched:raise RuntimeError('Source exposure readback mismatch: '+key)
        readback[key]=actual.get_path_name() if isinstance(actual,ue.Object) else str(actual) if not isinstance(actual,(str,int,float,bool)) else actual
    return {'source_ev_limits':plan['source_ev_limits'],'native_limits':plan['native_limits'],
        'bias_ev':plan['bias_ev'],'curve':curve.get_path_name(),'curve_samples':len(samples),
        'native_readback':readback,'meter_mask_changed':bool(meter),'passed':True}
