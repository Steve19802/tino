'''Typst compiler service. Shells out to the system `typst` binary to produce SVG or PDF output.'''

import logging
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT = 30


@lru_cache
def typst_version() -> str | None:
    '''Return the installed Typst CLI version, or None if it can't be determined.'''
    try:
        return CompilerService.version()
    except Exception:  # pylint: disable=broad-exception-caught
        return None


class CompilerService:
    '''Compiles .typ files to SVG or PDF by invoking the Typst CLI.'''

    def __init__(self, data_dir: Path, package_dir: Path | None = None,
                 font_dir: Path | None = None):
        self.data_dir = data_dir
        self.package_dir = package_dir
        self.font_dir = font_dir

    @staticmethod
    def version() -> str:
        '''Return the installed Typst CLI version string.'''
        result = subprocess.run(
            ['typst', '--version'],
            capture_output=True, text=True, check=True,
        )

        return result.stdout.strip()

    def compile_svg(self, slug: str, path: str) -> list[str]:
        '''Compile a Typst file and return a list of SVG strings (one per page).

        Raises FileNotFoundError if the source file doesn't exist,
        or RuntimeError if compilation fails (with the stderr message).
        '''
        bucket_dir, source = self._resolve_source(slug, path)
        logger.debug('Compiling SVG for %s/%s', slug, path)

        return self._render_svgs(source, bucket_dir, slug)

    def compile_pdf(self, slug: str, path: str) -> Path:
        '''Compile a Typst file and return the path to the resulting PDF.

        Writes to a temporary file; the caller is responsible for deleting it
        (typically via a BackgroundTask on the FileResponse).
        Raises FileNotFoundError if the source file doesn't exist,
        or RuntimeError if compilation fails (with the stderr message).
        '''
        bucket_dir, source = self._resolve_source(slug, path)
        logger.info('Compiling PDF for %s/%s', slug, path)

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            output = Path(tmp.name)

        try:
            self._run(source, output, bucket_dir, slug)
        except Exception:
            output.unlink(missing_ok=True)
            raise

        return output

    # ── Internal ──

    def _render_svgs(self, source, bucket_dir, slug):
        '''Compile a source file to SVG and return one string per page.'''
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'page-{n}.svg'
            self._run(source, output, bucket_dir, slug, fmt='svg')

            return [
                svg_file.read_text(encoding='utf-8')
                for svg_file in sorted(Path(tmp).glob('page-*.svg'))
            ]

    def _font_paths(self, slug: str) -> list[Path]:
        '''Existing font directories for a bucket (bucket fonts first).'''
        paths = []
        bucket_fonts = self.data_dir / slug / 'fonts'
        if bucket_fonts.is_dir():
            paths.append(bucket_fonts)
        if self.font_dir and self.font_dir.is_dir():
            paths.append(self.font_dir)
        return paths

    def _resolve_source(self, slug, path):
        '''Validate that the source file exists and is inside the bucket.'''
        bucket_dir = (self.data_dir / slug).resolve()
        source     = (bucket_dir / path).resolve()

        if not source.is_relative_to(bucket_dir):
            raise FileNotFoundError(f'{path} is outside the bucket')

        if not source.is_file():
            raise FileNotFoundError(f'{path} not found in bucket {slug}')

        return bucket_dir, source

    def _run(self, source, output, root, slug, fmt=None):
        '''Build the typst compile command, run it, and raise on failure.'''
        result = subprocess.run(
            self._build_cmd(source, output, root, slug, fmt),
            cwd=str(root),
            capture_output=True, text=True,
            timeout=_COMPILE_TIMEOUT, check=False,
        )

        if result.returncode != 0:
            logger.warning('Compilation failed for %s: %s', source, result.stderr.strip())
            raise RuntimeError(result.stderr.strip() or 'Compilation failed')

    def _build_cmd(self, source, output, root, slug, fmt=None):
        '''Assemble the typst compile argument list.'''
        cmd = ['typst', 'compile']

        if fmt:
            cmd.extend(['--format', fmt])

        if self.package_dir:
            cmd.extend(['--package-path', str(self.package_dir)])

        # Font paths are passed as a single --font-path with directories joined
        # by the OS path separator. The bucket's fonts/ dir comes first so
        # bucket fonts take precedence over the instance-wide font directory.
        font_paths = [str(path) for path in self._font_paths(slug)]
        if font_paths:
            cmd.extend(['--font-path', os.pathsep.join(font_paths)])

        cmd.extend(['--root', str(root), str(source), str(output)])

        return cmd
