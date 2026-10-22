'''compile_pptx service tests against a fake typst-pptx binary.'''

import pytest

from tino.services import compiler


@pytest.fixture
def bucket(tmp_path):
    '''A bucket dir with a single .typ source; returns (data_dir, slug).'''
    slug = 'demo'
    bucket_dir = tmp_path / slug
    bucket_dir.mkdir()
    (bucket_dir / 'main.typ').write_text('= Hello\n', encoding='utf-8')
    return tmp_path, slug


def _service(data_dir, fake_binary, monkeypatch, exit_code=None):
    monkeypatch.setattr(compiler.config, 'TINO_PPTX_BINARY', str(fake_binary))
    if exit_code is None:
        monkeypatch.delenv('FAKE_PPTX_EXIT', raising=False)
    else:
        monkeypatch.setenv('FAKE_PPTX_EXIT', str(exit_code))
    compiler.pptx_binary.cache_clear()
    compiler.pptx_version.cache_clear()
    return compiler.CompilerService(data_dir)


@pytest.fixture(autouse=True)
def _clear_pptx_cache():
    yield
    compiler.pptx_binary.cache_clear()
    compiler.pptx_version.cache_clear()


def test_success(bucket, fake_pptx_binary, monkeypatch):
    data_dir, slug = bucket
    service = _service(data_dir, fake_pptx_binary, monkeypatch)
    path, report = service.compile_pptx(slug, 'main.typ')
    try:
        assert path.exists()
        assert path.read_bytes() == b'fake pptx'
        assert path.suffix == '.pptx'
        assert report['typst_pptx'] == '0.1.0'
        assert len(report['baked']) == 1
    finally:
        path.unlink(missing_ok=True)


def test_export_error(bucket, fake_pptx_binary, monkeypatch):
    data_dir, slug = bucket
    service = _service(data_dir, fake_pptx_binary, monkeypatch, exit_code=2)
    with pytest.raises(compiler.CompileError) as excinfo:
        service.compile_pptx(slug, 'main.typ')
    diagnostics = excinfo.value.diagnostics
    assert any(d['severity'] == 'error' for d in diagnostics)
    assert any('Touying 0.8' in d['message'] for d in diagnostics)


def test_missing_source(bucket, fake_pptx_binary, monkeypatch):
    data_dir, slug = bucket
    service = _service(data_dir, fake_pptx_binary, monkeypatch)
    with pytest.raises(FileNotFoundError):
        service.compile_pptx(slug, 'nope.typ')


def test_bad_animations(bucket, fake_pptx_binary, monkeypatch):
    data_dir, slug = bucket
    service = _service(data_dir, fake_pptx_binary, monkeypatch)
    with pytest.raises(ValueError):
        service.compile_pptx(slug, 'main.typ', animations='bogus')
