'''Compile router tests for the PowerPoint endpoint.'''

import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tino.dependencies import get_compiler_service, require_viewer
from tino.models import User
from tino.routers import compile as compile_router
from tino.services.compiler import CompileError

_PPTX_MEDIA = (
    'application/vnd.openxmlformats-officedocument.presentationml.presentation'
)


class FakeService:
    '''Stands in for CompilerService: returns a temp file or raises.'''

    def __init__(self, error=None, baked=2):
        self.error = error
        self.baked = baked

    def compile_pptx(self, slug, path, animations='auto'):  # pylint: disable=unused-argument
        if self.error is not None:
            raise self.error
        handle, name = tempfile.mkstemp(suffix='.pptx')
        Path(name).write_bytes(b'pptx-bytes')
        return Path(name), {'baked': [{} for _ in range(self.baked)]}


def _client(service, monkeypatch, available=True):
    app = FastAPI()
    app.include_router(compile_router.router)
    app.dependency_overrides[require_viewer] = lambda: User(
        username='tester', email='t@example.com', groups=[])
    app.dependency_overrides[get_compiler_service] = lambda: service
    monkeypatch.setattr(
        compile_router, 'pptx_version',
        lambda: 'typst-pptx 0.1.0 (typst 0.15.1)' if available else None)
    return TestClient(app)


def test_ok(monkeypatch):
    client = _client(FakeService(), monkeypatch)
    res = client.get('/api/buckets/demo/compile/pptx/main.typ')
    assert res.status_code == 200
    assert res.content == b'pptx-bytes'
    assert res.headers['content-type'] == _PPTX_MEDIA
    assert res.headers['X-Tino-Pptx-Fallbacks'] == '2'


def test_not_found(monkeypatch):
    client = _client(FakeService(error=FileNotFoundError('nope')), monkeypatch)
    assert client.get('/api/buckets/demo/compile/pptx/main.typ').status_code == 404


def test_compile_error(monkeypatch):
    error = CompileError('error: boom', [
        {'severity': 'error', 'message': 'boom', 'file': 'main.typ',
         'line': 1, 'column': 1}])
    client = _client(FakeService(error=error), monkeypatch)
    res = client.get('/api/buckets/demo/compile/pptx/main.typ')
    assert res.status_code == 422
    assert res.json()['detail']['diagnostics'][0]['message'] == 'boom'


def test_bad_animations(monkeypatch):
    client = _client(FakeService(error=ValueError('bad')), monkeypatch)
    res = client.get('/api/buckets/demo/compile/pptx/main.typ?animations=bogus')
    assert res.status_code == 400


def test_unavailable(monkeypatch):
    client = _client(FakeService(), monkeypatch, available=False)
    assert client.get('/api/buckets/demo/compile/pptx/main.typ').status_code == 501
