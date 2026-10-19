'''Typst compiler service. Shells out to the `typst` CLI to produce SVG, PDF, or PNG output.'''

import logging
import math
import re
import subprocess
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

#: Wall-clock limit for SVG/PDF compilation.
_COMPILE_TIMEOUT = 30
#: Wall-clock limit for PNG rasterisation, which is much slower than PDF.
_IMAGE_TIMEOUT = 120

#: Allowed pixels-per-inch range and default for PNG output.
_DEFAULT_PPI = 144
_MIN_PPI = 36
_MAX_PPI = 300

#: Default bounds and spacing for the overview grid image.
_OVERVIEW_MAX_WIDTH = 2000
_OVERVIEW_MAX_HEIGHT = 2000
_OVERVIEW_BACKGROUND = (200, 200, 200)
_OVERVIEW_GUTTER = 8

#: Typst error/warning header and its ``┌─ file:line:col`` location line.
_SEVERITY_RE = re.compile(r'^(error|warning): ?(.*)$')
_HELP_RE     = re.compile(r'^help:')
_LOCATION_RE = re.compile(r'^\s*┌─\s+(.*):(\d+):(\d+)\s*$')


class CompileError(RuntimeError):
    '''Failed Typst compilation holding its diagnostics and raw stderr.'''

    def __init__(self, stderr: str, diagnostics: list[dict]):
        super().__init__(stderr or 'Compilation failed')
        self.diagnostics = diagnostics


def parse_diagnostics(stderr: str) -> list[dict]:
    '''Pull the individual errors/warnings out of Typst's stderr.

    Each entry is ``{severity, message, file, line, column}``; file/line/column
    are None when Typst reports no position.
    '''
    diagnostics: list[dict] = []
    current: dict | None = None

    for raw_line in stderr.splitlines():
        severity = _SEVERITY_RE.match(raw_line)
        if severity:
            current = {
                'severity': severity.group(1),
                'message': severity.group(2).strip(),
                'file': None, 'line': None, 'column': None,
            }
            diagnostics.append(current)
            continue

        # Skip help blocks, but let them close the current diagnostic.
        if _HELP_RE.match(raw_line):
            current = None
            continue

        location = _LOCATION_RE.match(raw_line)
        if location and current and current['file'] is None:
            current['file']   = location.group(1)
            current['line']   = int(location.group(2))
            current['column'] = int(location.group(3))

    return diagnostics


def _flatten_png(data: bytes) -> Image.Image:
    '''Decode *data* and flatten any transparency onto white.'''
    image = Image.open(BytesIO(data)).convert('RGBA')
    flat = Image.new('RGB', image.size, (255, 255, 255))
    flat.paste(image, mask=image.getchannel('A'))
    return flat


