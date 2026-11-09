"""Persist dependencies of software Lumen before the editor process starts."""
from pathlib import Path
import re

RENDERER_SETTINGS = {
    'r.DynamicGlobalIlluminationMethod': '1',
    'r.ReflectionMethod': '1',
    'r.GenerateMeshDistanceFields': 'True',
}
SECTION = '/Script/Engine.RendererSettings'


def headless_renderer_args():
    """Override renderer setup before engine startup, for this process only.

    r.GenerateMeshDistanceFields is read-only after startup. ExecCmds or a
    Python console command cannot safely disable its NullRHI allocations.
    Keep the project's normal editor/Lumen configuration unchanged.
    """
    settings = ('r.GenerateMeshDistanceFields=False',
                'r.DynamicGlobalIlluminationMethod=0', 'r.ReflectionMethod=0')
    return ['-ini:Engine:' + ','.join('['+SECTION+']:'+value for value in settings)]


def ensure_game_renderer(project):
    project = Path(project)
    if not project.is_file():
        raise FileNotFoundError('UE 工程不存在：'+str(project))
    path = project.parent/'Config/DefaultEngine.ini'
    text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
    output = []
    in_section = False
    found = False
    written = set()
    def missing():
        for key,value in RENDERER_SETTINGS.items():
            if key not in written:
                output.append(key+'='+value)
                written.add(key)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if in_section:missing()
            in_section = stripped[1:-1].lower()==SECTION.lower()
            found = found or in_section
        match = re.match(r'\s*([^;#=]+?)\s*=',line) if in_section else None
        key = next((k for k in RENDERER_SETTINGS if match and k.lower()==match[1].lower()),None)
        if key:
            if key not in written:output.append(key+'='+RENDERER_SETTINGS[key]);written.add(key)
        else:output.append(line)
    if in_section:missing()
    if not found:
        output.extend(['','['+SECTION+']'])
        missing()
    updated='\n'.join(output)+'\n'
    if updated!=text:
        path.parent.mkdir(parents=True,exist_ok=True)
        # Keep an inspectable copy of the original project config, once.
        backup=path.with_suffix('.ini.atlasmap-backup')
        if path.exists() and not backup.exists():backup.write_bytes(path.read_bytes())
        path.write_bytes(updated.encode('utf-8'))
    return dict(RENDERER_SETTINGS)
