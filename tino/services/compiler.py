'''Typst compiler service. Shells out to the `typst` CLI to produce SVG, PDF, or PNG output.'''

import base64
import logging
import math
import os
import re
import subprocess
import tempfile
import threading
import zipfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
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


#: Mime type per font file suffix for @font-face data URIs.
_FONT_MIMES = {
    '.ttf': 'font/ttf',
    '.otf': 'font/otf',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
}

#: CSS format string per font file suffix for @font-face rules.
_FONT_FORMATS = {
    '.ttf': 'truetype',
    '.otf': 'opentype',
    '.woff': 'woff',
    '.woff2': 'woff2',
}

#: Matches Typst's `<image xlink:href="data:image/svg+xml;base64,…">` embeds.
_EMBEDDED_SVG_RE = re.compile(r'((?:xlink:)?href)="data:image/svg\+xml;base64,([^"]+)"')

#: Matches `font-family` references in attribute and style values.
_FAMILY_RE = re.compile(r"font-family\s*[:=]\s*(['\"]?)([^;}\"'<>]+)\1?", re.IGNORECASE)

#: Generic CSS families, never matched against installed fonts.
_GENERIC_FAMILIES = frozenset({
    'serif', 'sans-serif', 'monospace', 'cursive', 'fantasy',
    'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded',
    'emoji', 'math', 'fangsong',
})

#: Cache of per-directory @font-face maps, invalidated by file signature.
_font_face_cache: dict[
    tuple[Path, ...], tuple[tuple, dict[str, tuple[bool, str]]]
] = {}
_font_face_cache_lock = threading.Lock()


@lru_cache
def typst_version() -> str | None:
    '''Return the installed Typst CLI version, or None if it can't be determined.'''
    try:
        return CompilerService.version()
    except Exception:  # pylint: disable=broad-exception-caught
        return None


def _font_signature(dirs: tuple[Path, ...]) -> tuple:
    '''Return a signature of the font files in *dirs* (name, size, mtime).'''
    signature = []
    for dir_path in dirs:
        files = []
        for file in sorted(dir_path.iterdir()):
            if file.is_file() and file.suffix.lower() in _FONT_FORMATS:
                stat = file.stat()
                files.append((file.name, stat.st_size, stat.st_mtime_ns))
        signature.append((str(dir_path), tuple(files)))
    return tuple(signature)


def _font_meta(path: Path) -> tuple[str | None, str | None, str, str, int, bool] | None:
    '''Return ``(family16, family1, mime, format, weight, italic)`` or None.

    Both family names are returned because variable fonts often differ between
    nameID 16 (typographic) and nameID 1 (font family). *weight* comes from
    OS/2 ``usWeightClass`` (default 400) and *italic* from the subfamily name
    (nameID 2 or 17), the OS/2 ``fsSelection`` bit 0, or ``head.macStyle``
    bit 1, so regular and italic cuts of the same family can be told apart.
    '''
    fmt = _FONT_FORMATS.get(path.suffix.lower())
    mime = _FONT_MIMES.get(path.suffix.lower())
    if fmt is None or mime is None:
        return None
    try:
        font = TTFont(path)
        name_table = font['name']
    except Exception:  # pylint: disable=broad-exception-caught
        return None
    family16 = name_table.getDebugName(16)
    family1 = name_table.getDebugName(1)
    subfamily = (name_table.getDebugName(2)
                 or name_table.getDebugName(17) or '')
    italic = 'italic' in subfamily.lower()
    weight = 400
    try:
        weight = font['OS/2'].usWeightClass or 400
    except KeyError:
        pass
    if not italic and 'OS/2' in font:
        italic = bool(font['OS/2'].fsSelection & 0x0001)
    if not italic and 'head' in font:
        italic = bool(font['head'].macStyle & 0x0002)
    if not family16 and not family1:
        return None
    return family16, family1, mime, fmt, weight, italic