def _compose_overview(pages: list[bytes], max_width: int, max_height: int) -> bytes:
    '''Compose page PNGs into a single overview grid PNG.

    Pages are laid out in a near-square grid and scaled to fit within
    *max_width* × *max_height* on a neutral background.
    '''
    columns = math.ceil(math.sqrt(len(pages)))
    rows = math.ceil(len(pages) / columns)
    cell_width = max(1, (max_width - _OVERVIEW_GUTTER * (columns + 1)) // columns)
    cell_height = max(1, (max_height - _OVERVIEW_GUTTER * (rows + 1)) // rows)
    canvas = Image.new(
        'RGB',
        (_OVERVIEW_GUTTER + columns * (cell_width + _OVERVIEW_GUTTER),
         _OVERVIEW_GUTTER + rows * (cell_height + _OVERVIEW_GUTTER)),
        _OVERVIEW_BACKGROUND,
    )

    for index, data in enumerate(pages):
        tile = _flatten_png(data)
        tile.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
        left = _OVERVIEW_GUTTER + (index % columns) * (cell_width + _OVERVIEW_GUTTER)
        top = _OVERVIEW_GUTTER + (index // columns) * (cell_height + _OVERVIEW_GUTTER)
        canvas.paste(tile, (left + (cell_width - tile.width) // 2,
                            top + (cell_height - tile.height) // 2))

    buffer = BytesIO()
    canvas.save(buffer, format='PNG')
    return buffer.getvalue()


def zip_pngs(pages: list[bytes], overview: bytes | None = None) -> bytes:
    '''Zip page PNGs as ``page_N.png`` (plus ``overview.png`` when given).'''
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, data in enumerate(pages, start=1):
            archive.writestr(f'page_{index}.png', data)
        if overview is not None:
            archive.writestr('overview.png', overview)

    return buffer.getvalue()


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

        return self._render_svgs(source, bucket_dir)

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
            self._run(source, output, bucket_dir)
        except Exception:
            output.unlink(missing_ok=True)
            raise

        return output

    def compile_png(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, slug: str, path: str, ppi: int = _DEFAULT_PPI,
        overview: bool = False, max_width: int = _OVERVIEW_MAX_WIDTH,
        max_height: int = _OVERVIEW_MAX_HEIGHT,
    ) -> dict:
        '''Compile a Typst file and return one PNG per page.

        Returns ``{'pages': [bytes, ...], 'overview': bytes | None}``: *pages*
        holds one PNG per page, and *overview* a grid image of all pages (or
        None) when *overview* is requested.
        Raises ValueError for an out-of-range *ppi*, FileNotFoundError if the
        source is missing, or CompileError if compilation fails.
        '''
        if not _MIN_PPI <= ppi <= _MAX_PPI:
            raise ValueError(f'ppi must be between {_MIN_PPI} and {_MAX_PPI}')
        bucket_dir, source = self._resolve_source(slug, path)
        logger.info('Compiling PNG for %s/%s (ppi=%d)', slug, path, ppi)

        pages = self._render_pngs(source, bucket_dir, ppi)
        grid = _compose_overview(pages, max_width, max_height) if overview and pages else None

        return {'pages': pages, 'overview': grid}

    # ── Internal ──

    def _render_svgs(self, source, bucket_dir):
        '''Compile a source file to SVG and return one string per page.'''
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'page-{n}.svg'
            self._run(source, output, bucket_dir, fmt='svg')

            return [
                svg_file.read_text(encoding='utf-8')
                for svg_file in sorted(Path(tmp).glob('page-*.svg'))
            ]

    def _render_pngs(self, source, bucket_dir, ppi):
        '''Compile a source file to PNG and return one bytes object per page.'''
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'page-{n}.png'
            self._run(source, output, bucket_dir, fmt='png', ppi=ppi, timeout=_IMAGE_TIMEOUT)

            return [
                png_file.read_bytes()
                for png_file in sorted(Path(tmp).glob('page-*.png'))
            ]

    def _resolve_source(self, slug, path):
        '''Validate that the source file exists and is inside the bucket.'''
        bucket_dir = (self.data_dir / slug).resolve()
        source     = (bucket_dir / path).resolve()

        if not source.is_relative_to(bucket_dir):
            raise FileNotFoundError(f'{path} is outside the bucket')

        if not source.is_file():
            raise FileNotFoundError(f'{path} not found in bucket {slug}')

        return bucket_dir, source

    def _run(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, source, output, root, fmt=None, ppi=None, timeout=_COMPILE_TIMEOUT,
    ):
        '''Build the typst compile command, run it, and raise on failure.'''
        result = subprocess.run(
            self._build_cmd(source, output, root, fmt, ppi),
            cwd=str(root),
            capture_output=True, text=True,
            timeout=timeout, check=False,
        )

        if result.returncode != 0:
            stderr = self._strip_paths(result.stderr.strip(), root)
            logger.warning('Compilation failed for %s: %s', source, stderr)
            raise CompileError(stderr, parse_diagnostics(stderr))

    def _strip_paths(self, text, root):
        '''Strip absolute paths so only bucket-relative ones reach the client.'''
        for base in (root, self.data_dir):
            text = text.replace(f'{base}/', '').replace(str(base), '')

        return text

    def _build_cmd(self, source, output, root, fmt=None, ppi=None):
        '''Assemble the typst compile argument list.'''
        cmd = ['typst', 'compile']

        if fmt:
            cmd.extend(['--format', fmt])

        if ppi is not None:
            cmd.extend(['--ppi', str(ppi)])

        if self.package_dir:
            cmd.extend(['--package-path', str(self.package_dir)])

        if self.font_dir and self.font_dir.is_dir():
            cmd.extend(['--font-path', str(self.font_dir)])

        cmd.extend(['--root', str(root), str(source), str(output)])

        return cmd
