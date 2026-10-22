'''Speaker notes read from a document's pdfpc metadata.'''

import json
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tino.dependencies import get_compiler_service, require_viewer
from tino.models import User
from tino.routers import notes as notes_router
from tino.services.compiler import CompilerService, parse_notes

#: `typst eval` output for a real four-slide Touying deck: a title slide, a slide
#: whose note repeats on each of its animation steps, a slide with no note, and a
#: slide with a bulleted note.
_PDFPC = json.dumps({
    'pdfpcFormat': 2,
    'disableMarkdown': False,
    'pages': [
        {'overlay': 0, 'idx': 0, 'label': '1'},
        {'note': 'Remember to smile.', 'overlay': 0, 'idx': 1, 'label': '2'},
        {'note': 'Remember to smile.', 'overlay': 1, 'idx': 2, 'label': '2'},
        {'overlay': 0, 'idx': 3, 'label': '3'},
        {'note': '+ One\n+ Two', 'overlay': 0, 'idx': 4, 'label': '4'},
    ],
})

_NOTES = [None, 'Remember to smile.', 'Remember to smile.', None, '+ One\n+ Two']


def test_notes_are_one_per_page():
    assert parse_notes(_PDFPC) == _NOTES


def test_notes_absent():
    assert parse_notes('') == []
    assert parse_notes('not json at all') == []
    assert parse_notes('[]') == []


def test_notes_without_pages():
    assert parse_notes(json.dumps({'pdfpcFormat': 2})) == []
    assert parse_notes(json.dumps({'pages': 'nope'})) == []


def test_notes_skip_malformed_pages():
    payload = json.dumps({'pages': [{'note': 'kept'}, 'junk', {'idx': 2}]})
    assert parse_notes(payload) == ['kept', None, None]


class FakeService:
    '''Stands in for CompilerService: returns notes or raises.'''

    def __init__(self, notes=None, error=None):
        self.notes = notes if notes is not None else []
        self.error = error

    def compile_notes(self, slug, path):  # pylint: disable=unused-argument
        if self.error is not None:
            raise self.error
        return self.notes


def _client(service):
    app = FastAPI()
    app.include_router(notes_router.router)
    app.dependency_overrides[require_viewer] = lambda: User(
        username='tester', email='t@example.com', groups=[])
    app.dependency_overrides[get_compiler_service] = lambda: service
    return TestClient(app)


def test_route_returns_notes():
    service = FakeService(['a', None])
    res = _client(service).get('/api/buckets/demo/notes/decks/main.typ')
    assert res.status_code == 200
    assert res.json() == {'notes': ['a', None]}


def test_route_is_empty_without_metadata():
    res = _client(FakeService([])).get('/api/buckets/demo/notes/main.typ')
    assert res.status_code == 200
    assert res.json() == {'notes': []}


def test_route_not_found():
    service = FakeService(error=FileNotFoundError('nope'))
    assert _client(service).get('/api/buckets/demo/notes/main.typ').status_code == 404


def _fake_typst(path, stdout, code=0):
    '''Write a `typst` stub that logs its arguments and prints *stdout*.'''
    path.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "$@" > "{path}.args"\n'
        f"cat <<'JSON'\n{stdout}\nJSON\n"
        f'exit {code}\n',
        encoding='utf-8',
    )
    path.chmod(0o755)


def _bucket(tmp_path):
    bucket = tmp_path / 'demo'
    bucket.mkdir()
    (bucket / 'main.typ').write_text('= Title', encoding='utf-8')
    return bucket


def test_service_runs_the_query(tmp_path, monkeypatch):
    _bucket(tmp_path)
    binary = tmp_path / 'typst'
    _fake_typst(binary, _PDFPC)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')

    service = CompilerService(data_dir=tmp_path)
    assert service.compile_notes('demo', 'main.typ') == _NOTES

    args = Path(f'{binary}.args').read_text(encoding='utf-8').splitlines()
    assert args[:3] == ['eval', '--format', 'json']
    assert args[-1] == 'query(<pdfpc-file>).first().value'
    assert '--in' in args
    assert '--root' in args


def test_service_without_metadata(tmp_path, monkeypatch):
    _bucket(tmp_path)
    binary = tmp_path / 'typst'
    _fake_typst(binary, 'error: array is empty', code=1)
    monkeypatch.setenv('PATH', f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')

    service = CompilerService(data_dir=tmp_path)
    assert service.compile_notes('demo', 'main.typ') == []


def test_service_without_typst(tmp_path, monkeypatch):
    _bucket(tmp_path)
    monkeypatch.setenv('PATH', str(tmp_path))

    service = CompilerService(data_dir=tmp_path)
    assert service.compile_notes('demo', 'main.typ') == []


def test_service_missing_source(tmp_path):
    service = CompilerService(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        service.compile_notes('demo', 'nope.typ')
