'''Command building and typst-pptx version parsing.'''

from pathlib import Path

from tino.services import compiler


def test_build_cmd(tmp_path):
    service = compiler.CompilerService(tmp_path, Path('/pkg'), None)
    cmd = service._build_cmd('src.typ', 'out.pdf', tmp_path, 'bucket')
    assert cmd[:2] == ['typst', 'compile']
    assert cmd[-4:] == ['--root', str(tmp_path), 'src.typ', 'out.pdf']
    assert cmd[cmd.index('--package-path') + 1] == '/pkg'


def test_build_cmd_includes_fonts(tmp_path):
    font_dir = tmp_path / 'bucket' / 'fonts'
    font_dir.mkdir(parents=True)
    service = compiler.CompilerService(tmp_path, None, None)
    cmd = service._build_cmd('src.typ', 'out.pdf', tmp_path, 'bucket')
    assert cmd[cmd.index('--font-path') + 1] == str(font_dir)


def test_build_pptx_cmd(tmp_path):
    service = compiler.CompilerService(tmp_path, None, None)
    cmd = service._build_pptx_cmd('/bin/typst-pptx', 'src.typ', 'out.pptx',
                                  tmp_path, 'bucket', 'auto', '/tmp/report.json')
    assert cmd[:2] == ['/bin/typst-pptx', 'compile']
    assert cmd[cmd.index('--diagnostic-format') + 1] == 'short'
    assert cmd[cmd.index('--animations') + 1] == 'auto'
    assert cmd[cmd.index('--report') + 1] == '/tmp/report.json'
    assert cmd[-2:] == ['src.typ', 'out.pptx']


def test_pptx_version(fake_pptx_binary, monkeypatch):
    monkeypatch.setattr(compiler.config, 'TINO_PPTX_BINARY', str(fake_pptx_binary))
    compiler.pptx_binary.cache_clear()
    compiler.pptx_version.cache_clear()
    try:
        assert compiler.pptx_version() == 'typst-pptx 0.1.0 (typst 0.15.1)'
    finally:
        compiler.pptx_binary.cache_clear()
        compiler.pptx_version.cache_clear()


def test_pptx_version_missing(monkeypatch):
    monkeypatch.setattr(compiler.config, 'TINO_PPTX_BINARY', 'no-such-typst-pptx-xyz')
    compiler.pptx_binary.cache_clear()
    compiler.pptx_version.cache_clear()
    try:
        assert compiler.pptx_version() is None
    finally:
        compiler.pptx_binary.cache_clear()
        compiler.pptx_version.cache_clear()
