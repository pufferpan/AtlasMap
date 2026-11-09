"""Explicit stock-UE compatibility presets; never change exported source values."""
import json
import math
from pathlib import Path


def build_profile(data, root=None, mode='game'):
    if mode not in ('game', 'source'):
        raise ValueError('Unknown render profile: '+str(mode))
    name=data.get('mapRoot','').replace('\\','/').split(' + ')[-1].rstrip('/').split('/')[-1]
    authored=any(row.get('properties',{}).get('Settings',{}).get('bOverride_AutoExposureBias')
                 for row in data.get('postprocess',[]))
    settings={'enabled':mode=='game','map':name,'mode':mode,
              'fog_only_scattering_cap':0.02,
              'exposure_bias_ev':None if authored else (-1.0 if name=='CollectionRoom' else 0.0),
              'local_highlight_contrast':0.8,'local_shadow_contrast':0.9,
              'basis':'Stock-UE compatibility preset, not a recovered game shader or reference-image match',
              'source_exposure_preserved':authored}
    path=Path(root)/'game-lighting.json' if root else None
    if settings['enabled'] and path and path.is_file():
        overrides=json.loads(path.read_text(encoding='utf-8-sig'))
        allowed={'fog_only_scattering_cap','exposure_bias_ev','local_highlight_contrast','local_shadow_contrast'}
        if not isinstance(overrides,dict) or set(overrides)-allowed:
            raise ValueError('Unknown game-lighting.json fields')
        for key,value in overrides.items():
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
                raise ValueError('Invalid lighting profile value: '+key)
            low,high=(-10,10) if key=='exposure_bias_ev' else (0,1)
            if not low<=value<=high:
                raise ValueError('Lighting profile value out of range: '+key)
            settings[key]=float(value)
        settings['basis']='Explicit per-map game-lighting.json overrides'
        settings['explicit_override_fields']=sorted(overrides)
        if 'exposure_bias_ev' in overrides:settings['source_exposure_preserved']=False
    return settings
