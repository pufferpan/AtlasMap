"""Save Blender's material-preview HDRI as a UE-readable HDR environment."""
import bpy
import json
from pathlib import Path
source=Path('D:/blender/Blender 5.2/5.2/datafiles/studiolights/world/forest.exr')
root=Path('D:/AtlasMap-tooling/out/Iceland/ue_transfer/20261031')
image=bpy.data.images.load(str(source),check_existing=False)
_ = image.pixels[0]
image.file_format='HDR';image.filepath_raw=str(root/'forest_environment.hdr');image.save()
(root/'environment.json').write_text(json.dumps({'source':str(source),'file':str(root/'forest_environment.hdr'),'size':list(image.size),'colourspace':image.colorspace_settings.name},indent=2))
