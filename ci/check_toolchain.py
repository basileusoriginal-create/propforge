"""Run in Blender AFTER installing the add-on's own pinned dependencies."""
import bpy
import importlib.metadata
import json
import sys
import tomllib
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from propforge.sollumz_env import import_sollumz
pins=json.loads((root/'toolchain.lock.json').read_text())
assert '.'.join(map(str,bpy.app.version))==pins['blender'], 'Blender-Version weicht vom getesteten Stand ab'
addon=import_sollumz()
module=__import__(addon.module,fromlist=['*'])
manifest=tomllib.loads((Path(module.__file__).parent/'blender_manifest.toml').read_text())
assert manifest['version']==pins['sollumz_manifest'], 'Sollumz-Version weicht ab'
assert importlib.metadata.version('szio')==pins['szio']
if sys.platform=='win32': assert importlib.metadata.version('pymateria')==pins['pymateria']
properties=bpy.ops.sollumz.export_assets.get_rna_type().properties
assert 'target_formats' in properties and 'target_versions' in properties
print('TOOLCHAIN_PIN_CHECK_PASSED='+json.dumps({'blender':bpy.app.version_string,'sollumz':manifest['version'],'szio':pins['szio']}))
