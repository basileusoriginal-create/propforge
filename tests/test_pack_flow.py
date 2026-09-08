import argparse
import json
from pathlib import Path
from propforge import cli, workspace as ws
import pytest


def setup(tmp_path, monkeypatch, fail=None):
    w=ws.Workspace.load(tmp_path); w.ensure()
    mesh=w.inbox/'pf_test.glb'; mesh.write_bytes(b'fixture')
    ws.Job(name='pf_test',mesh=mesh,textures={'diffuse':'fixture.png'}).write()
    (w.out/'previous.txt').write_text('known good')
    calls=[]
    def step(name):
        def invoke(args):
            calls.append(name)
            (args.config.workdir/(name+'.txt')).write_text(name)
            return 1 if fail==name else 0
        return invoke
    for name in ('validate','textures','build','verify','pack'):
        monkeypatch.setattr(cli,'cmd_'+name,step(name))
    monkeypatch.setattr(cli.sys.stdin,'isatty',lambda:False)
    args=argparse.Namespace(root=str(tmp_path),blender='blender',texconv=None,
                            format='NATIVE',no_ask=False,ytd=None,embed=False,pack=None)
    return w,args,calls


@pytest.mark.parametrize('failed',['textures','build','verify','pack'])
def test_failed_step_preserves_output_and_input(tmp_path,monkeypatch,failed):
    w,args,calls=setup(tmp_path,monkeypatch,failed)
    assert cli.cmd_convert(args)==1
    assert sorted(p.name for p in w.out.iterdir())==['previous.txt']
    assert (w.inbox/'pf_test.glb').exists()
    assert (w.inbox/'pf_test.job.json').exists()
    assert not list(w.done.iterdir())


def test_all_stages_finish_before_archive(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    original=ws.Workspace.archive
    def archive(self,job):
        assert calls==['validate','textures','build','verify','pack']
        assert (w.out/'verify.txt').is_file()
        return original(self,job)
    monkeypatch.setattr(ws.Workspace,'archive',archive)
    assert cli.cmd_convert(args)==0
    assert (w.done/'pf_test.glb').exists()


def test_pack_mode_uses_merger_after_native_check(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    from propforge import pack_flow
    def assemble(config,blender,merge):
        assert calls==['validate','textures','build','verify']
        assert config.resource_name=='my_pack' and config.props[0].ytd=='my_pack'
        calls.append('assemble')
    monkeypatch.setattr(pack_flow,'assemble',assemble)
    args.pack='my_pack'
    assert cli.cmd_convert(args)==0
    assert calls[-1]=='assemble'


def test_remembered_pack_is_used_without_retyping(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    (w.out/'pack_result.json').write_text(json.dumps({'resource':'my_pack'}))
    from propforge import pack_flow
    def assemble(config,*_):
        assert config.resource_name=='my_pack'
        assert config.props[0].ytd=='my_pack'
    monkeypatch.setattr(pack_flow,'assemble',assemble)
    assert cli.cmd_convert(args)==0


def test_interrupted_publication_recovers_before_reading_pack_name(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    from propforge.transaction import DirectoryTransaction
    from propforge import pack_flow
    (w.out/'pack_result.json').write_text(json.dumps({'resource':'my_pack'}))
    tx=DirectoryTransaction(w.out)
    w.out.rename(tx.previous)
    abandoned=w.out.parent/(tx.prefix+'stage-interrupted')
    abandoned.mkdir()
    tx.journal.write_text(json.dumps({'target':str(w.out),'stage':str(abandoned)}))
    def assemble(config,*_):
        assert config.resource_name=='my_pack'
        assert (config.workdir/'previous.txt').read_text()=='known good'
        calls.append('assemble')
    monkeypatch.setattr(pack_flow,'assemble',assemble)
    assert cli.cmd_convert(args)==0
    assert calls[-1]=='assemble'
    assert (w.out/'previous.txt').read_text()=='known good'


def test_competing_convert_does_not_rewrite_jobs_before_lock(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    from propforge.transaction import DirectoryTransaction
    sidecar=w.inbox/'pf_test.job.json'
    before=sidecar.read_bytes()
    args.ytd='another_dictionary'
    with DirectoryTransaction(w.out):
        assert cli.cmd_convert(args)==1
    assert sidecar.read_bytes()==before
    assert calls==[]


def test_archive_sidecar_error_restores_source_pair(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    original=ws.shutil.move
    def move(source,target):
        if str(source).endswith('.job.json'): raise OSError('injected archive failure')
        return original(source,target)
    monkeypatch.setattr(ws.shutil,'move',move)
    with pytest.raises(OSError): w.archive(w.jobs()[0])
    assert (w.inbox/'pf_test.glb').exists() and (w.inbox/'pf_test.job.json').exists()


def test_source_inside_output_is_refused(tmp_path,monkeypatch):
    w,args,calls=setup(tmp_path,monkeypatch)
    config=w.to_config(w.jobs())
    config.workdir=w.root
    with pytest.raises(ValueError,match='getrennt'):
        cli._check_output_layout(config)


def test_cwxml_pack_does_not_create_fake_playable_resource(tmp_path):
    w=ws.Workspace.load(tmp_path)
    config=w.to_config([],export_format='CWXML')
    assert cli.cmd_pack(argparse.Namespace(config=config))==2
    assert not (w.out/'resources').exists()
