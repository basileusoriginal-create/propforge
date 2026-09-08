import json
import os

import pytest

from propforge.transaction import DirectoryTransaction


def test_failure_keeps_previous_and_discards_candidate(tmp_path):
    target=tmp_path/'out'; target.mkdir(); (target/'data').write_text('old')
    with pytest.raises(RuntimeError):
        with DirectoryTransaction(target) as tx:
            (tx.stage/'data').write_text('new')
            raise RuntimeError('failed build')
    assert (target/'data').read_text()=='old'
    assert not list(tmp_path.glob('.out.pf-stage-*'))


def test_publishes_whole_tree_and_preserves_previous(tmp_path):
    target=tmp_path/'out'; target.mkdir(); (target/'data').write_text('old')
    with DirectoryTransaction(target,relocate=True) as tx:
        (tx.stage/'data').write_text('new')
        (tx.stage/'path.json').write_text(json.dumps({'path':str(tx.stage/'data')}))
        previous=tx.previous
        tx.publish()
    assert (target/'data').read_text()=='new'
    assert (previous/'data').read_text()=='old'
    assert json.loads((target/'path.json').read_text())['path']==str(target/'data')


def test_rename_failure_restores_previous(tmp_path,monkeypatch):
    target=tmp_path/'out'; target.mkdir(); (target/'data').write_text('old')
    original=os.replace
    with pytest.raises(OSError):
        with DirectoryTransaction(target) as tx:
            (tx.stage/'data').write_text('new')
            def fail(source,destination):
                if source==tx.stage: raise OSError('simulated publication failure')
                original(source,destination)
            monkeypatch.setattr(os,'replace',fail)
            tx.publish()
    assert (target/'data').read_text()=='old'


@pytest.mark.parametrize('first',[False,True])
def test_recovers_interrupted_rename(tmp_path,first):
    target=tmp_path/'out'
    previous=tmp_path/'.out.pf-previous'
    stage=tmp_path/'.out.pf-stage-interrupted'; stage.mkdir(); (stage/'data').write_text('new')
    if not first:
        previous.mkdir(); (previous/'data').write_text('old')
    (tmp_path/'.out.pf-journal.json').write_text(json.dumps({'target':str(target),'stage':str(stage)}))
    with DirectoryTransaction(target) as tx:
        assert (target/'data').read_text()==('new' if first else 'old')
    assert not stage.exists()


def test_second_writer_is_rejected(tmp_path):
    with DirectoryTransaction(tmp_path/'out'):
        with pytest.raises(RuntimeError,match='gesperrt'):
            with DirectoryTransaction(tmp_path/'out'): pass


def test_forged_journal_cannot_move_or_remove_unrelated_folder(tmp_path):
    target=tmp_path/'out'; other=tmp_path/'keep'; other.mkdir()
    (tmp_path/'.out.pf-journal.json').write_text(json.dumps({'target':str(target),'stage':str(other)}))
    with pytest.raises(RuntimeError,match='Unsicheres'):
        with DirectoryTransaction(target): pass
    assert other.is_dir()
