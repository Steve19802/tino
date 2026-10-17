'''Typst compiler service. Shells out to the system `typst` binary to produce SVG or PDF output.'''

import base64
import logging
import os
import re
import subprocess
import tempfile
import threading
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont

logger = logging.getLogger(__name__)

_COMPILE_TIMEOUT = 30

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
