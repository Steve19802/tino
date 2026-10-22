'''Config and health exposure of the typst-pptx version.'''

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tino.routers import misc

_VERSION = 'typst-pptx 0.1.0 (typst 0.15.1)'


def _client():
    app = FastAPI()
    app.include_router(misc.router)
    return TestClient(app)


def test_config_reports_pptx_version(monkeypatch):
    monkeypatch.setattr(misc, '_PPTX_VERSION', _VERSION)
    assert _client().get('/api/config').json()['pptxVersion'] == _VERSION


def test_config_reports_null_when_absent(monkeypatch):
    monkeypatch.setattr(misc, '_PPTX_VERSION', None)
    assert _client().get('/api/config').json()['pptxVersion'] is None


def test_health_reports_pptx_version(monkeypatch):
    monkeypatch.setattr(misc, '_PPTX_VERSION', _VERSION)
    assert _client().get('/health').json()['typst_pptx'] == _VERSION