def _norm_family(name: str) -> str:
    '''Lowercase *name* and strip punctuation for forgiving matching.'''
    return ''.join(char for char in name.lower() if char.isalnum())


def _build_font_faces(dirs: tuple[Path, ...]) -> dict[str, tuple[bool, str]]:
    '''Build a map of normalized family name → ``(italic, src)`` for *dirs*.

    Keys are the normalized (lowercased, punctuation-stripped) family names
    from both nameID 16 and nameID 1, so a referenced family such as
    ``IBM Plex Sans`` can find a variable font named ``IBM Plex Sans Var``.
    When regular and italic cuts of the same family collide, the non-italic
    face wins the plain key (so ordinary text stays upright); italic faces
    are additionally kept under ``key|italic``. Values carry the
    ``font-weight``/``font-style`` descriptors plus the
    ``src:url(data:…;base64,…) format('…')`` part; the declared @font-face
    family name is chosen at injection time to match what the SVG references.
    '''
    faces: dict[str, tuple[bool, str]] = {}
    for dir_path in dirs:
        for file in sorted(dir_path.iterdir()):
            meta = _font_meta(file)
            if meta is None:
                continue
            family16, family1, mime, fmt, weight, italic = meta
            try:
                encoded = base64.b64encode(file.read_bytes()).decode('ascii')
            except OSError:
                continue
            src = (
                f'font-weight:{weight};font-style:'
                f'{"italic" if italic else "normal"};'
                f'src:url(data:{mime};base64,{encoded}) format(\'{fmt}\')'
            )
            for family in (family16, family1):
                if not family:
                    continue
                key = _norm_family(family)
                if key not in faces or (faces[key][0] and not italic):
                    faces[key] = (italic, src)
                if italic:
                    faces.setdefault(f'{key}|italic', (True, src))
    return faces


def _font_faces(dirs: tuple[Path, ...]) -> dict[str, tuple[bool, str]]:
    '''Return the @font-face map for *dirs*, cached until the fonts change.'''
    signature = _font_signature(dirs)
    with _font_face_cache_lock:
        cached = _font_face_cache.get(dirs)
        if cached is not None and cached[0] == signature:
            return cached[1]

    faces = _build_font_faces(dirs)
    with _font_face_cache_lock:
        _font_face_cache[dirs] = (signature, faces)
    return faces


def _referenced_families(svg: str) -> dict[str, str]:
    '''Return the family names an SVG's text references via font-family.

    Maps lowercased name → display name (first seen), skipping generic CSS
    families such as ``sans-serif``.
    '''
    names: dict[str, str] = {}
    for match in _FAMILY_RE.finditer(svg):
        for part in match.group(2).split(','):
            name = part.strip().strip('"\'')
            lowered = name.lower()
            if not name or lowered in _GENERIC_FAMILIES:
                continue
            names.setdefault(lowered, name)
    return names


