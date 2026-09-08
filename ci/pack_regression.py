"""Exercise real native pack creation and extension through the public CLI."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--blender',required=True)
parser.add_argument('--root',default='ci/out_pack')
args=parser.parse_args()
repository=Path(__file__).resolve().parents[1]
folder=Path(args.root).resolve()
inbox=folder/'work/eingang'; inbox.mkdir(parents=True,exist_ok=True)
(folder/'propforge.toml').write_text('[workspace]\nblender = '+json.dumps(str(Path(args.blender).resolve()))+'\n')
sources=repository/'ci/assets'

def run(name,first=False):
    shutil.copy2(sources/'pf_desk.glb',inbox/(name+'.glb'))
    job={'name':name,'profile':'standard','material':'WOOD_SOLID_MEDIUM','source_up':'y','center':'base',
         'textures':{role:str(sources/('pf_desk_'+suffix+'.png')) for role,suffix in
                     [('diffuse','albedo'),('normal','normal'),('roughness','roughness'),('metallic','metallic')]}}
    (inbox/(name+'.job.json')).write_text(json.dumps(job))
    command=[sys.executable,'-m','propforge.cli','convert','--root',str(folder),'--no-ask']
    if first: command+=['--pack','pf_ci_shared']
    subprocess.run(command,check=True,cwd=repository)
    out=folder/'work/ausgabe'
    result=json.loads((out/'native_check/native_result.json').read_text())
    assert result['status']=='passed'
    assert len(result['dictionaries']['pf_ci_shared']['textures'])==3
    return out,result

out,first=run('pf_pack_a',True)
first_hashes={t['dds_sha256'] for t in first['dictionaries']['pf_ci_shared']['textures']}
out,second=run('pf_pack_b')
assert set(second['props'])=={'pf_pack_a','pf_pack_b'}
assert first_hashes=={t['dds_sha256'] for t in second['dictionaries']['pf_ci_shared']['textures']}
assert second['props']['pf_pack_a']['samplers']==second['props']['pf_pack_b']['samplers']
pack=json.loads((out/'pack_result.json').read_text())
assert set(pack['files'])=={'pf_pack_a.ydr','pf_pack_b.ydr','pf_ci_shared.ytd','pf_ci_shared.ytyp'}
assert not list(inbox.glob('*.glb'))
before={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
(inbox/'pf_broken.glb').write_bytes(b'intentionally invalid GLB')
broken=json.loads((folder/'work/fertig/pf_pack_b.job.json').read_text())
broken['name']='pf_broken'
(inbox/'pf_broken.job.json').write_text(json.dumps(broken))
code=subprocess.run([sys.executable,'-m','propforge.cli','convert','--root',str(folder),'--no-ask'],cwd=repository).returncode
assert code!=0
after={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
assert before==after and (inbox/'pf_broken.glb').is_file()
(folder/'regression_result.json').write_text(json.dumps({'status':'passed','runs':2,'props':2,'textures':3,
    'shared_sampler_names':True,'old_texture_payloads_retained':True,'failed_run_preserved_all_output_bytes':True},indent=2))
print('NATIVE_PACK_REGRESSION_PASSED')
