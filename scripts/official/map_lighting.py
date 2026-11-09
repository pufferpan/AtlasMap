"""The reference dfmap lights.json contract, in original UE centimetres.

No glTF-axis conversions or luminance guesses are applied to native UE lights.
"""
import hashlib
import json
import math

KINDS = {'point':'Point', 'spot':'Spot', 'rect':'Rect', 'directional':'Directional',
         'sky':'Sky', 'fog':'Fog'}

# Keep these source values in centimetres, including a meaningful zero. Unreal
# can expose the target UPROPERTY to get_editor_property without a Python attr.
DISTANCE_FIELDS = (('maxdrawdistance', 'MaxDrawDistance', 'max_draw_distance'),
                   ('maxdistancefaderange', 'MaxDistanceFadeRange', 'max_distance_fade_range'))


def postprocess_box(row):
    """Model bounds are local to the brush, including its nonzero origin."""
    transform=row.get('transform',{})
    location=transform.get('RelativeLocation',{})
    scale=transform.get('RelativeScale3D',{})
    rotation=transform.get('RelativeRotation',{})
    bounds=row.get('bounds')
    center=[float(location.get(k,0)) for k in ('X','Y','Z')]
    if not bounds:return center,None
    offset=[float(bounds.get('Origin',{}).get(k,0))*scale.get(k,1) for k in ('X','Y','Z')]
    pitch,yaw,roll=[math.radians(rotation.get(k,0)) for k in ('Pitch','Yaw','Roll')]
    cp,sp,cy,sy,cr,sr=math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw),math.cos(roll),math.sin(roll)
    matrix=((cp*cy,sr*sp*cy-cr*sy,-cr*sp*cy-sr*sy),
            (cp*sy,sr*sp*sy+cr*cy,cy*sr-cr*sp*sy),(sp,-sr*cp,cr*cp))
    center=[center[i]+sum(matrix[i][j]*offset[j] for j in range(3)) for i in range(3)]
    extent=[abs(float(bounds['BoxExtent'][k])*scale.get(k,1)) for k in ('X','Y','Z')]
    return center,extent


def vector(value, default, name):
    result = list(default if value is None else value)
    if len(result) != 3 or not all(math.isfinite(float(x)) for x in result):
        raise ValueError('Invalid source light ' + name)
    return [float(x) for x in result]


def records(data):
    """Keep source order and coincident instances, including zero intensities."""
    occurrences={}
    for index, original in enumerate(data.get('lights', [])):
        row = {str(key).lower(): value for key, value in original.items()}
        kind = KINDS.get(str(row.get('type', '')).lower())
        if not kind:
            raise ValueError('Unsupported source light type: ' + str(row.get('type')))
        row['type'] = kind
        row['loc'] = vector(row.get('loc'), [0,0,0], 'location')
        row['rot'] = vector(row.get('rot'), [0,0,0], 'rotation')
        row['color'] = vector(row.get('color'), [1,1,1], 'linear color')
        for name in ('intensity','radius','innercone','outercone','sourcewidth','sourceheight',
                     'maxdrawdistance','maxdistancefaderange'):
            if name in row and (not math.isfinite(float(row[name])) or
                    (name in ('radius','sourcewidth','sourceheight','maxdrawdistance','maxdistancefaderange') and float(row[name]) < 0)):
                raise ValueError('Invalid source light ' + name)
        source=row.get('source') or {}
        owner=(source.get('object') or {}).get('ObjectPath')
        identity=[source['level'],owner,row.get('name',''),kind] if source.get('level') else [index,row.get('name',''),kind]
        signature = json.dumps(identity, ensure_ascii=True)
        ordinal=occurrences.get(signature,0);occurrences[signature]=ordinal+1
        if ordinal:signature=json.dumps([*identity,ordinal],ensure_ascii=True)
        yield hashlib.sha256(signature.encode()).hexdigest()[:24], row