def _match_face(referenced: str, faces: dict[str, tuple[bool, str]]) -> str | None:
    '''Return the normalized face key matching *referenced*, or None.

    Prefers an exact normalized match, then the shortest face whose name
    contains the referenced family (e.g. ``IBM Plex Sans`` → the variable
    font ``IBM Plex Sans Var``). Plain (non-italic) keys are preferred over
    their ``key|italic`` companions.
    '''
    wanted = _norm_family(referenced)
    if wanted in faces:
        return wanted
    candidates = sorted(
        key for key in faces
        if key.startswith(wanted) or wanted.startswith(key)
    )
    if not candidates:
        return None
    return min(candidates, key=len)


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

        pages = self._render_pngs(source, bucket_dir, slug, ppi)
        grid = _compose_overview(pages, max_width, max_height) if overview and pages else None

        return {'pages': pages, 'overview': grid}

    # ── Internal ──

    def _render_svgs(self, source, bucket_dir, slug):
        '''Compile a source file to SVG and return one string per page.'''
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'page-{n}.svg'
            self._run(source, output, bucket_dir, slug, fmt='svg')

            return [
                self._inject_svg_fonts(svg_file.read_text(encoding='utf-8'), slug)
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

    def _inject_svg_fonts(self, svg: str, slug: str) -> str:
        '''Bake server fonts into embedded SVG images so browsers render them.

        Typst embeds an SVG image as the original ``data:image/svg+xml`` data
        URI, which the browser renders as an image context where page fonts do
        not apply. This injects ``@font-face`` rules (with the font data
        inlined) into each embedded SVG for the families it references, so the
        preview matches the PDF. Any unparseable image or font is left
        untouched.
        '''
        if 'data:image/svg+xml;base64' not in svg:
            return svg

        dirs = tuple(self._font_paths(slug))
        faces = _font_faces(dirs) if dirs else {}
        logger.debug(
            'SVG font injection for %s: font_dirs=%s, discovered_families=%d',
            slug, [str(d) for d in dirs], len(faces),
        )
        if not faces:
            return svg

        embedded = list(_EMBEDDED_SVG_RE.finditer(svg))
        logger.debug('SVG font injection for %s: %d embedded SVG image(s) found',
                     slug, len(embedded))
        if not embedded:
            return svg

        def _replace(match):
            prefix, encoded = match.group(1), match.group(2)
            inner = self._font_face_inner(encoded, faces, slug)
            if inner is None:
                return match.group(0)
            rebased = base64.b64encode(inner.encode('utf-8')).decode('ascii')
            return f'{prefix}="data:image/svg+xml;base64,{rebased}"'

        return _EMBEDDED_SVG_RE.sub(_replace, svg)

    @staticmethod
    def _font_face_inner(encoded: str, faces: dict[str, tuple[bool, str]],
                         slug: str) -> str | None:
        '''Return *encoded* (base64 SVG) with @font-face rules injected, or None.'''
        try:
            inner = base64.b64decode(encoded).decode('utf-8')
        except ValueError:
            return None

        referenced = _referenced_families(inner)
        rules = []
        missing = []
        for display in referenced.values():
            key = _match_face(display, faces)
            if key is None:
                missing.append(display)
                continue
            safe = display.replace('\\', '\\\\').replace('"', '\\"')
            rules.append(
                f'@font-face{{font-family:"{safe}";{faces[key][1]};}}'
            )
        if missing:
            logger.warning(
                'Embedded SVG in %s references no installed font family'
                ' (referenced=%s, available=%s)',
                slug, sorted(missing), sorted(faces.keys()),
            )
        if not rules:
            return None

        injected = re.sub(
            r'(<svg[^>]*>)',
            lambda m: m.group(1) + f'<style>{"".join(rules)}</style>',
            inner,
            count=1,
        )
        if injected == inner:
            return None

        logger.info('Injected %d @font-face rule(s) into an embedded SVG in %s',
                    len(rules), slug)
        return injected

    def _render_pngs(self, source, bucket_dir, slug, ppi):
        '''Compile a source file to PNG and return one bytes object per page.'''
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'page-{n}.png'
            self._run(source, output, bucket_dir, slug, fmt='png', ppi=ppi,
                      timeout=_IMAGE_TIMEOUT)

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
        self, source, output, root, slug, fmt=None, ppi=None, timeout=_COMPILE_TIMEOUT,
    ):
        '''Build the typst compile command, run it, and raise on failure.'''
        result = subprocess.run(
            self._build_cmd(source, output, root, slug, fmt, ppi),
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

    def _build_cmd(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, source, output, root, slug, fmt=None, ppi=None,
    ):
        '''Assemble the typst compile argument list.'''
        cmd = ['typst', 'compile']

        if fmt:
            cmd.extend(['--format', fmt])

        if ppi is not None:
            cmd.extend(['--ppi', str(ppi)])

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
