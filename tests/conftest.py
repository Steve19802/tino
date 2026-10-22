'''Shared pytest fixtures.'''

import stat

import pytest

#: A stand-in for the typst-pptx CLI. ``--version`` prints the expected line;
#: ``compile`` writes the output and ``--report`` files, emits a warning line,
#: and exits non-zero when ``FAKE_PPTX_EXIT`` is set.
_FAKE_BINARY = """#!/usr/bin/env bash
set -eu
if [[ "${1:-}" == "--version" ]]; then
  echo "typst-pptx 0.1.0 (typst 0.15.1)"
  exit 0
fi
report=""
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "--report" ]]; then report="$arg"; fi
  prev="$arg"
  out="$arg"
done
echo "warning: exported as a picture: scaled, skewed or mirrored text" >&2
if [[ "${FAKE_PPTX_EXIT:-0}" != "0" ]]; then
  echo "error: typst-pptx needs Touying 0.8 or newer (found 0.7.4)" >&2
  echo "  = hint: update the import to @preview/touying:0.8.0" >&2
  exit "${FAKE_PPTX_EXIT}"
fi
printf 'fake pptx' > "$out"
if [[ -n "$report" ]]; then
  printf '%s' '{"typst_pptx":"0.1.0","baked":[{"slide":1,"reason":"equation"}]}' > "$report"
fi
exit 0
"""


@pytest.fixture(scope='session')
def fake_pptx_binary(tmp_path_factory):
    '''Write an executable that stands in for the typst-pptx CLI.'''
    path = tmp_path_factory.mktemp('bin') / 'typst-pptx'
    path.write_text(_FAKE_BINARY, encoding='utf-8')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path
