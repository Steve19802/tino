# pylint: disable=too-many-lines
'''MCP (Model Context Protocol) server exposing TINO as tools for AI agents.

The server is mounted into the main FastAPI app as a Streamable HTTP ASGI
sub-application at ``/mcp``. It reuses TINO's existing services and enforces the
same per-bucket role model as the REST API.

Authentication follows the MCP OAuth 2.0 specification: TINO acts as a *Resource
Server* and delegates authentication to the configured OIDC provider (it still
enforces its own per-bucket authorization). MCP clients
identify themselves to that provider with a `Client ID Metadata Document
<https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/>`_
(CIMD) — their ``client_id`` is an HTTPS URL the provider dereferences, so there is
no Dynamic Client Registration — obtain an access token, and present it to TINO as a
Bearer token. TINO validates the token against the provider's JWKS and runs each
tool as that user, with their real group memberships driving bucket access.
'''

import base64
import functools
import inspect
import logging
import zipfile
from contextvars import ContextVar
from urllib.parse import urlparse

import anyio
import httpx
import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from .. import config
from ..auth import ROLE_HIERARCHY, resolve_role
from ..dependencies import get_bucket_font_service, get_bucket_service, get_collab_manager, \
    get_compiler_service, get_file_service, get_git_service, get_notifier, get_search_service
from ..models import User
from ..services.compiler import CompileError, pptx_version, typst_version, zip_pngs
from ..services.file import apply_hunks
from .instructions import server_instructions

logger = logging.getLogger(__name__)

#: The authenticated user for the in-flight MCP request.
_current_user: ContextVar[User | None] = ContextVar('mcp_user', default=None)

_DISCOVERY_SUFFIX = '/.well-known/openid-configuration'

_INSTRUCTIONS = server_instructions()

#: Search queries shorter than this are ignored (the tool returns an empty list).
MCP_MIN_QUERY_LEN = 2

#: Maximum number of file results the ``search`` tool returns across all buckets.
MCP_MAX_RESULTS = 50


def _issuer_url(discovery_url: str) -> str:
    '''Derive the OAuth issuer URL from the OIDC discovery URL.'''
    if discovery_url.endswith(_DISCOVERY_SUFFIX):
        return discovery_url[:-len(_DISCOVERY_SUFFIX)]
    return discovery_url


# ── Authentication (OAuth Resource Server) ──


class OIDCTokenVerifier(TokenVerifier):  # pylint: disable=too-few-public-methods
    '''Validate provider-issued JWT access tokens against the OIDC JWKS.

    On success the token's claims are turned into a :class:`~tino.models.User`
    (username + groups) and bound to the request context for the tools to use.
    '''

    def __init__(self, discovery_url: str, groups_claim: str) -> None:
        self._discovery_url = discovery_url
        self._groups_claim = groups_claim
        self._issuer: str | None = None
        self._jwks_client: jwt.PyJWKClient | None = None
        self._lock = anyio.Lock()
        logger.debug(
            'OIDCTokenVerifier configured: discovery=%s, groups_claim=%s',
            discovery_url, groups_claim,
        )

    async def _ensure_metadata(self) -> None:
        '''Lazily fetch the issuer and JWKS URI from the discovery document.'''
        if self._jwks_client is not None:
            return
        async with self._lock:
            if self._jwks_client is not None:
                return
            logger.debug('Fetching OIDC discovery from %s', self._discovery_url)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(self._discovery_url, timeout=10)
                    resp.raise_for_status()
                    meta = resp.json()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    'OIDC discovery failed: url=%s, status=%d',
                    self._discovery_url, exc.response.status_code,
                )
                raise
            except httpx.HTTPError as exc:
                logger.error(
                    'OIDC discovery network error: url=%s, error=%s',
                    self._discovery_url, exc,
                )
                raise
            self._issuer = meta['issuer']
            self._jwks_client = jwt.PyJWKClient(meta['jwks_uri'])
            logger.info(
                'OIDC metadata loaded: issuer=%s, jwks_uri=%s',
                self._issuer, meta['jwks_uri'],
            )

    @staticmethod
    def _safe_claims(token: str) -> dict:
        '''Decode the JWT payload without verification for diagnostic logging.'''
        try:
            return jwt.decode(token, options={
                'verify_signature': False,
                'verify_exp': False,
                'verify_iss': False,
                'verify_aud': False,
            })
        except Exception:  # pylint: disable=broad-exception-caught
            return {}

    async def verify_token(self, token: str) -> AccessToken | None:
        '''Validate the JWT and bind the resolved user to the request context.'''
        logger.debug('Verifying MCP bearer token (%d chars)', len(token))
        try:
            await self._ensure_metadata()
            signing_key = await anyio.to_thread.run_sync(
                self._jwks_client.get_signing_key_from_jwt, token,
            )
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=['RS256'],
                issuer=self._issuer,
                # Signature, issuer and expiry are validated, but NOT the
                # audience: Keycloak issues CIMD-flow tokens with no ``aud`` claim
                # (the ephemeral client has no registered entry to carry an
                # audience mapper), so there is nothing to bind to. A token issued
                # to another client in the same realm is therefore accepted here
                # and constrained only by per-bucket authorization. See ADR-10
                # and tino#24; enable verify_aud once the provider sets ``aud``.
                options={'verify_aud': False},
            )
        except jwt.ExpiredSignatureError as exc:
            unverified = self._safe_claims(token)
            logger.warning(
                'MCP token rejected (expired): %s (iss=%s, exp=%s, azp=%s)',
                exc, unverified.get('iss'), unverified.get('exp'),
                unverified.get('azp'),
            )
            return None
        except jwt.InvalidIssuerError as exc:
            unverified = self._safe_claims(token)
            logger.warning(
                'MCP token rejected (issuer mismatch, expected=%s): %s'
                ' (iss=%s, exp=%s, azp=%s)',
                self._issuer, exc, unverified.get('iss'),
                unverified.get('exp'), unverified.get('azp'),
            )
            return None
        except jwt.InvalidSignatureError as exc:
            unverified = self._safe_claims(token)
            logger.warning(
                'MCP token rejected (bad signature): %s (iss=%s, exp=%s, azp=%s)',
                exc, unverified.get('iss'), unverified.get('exp'),
                unverified.get('azp'),
            )
            return None
        except jwt.DecodeError as exc:
            logger.warning('MCP token rejected (malformed JWT): %s', exc)
            return None
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Network errors, JWKS fetch failures, or anything else.
            is_network = isinstance(exc, (httpx.HTTPError, OSError))
            reason = 'network/JWKS' if is_network else type(exc).__name__
            logger.warning('MCP token rejected (%s): %s', reason, exc)
            return None

        user = User(
            username=claims.get('preferred_username', claims.get('sub', '')),
            email=claims.get('email', ''),
            groups=claims.get(self._groups_claim) or [],
        )
        _current_user.set(user)
        logger.info('MCP authenticated user: %s', user.username)
        # ``aud``/``azp``/``client_id`` are logged for auth diagnostics. Keycloak
        # CIMD tokens carry no ``aud`` (see the ``verify_aud`` note above); ``azp``
        # holds the client's CIMD URL. ``aud`` uses %r as it may be a string or list.
        logger.debug(
            'MCP token details: user=%s, email=%s, groups=%s, iss=%s, exp=%s, '
            'aud=%r, azp=%s, client_id=%s',
            user.username, user.email, user.groups,
            claims.get('iss'), claims.get('exp'),
            claims.get('aud'), claims.get('azp'), claims.get('client_id'),
        )

        return AccessToken(
            token=token,
            client_id=claims.get('azp') or claims.get('client_id', ''),
            scopes=claims.get('scope', '').split(),
            expires_at=claims.get('exp'),
        )


def _noauth_user() -> User:
    '''Build the implicit admin user used when ``TINO_AUTH_DISABLED`` is set.'''
    return User(username='tino', email='tino@localhost', groups=list(config.TINO_ADMIN_GROUPS))


class _DevAdminMiddleware:  # pylint: disable=too-few-public-methods
    '''Inject an implicit admin user when ``TINO_AUTH_DISABLED`` is set (dev only).'''

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        user = _noauth_user()
        logger.debug('DevAdminMiddleware injecting implicit admin: %s', user.username)
        token = _current_user.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_user.reset(token)


def _build_auth_kwargs() -> dict:
    '''Return the MCPServer auth kwargs, or an empty dict when auth is disabled.'''
    if config.TINO_AUTH_DISABLED:
        logger.info('MCP auth disabled (TINO_AUTH_DISABLED)')
        return {}
    if not (config.TINO_OIDC_DISCOVERY_URL and config.TINO_BASE_URL):
        logger.warning('MCP auth not configured (missing OIDC_DISCOVERY_URL or BASE_URL)')
        return {}
    issuer = _issuer_url(config.TINO_OIDC_DISCOVERY_URL)
    resource_url = f'{config.TINO_BASE_URL}/mcp'
    logger.info('MCP auth: issuer=%s, resource=%s', issuer, resource_url)
    return {
        'token_verifier': OIDCTokenVerifier(
            config.TINO_OIDC_DISCOVERY_URL, config.TINO_OIDC_GROUPS_CLAIM,
        ),
        'auth': AuthSettings(
            issuer_url=issuer,
            resource_server_url=resource_url,
            required_scopes=[],
        ),
    }


_auth_kwargs = _build_auth_kwargs()

# Allow the configured base URL host (plus localhost for dev).
_allowed_hosts = ['localhost:*', '127.0.0.1:*']
if config.TINO_BASE_URL:
    _allowed_hosts.append(urlparse(config.TINO_BASE_URL).netloc)
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=_allowed_hosts,
)

# Transport options (stateless_http, json_response, path, transport security)
# moved from the constructor to streamable_http_app() in mcp SDK 2.x.
mcp = MCPServer(
    'TINO',
    instructions=_INSTRUCTIONS,
    **_auth_kwargs,
)
logger.info(
    'MCPServer instance created: stateless_http=True, auth_configured=%s',
    'token_verifier' in _auth_kwargs,
)
logger.info('Typst compiler version: %s', typst_version())


# ── Authorization helpers ──


def _require(slug: str, min_role: str) -> User:
    '''Resolve the current user and enforce *min_role* on *slug*.

    Returns the resolved ``User``. Raises ``PermissionError`` if the user lacks
    the role, or ``FileNotFoundError`` if the bucket does not exist.
    '''
    user = _current_user.get()
    if user is None:
        raise PermissionError('Not authenticated')

    bucket = get_bucket_service().get(slug)
    if bucket is None:
        raise FileNotFoundError(f'Bucket not found: {slug}')

    role = resolve_role(user, bucket.access, slug)
    if role is None or ROLE_HIERARCHY[role] < ROLE_HIERARCHY[min_role]:
        logger.warning(
            'MCP authorization denied: user=%s, bucket=%s, required=%s, actual=%s',
            user.username, slug, min_role, role,
        )
        raise PermissionError(f"'{min_role}' role required for bucket '{slug}'")

    logger.debug(
        'MCP authorization granted: user=%s, bucket=%s, role=%s',
        user.username, slug, role,
    )
    return user


def _read_text(bucket: str, path: str) -> str:
    '''Return the text content of a file, preferring the live collab room.

    Mirrors the ``read_file`` tool: open collab rooms carry unsaved edits that
    outrank the (older) on-disk copy, so edits computed against this content
    don't clobber in-flight web-UI changes.
    '''
    live = get_collab_manager().get_content(bucket, path)
    if live is not None:
        return live

    result = get_file_service().read(bucket, path)
    if result is None:
        raise FileNotFoundError(f'File not found: {bucket}/{path}')
    if result.get('binary'):
        raise ValueError(f'File is binary and cannot be read as text: {bucket}/{path}')

    return result['content']


async def _apply_changes(bucket: str, path: str, changes: list[dict]) -> dict:
    '''Apply search/replace changes to a file and refresh collab state.

    Validates every change against the current content before writing, so a
    failing change leaves the file untouched. Requires the editor role.
    '''
    user = _require(bucket, 'editor')
    new_content, replaced = apply_hunks(_read_text(bucket, path), changes)

    modified = get_file_service().write(bucket, path, new_content)
    if modified is None:
        raise ValueError(f'Invalid path: {path}')

    # Push the new content into any open collab room so connected web-UI
    # clients see it, and the room's eventual flush doesn't overwrite this edit.
    await get_collab_manager().reload_rooms(bucket, [path])
    logger.info('MCP patched %s/%s (%d change(s)) (user: %s)',
                bucket, path, len(changes), user.username)
    await get_notifier().notify(bucket)
    return {
        'path': path, 'modified': modified,
        'changes': len(changes), 'replaced': replaced,
    }


#: Exception types a tool raises for *anticipated* failures. Converted to
#: ``ToolError`` so the MCP SDK surfaces the message to the agent instead of
#: wrapping it in a generic "Error executing tool <name>".
_EXPECTED_TOOL_ERRORS = (
    ValueError,
    FileNotFoundError,
    RuntimeError,
    PermissionError,
    KeyError,
)


def _tool_safe(fn):
    '''Convert expected exceptions raised by a tool into a ``ToolError``.

    The MCP SDK only forwards the original message for ``ToolError``; any other
    exception reaches the model as a bare "Error executing tool <name>". Wrapping
    keeps the helpful messages (missing files, unmatched ``old_text``, invalid
    input, …) visible to the agent. Unexpected exceptions still propagate as
    crashes. ``functools.wraps`` preserves the tool's name, docstring and
    signature for the SDK's argument schema.
    '''
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def _wrapped(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except _EXPECTED_TOOL_ERRORS as exc:
                raise ToolError(str(exc)) from exc
    else:
        @functools.wraps(fn)
        def _wrapped(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except _EXPECTED_TOOL_ERRORS as exc:
                raise ToolError(str(exc)) from exc

    return _wrapped


def _tool(fn=None):
    '''Register a tool with expected-error surfacing.

    Usable as ``@_tool()`` (like ``@mcp.tool()``) or directly as ``_tool(fn)``
    for tools registered conditionally (e.g. ``commit``).
    '''
    def _decorator(func):
        return mcp.tool()(_tool_safe(func))

    if fn is None:
        return _decorator
    return _decorator(fn)


# ── Tools ──


@_tool()
def list_buckets() -> list[dict]:
    '''List all buckets the current user can access, with their role on each.

    Buckets may include an ``instructions`` field with specific guidance for
    working with that bucket's content.  Always read and follow these
    instructions before making changes.
    '''
    user = _current_user.get()
    if user is None:
        raise PermissionError('Not authenticated')

    logger.debug('MCP list_buckets called by user=%s', user.username)
    results = []
    for bucket in get_bucket_service().list():
        role = resolve_role(user, bucket.access, bucket.slug)
        if role is not None:
            entry = {
                'slug': bucket.slug,
                'description': bucket.description,
                'role': role,
            }
            if bucket.name:
                entry['name'] = bucket.name
            if bucket.mcp_instructions:
                entry['instructions'] = bucket.mcp_instructions
            results.append(entry)
    logger.debug('MCP list_buckets returning %d buckets for user=%s', len(results), user.username)
    return results


@_tool()
def list_files(bucket: str) -> list[dict]:
    '''List all files and directories in a bucket.'''
    logger.debug('MCP list_files called: bucket=%s', bucket)
    _require(bucket, 'viewer')
    return [entry.model_dump() for entry in get_file_service().list(bucket)]


@_tool()
def search(query: str, bucket: str | None = None) -> list[dict]:
    '''Search file names and contents across the buckets you can access.

    Pass *bucket* to limit the search to a single bucket, or omit it to search
    every accessible bucket. Each result is a file with ``name_match`` and any
    matching content ``snippets`` (line number + text). Prefer this over listing
    every bucket and reading files one by one when locating a document.
    '''
    user = _current_user.get()
    if user is None:
        raise PermissionError('Not authenticated')

    needle = query.strip()
    if len(needle) < MCP_MIN_QUERY_LEN:
        return []

    if bucket is not None:
        _require(bucket, 'viewer')
        slugs = [bucket]
    else:
        slugs = [b.slug for b in get_bucket_service().list()
                 if resolve_role(user, b.access, b.slug) is not None]

    logger.debug('MCP search %r over %d bucket(s) (user: %s)',
                 needle, len(slugs), user.username)

    results: list[dict] = []
    for slug in slugs:
        remaining = MCP_MAX_RESULTS - len(results)
        if remaining <= 0:
            break
        hits = get_search_service().search_bucket(slug, needle, limit=remaining)
        results.extend(r.model_dump() for r in hits)

    return results


@_tool()
def read_file(bucket: str, path: str,
              start_line: int | None = None, end_line: int | None = None) -> str:
    '''Read the text content of a file in a bucket.

    Pass *start_line* and *end_line* (1-indexed, inclusive) to read only a
    range of lines — handy for re-checking an edited region after
    ``edit_file``/``patch_file`` without re-reading the whole file.
    '''
    logger.debug('MCP read_file called: bucket=%s, path=%s, range=%r-%r',
                 bucket, path, start_line, end_line)
    _require(bucket, 'viewer')

    content = _read_text(bucket, path)

    if start_line is None:
        return content

    if start_line < 1:
        raise ValueError('start_line must be >= 1')
    if end_line is not None and end_line < start_line:
        raise ValueError('end_line must be >= start_line')

    lines = content.splitlines()
    if end_line is None:
        end_line = len(lines)

    return '\n'.join(lines[start_line - 1:end_line])


@_tool()
async def edit_file(bucket: str, path: str, old_text: str, new_text: str,
                    replace_all: bool = False) -> dict:
    '''Replace a block of text in a file. Requires the editor role.

    *old_text* must match the current content exactly, including whitespace and
    line endings. When it appears multiple times, pass *replace_all* to replace
    every occurrence, or use ``patch_file`` with an ``occurrence`` index for a
    single later match. Prefer this over ``write_file`` for small changes — only
    the changed text is sent, saving tokens.
    '''
    logger.debug('MCP edit_file called: bucket=%s, path=%s, replace_all=%s',
                 bucket, path, replace_all)
    return await _apply_changes(bucket, path, [
        {'old_text': old_text, 'new_text': new_text, 'replace_all': replace_all},
    ])


@_tool()
async def patch_file(bucket: str, path: str, changes: list[dict]) -> dict:
    '''Apply one or more search/replace changes to a file atomically.

    Each change is ``{"old_text": "...", "new_text": "...", "occurrence": 0}``
    plus an optional ``"replace_all": true`` flag. *old_text* must match the
    current content exactly (whitespace and line endings matter); *occurrence*
    (0-based, default 0) selects which match to replace, and with
    ``replace_all`` every occurrence is replaced in one pass (occurrence is
    ignored). Both are counted against the *evolving* content: changes apply in
    order, so a later change sees the result of earlier ones. All changes are
    validated against the current content before anything is written, so a
    failing change leaves the file untouched. The response reports how many
    occurrences each change replaced under ``replaced``. Requires the editor
    role.
    '''
    logger.debug('MCP patch_file called: bucket=%s, path=%s, changes=%d',
                 bucket, path, len(changes))
    return await _apply_changes(bucket, path, changes)


@_tool()
def grep(bucket: str, pattern: str, path: str | None = None,
         ignore_case: bool = False) -> list[dict]:
    '''Search file contents with a regular expression in a bucket.

    Returns files with matching lines: ``{"path", "matches": [{"line", "text"}]}``.
    Use *path* to restrict the search to a single file or a directory subtree
    (e.g. ``src/``). Pass *ignore_case* for case-insensitive matching. Prefer
    ``grep`` when you need a pattern such as ``^#import``; use ``search`` for
    fuzzy file-name and content lookup.
    '''
    logger.debug('MCP grep called: bucket=%s, pattern=%r, path=%r',
                 bucket, pattern, path)
    _require(bucket, 'viewer')
    return get_search_service().grep_bucket(bucket, pattern, path=path, ignore_case=ignore_case)


@_tool()
async def write_file(bucket: str, path: str, content: str) -> dict:
    '''Create or overwrite a text file in a bucket. Requires the editor role.'''
    user = _require(bucket, 'editor')
    modified = get_file_service().write(bucket, path, content)

    if modified is None:
        raise ValueError(f'Invalid path: {path}')

    # Push the new content into any open collab room so connected web-UI clients
    # see it, and the room's eventual flush doesn't overwrite this write.
    await get_collab_manager().reload_rooms(bucket, [path])
    logger.info('MCP wrote %s/%s (user: %s)', bucket, path, user.username)
    await get_notifier().notify(bucket)
    return {'path': path, 'modified': modified}


@_tool()
async def write_files(bucket: str, files: list[dict]) -> dict:
    '''Create or overwrite multiple text files in a bucket in one call.

    *files* is a list of ``{"path": "...", "content": "..."}`` entries. Writes
    run sequentially; a file with an invalid path is reported under ``failed``
    without aborting the rest. Prefer this over repeated ``write_file`` calls
    when adding many assets at once. Requires the editor role.
    '''
    user = _require(bucket, 'editor')
    if not files:
        raise ValueError('Provide at least one file entry')

    written: list[dict] = []
    failed: list[dict] = []
    for entry in files:
        path = entry.get('path', '')
        content = entry.get('content', '')
        if not isinstance(path, str) or not path or not isinstance(content, str):
            failed.append({'path': path, 'error': 'Each entry needs "path" and "content" strings'})
            continue
        modified = get_file_service().write(bucket, path, content)
        if modified is None:
            failed.append({'path': path, 'error': 'Invalid path'})
        else:
            written.append({'path': path, 'modified': modified})

    paths = [w['path'] for w in written]
    if paths:
        await get_collab_manager().reload_rooms(bucket, paths)
        logger.info('MCP wrote %d file(s) to %s (user: %s)', len(written), bucket, user.username)
        await get_notifier().notify(bucket)
    return {'written': written, 'failed': failed}


@_tool()
def download_bucket(bucket: str, inline: bool = False) -> dict:
    '''Download the whole bucket as a ZIP archive (the "clone" step).

    With ``inline=False`` (default) returns the URL of the REST download
    endpoint — note that endpoint requires TINO session or API-key
    authentication, not the MCP bearer token. With ``inline=True`` the archive
    is returned base64-encoded, usable with MCP authentication alone. Requires
    the viewer role.
    '''
    user = _require(bucket, 'viewer')

    if not inline:
        url = f'{config.TINO_BASE_URL or ""}/api/buckets/{bucket}/files/download'
        return {'bucket': bucket, 'url': url}

    zip_path = get_file_service().zip(bucket)
    if zip_path is None:
        raise FileNotFoundError(f'Bucket not found: {bucket}')
    try:
        data = zip_path.read_bytes()
        encoded = base64.b64encode(data).decode('ascii')
    finally:
        zip_path.unlink(missing_ok=True)

    logger.info('MCP downloaded %s as ZIP (%d bytes, inline) (user: %s)',
                bucket, len(data), user.username)
    return {'bucket': bucket, 'zip': encoded, 'size': len(data)}


@_tool()
async def upload_bucket_zip(bucket: str, zip_base64: str, prefix: str = '') -> dict:
    '''Upload a base64-encoded ZIP archive into a bucket (the "push" step).

    The archive is extracted into the bucket working tree, overwriting matching
    files; files not present in the archive are left untouched. *prefix*
    optionally nests the archive under a directory. Requires the editor role.
    '''
    user = _require(bucket, 'editor')

    try:
        data = base64.b64decode(zip_base64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('"zip_base64" must be valid base64 data') from exc

    try:
        extracted = get_file_service().unzip(bucket, data, prefix)
    except zipfile.BadZipFile as exc:
        raise ValueError('"zip_base64" is not a valid ZIP archive') from exc

    if extracted:
        await get_collab_manager().reload_rooms(bucket, extracted)
        logger.info('MCP uploaded ZIP to %s (%d files) (user: %s)',
                    bucket, len(extracted), user.username)
        await get_notifier().notify(bucket)
    return {'bucket': bucket, 'extracted': extracted}


@_tool()
def list_bucket_fonts(bucket: str) -> list[dict]:
    '''List the custom fonts installed in a bucket's ``fonts/`` directory.

    Bucket fonts take precedence over the instance-wide global fonts when both
    provide the same family. Requires the viewer role.
    '''
    logger.debug('MCP list_bucket_fonts called: bucket=%s', bucket)
    _require(bucket, 'viewer')
    return get_bucket_font_service(bucket).list()


@_tool()
async def upload_bucket_fonts(bucket: str, fonts: list[dict]) -> dict:
    '''Upload one or more font files into a bucket. Requires the editor role.

    Each entry is ``{"filename": "...", "data": "<base64>"}`` for a
    ``.ttf``/``.otf``/``.woff``/``.woff2`` file. Returns
    ``{"uploaded": [...], "failed": [...]}`` with per-entry errors.
    '''
    user = _require(bucket, 'editor')
    if not fonts:
        raise ValueError('Provide at least one font entry')

    svc = get_bucket_font_service(bucket)
    uploaded: list[str] = []
    failed: list[dict] = []
    for entry in fonts:
        filename = entry.get('filename', '')
        data = entry.get('data', '')
        if not isinstance(filename, str) or not filename or not isinstance(data, str):
            failed.append({'filename': filename,
                           'error': 'Each entry needs "filename" and "data" (base64)'})
            continue
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            failed.append({'filename': filename, 'error': 'Invalid base64 data'})
            continue
        if svc.upload(filename, raw):
            uploaded.append(filename)
        else:
            failed.append({'filename': filename, 'error': 'Invalid font filename'})

    if uploaded:
        logger.info('MCP uploaded %d font(s) to %s (user: %s)',
                    len(uploaded), bucket, user.username)
        await get_notifier().notify(bucket)
    return {'uploaded': uploaded, 'failed': failed}


@_tool()
async def delete_bucket_font(bucket: str, filename: str) -> dict:
    '''Delete a font from a bucket. Requires the editor role.'''
    user = _require(bucket, 'editor')
    if not get_bucket_font_service(bucket).delete(filename):
        raise ValueError(f'Font not found: {filename}')
    logger.info('MCP deleted font %s from %s (user: %s)', filename, bucket, user.username)
    await get_notifier().notify(bucket)
    return {'deleted': filename}


@_tool()
async def delete_file(bucket: str, path: str) -> dict:
    '''Delete a file from a bucket. Requires the editor role.'''
    user = _require(bucket, 'editor')

    # Evict any open collab room (without flushing) around the delete, so a
    # pending flush can't re-create the file the tool just removed.
    async with get_collab_manager().lock_path(bucket, path):
        if not get_file_service().delete(bucket, path):
            raise FileNotFoundError(f'File not found: {bucket}/{path}')

    logger.info('MCP deleted %s/%s (user: %s)', bucket, path, user.username)
    await get_notifier().notify(bucket)
    return {'deleted': path}


@_tool()
async def rename_file(bucket: str, old_path: str, new_path: str) -> dict:
    '''Rename or move a file within a bucket. Requires the editor role.

    Fails if the source is missing, the destination already exists, or the path
    is invalid.
    '''
    user = _require(bucket, 'editor')

    # Evict any open collab room for the source (without flushing) so a pending
    # flush can't re-create the file at its old path after the move.
    async with get_collab_manager().lock_path(bucket, old_path):
        if not get_file_service().rename(bucket, old_path, new_path):
            raise ValueError(
                f'Invalid path or target exists: {old_path} -> {new_path}')

    logger.info('MCP renamed %s/%s -> %s (user: %s)',
                bucket, old_path, new_path, user.username)
    await get_notifier().notify(bucket)
    return {'old_path': old_path, 'new_path': new_path}


@_tool()
async def create_dir(bucket: str, path: str) -> dict:
    '''Create an empty directory in a bucket. Requires the editor role.

    Fails if the directory already exists or the path is invalid.  Note that git
    does not track empty directories, so a created directory only persists once
    it contains a committed file.
    '''
    user = _require(bucket, 'editor')

    if not get_file_service().create_dir(bucket, path):
        raise ValueError(f'Directory already exists or invalid path: {path}')

    logger.info('MCP created dir %s/%s (user: %s)', bucket, path, user.username)
    await get_notifier().notify(bucket)
    return {'path': path}


@_tool()
async def rename_dir(bucket: str, old_path: str, new_path: str) -> dict:
    '''Rename or move a directory and all its contents. Requires the editor role.'''
    user = _require(bucket, 'editor')

    # Evict any open collab rooms under the directory before moving it.
    await get_collab_manager().evict_under(bucket, old_path)
    affected = get_file_service().rename_dir(bucket, old_path, new_path)

    if affected is None:
        raise ValueError(
            f'Invalid path or target exists: {old_path} -> {new_path}')

    logger.info('MCP renamed dir %s/%s -> %s (user: %s)',
                bucket, old_path, new_path, user.username)
    await get_notifier().notify(bucket)
    return {'old_path': old_path, 'new_path': new_path, 'affected': affected}


@_tool()
async def delete_dir(bucket: str, path: str) -> dict:
    '''Delete a directory and all its contents. Requires the editor role.'''
    user = _require(bucket, 'editor')

    # Evict any open collab rooms under the directory before deleting it.
    await get_collab_manager().evict_under(bucket, path)
    affected = get_file_service().delete_dir(bucket, path)

    if affected is None:
        raise FileNotFoundError(f'Directory not found: {bucket}/{path}')

    logger.info('MCP deleted dir %s/%s (%d files) (user: %s)',
                bucket, path, len(affected), user.username)
    await get_notifier().notify(bucket)
    return {'deleted': path, 'affected': affected}


@_tool()
def compile_typst(bucket: str, path: str) -> dict:
    '''Compile a Typst file to verify it is valid.

    Returns ``{"success": true, "pages": N, "typst_version": "..."}`` when
    compilation succeeds, or ``{"success": false, "error": "...",
    "typst_version": "...", "diagnostics": [...]}`` with the compiler error
    otherwise. Each diagnostic has ``severity``, ``message``, ``file``,
    ``line`` and ``column`` (the latter three are null when Typst reports no
    position). Use this after editing to check your work before committing;
    *typst_version* lets you adapt syntax/package versions to the server.
    '''
    logger.debug('MCP compile_typst called: bucket=%s, path=%s', bucket, path)
    _require(bucket, 'viewer')

    try:
        pages = get_compiler_service().compile_svg(bucket, path)
        return {'success': True, 'pages': len(pages), 'typst_version': typst_version()}
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    except CompileError as exc:
        return {'success': False, 'error': str(exc), 'diagnostics': exc.diagnostics}
    except RuntimeError as exc:
        return {'success': False, 'error': str(exc), 'typst_version': typst_version()}


@_tool()
def compile_svg(bucket: str, path: str) -> dict:
    '''Compile a Typst file and return the rendered SVG pages inline.

    Returns ``{"success": true, "typst_version": "...", "pages": [svg, ...]}``
    or ``{"success": false, "error": "...", "typst_version": "..."}``. Use this
    to inspect the compiled output directly (SVG is XML text); note the output
    can be large for multi-page documents. Requires the viewer role.
    '''
    logger.debug('MCP compile_svg called: bucket=%s, path=%s', bucket, path)
    _require(bucket, 'viewer')

    try:
        pages = get_compiler_service().compile_svg(bucket, path)
        return {'success': True, 'typst_version': typst_version(), 'pages': pages}
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    except CompileError as exc:
        return {'success': False, 'error': str(exc), 'diagnostics': exc.diagnostics}
    except RuntimeError as exc:
        return {'success': False, 'error': str(exc), 'typst_version': typst_version()}


@_tool()
def compile_pdf(bucket: str, path: str) -> dict:
    '''Compile a Typst file and return the PDF as base64.

    Returns ``{"success": true, "typst_version": "...", "pdf": "<base64>",
    "size": N}`` or ``{"success": false, "error": "...", "typst_version":
    "..."}``. Use this to fetch the compiled document for download or rendering
    elsewhere. Requires the viewer role.
    '''
    logger.debug('MCP compile_pdf called: bucket=%s, path=%s', bucket, path)
    _require(bucket, 'viewer')

    try:
        pdf_path = get_compiler_service().compile_pdf(bucket, path)
        try:
            data = pdf_path.read_bytes()
            return {
                'success': True,
                'typst_version': typst_version(),
                'pdf': base64.b64encode(data).decode('ascii'),
                'size': len(data),
            }
        finally:
            pdf_path.unlink(missing_ok=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    except CompileError as exc:
        return {'success': False, 'error': str(exc), 'diagnostics': exc.diagnostics}
    except RuntimeError as exc:
        return {'success': False, 'error': str(exc), 'typst_version': typst_version()}


@_tool()
def compile_png(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    bucket: str, path: str, ppi: int = 144, overview: bool = False,
    max_width: int = 2000, max_height: int = 2000,
) -> dict:
    '''Compile a Typst file and return its pages rasterised to PNG.

    Returns ``{"success": true, "page_count": N, "zip": "<base64>"}`` where the
    ZIP holds ``page_N.png`` for every page, plus an ``overview.png`` grid when
    *overview* is true. *ppi* sets the rasterisation resolution (36-300);
    *max_width*/*max_height* bound the overview grid. Returns
    ``{"success": false, "error": "...", "diagnostics": [...]}`` when
    compilation fails.
    '''
    logger.debug('MCP compile_png called: bucket=%s, path=%s, ppi=%r', bucket, path, ppi)
    _require(bucket, 'viewer')

    try:
        result = get_compiler_service().compile_png(
            bucket, path, ppi=ppi, overview=overview,
            max_width=max_width, max_height=max_height,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    except CompileError as exc:
        return {'success': False, 'error': str(exc), 'diagnostics': exc.diagnostics}
    except RuntimeError as exc:
        return {'success': False, 'error': str(exc)}

    archive = zip_pngs(result['pages'], result['overview'])
    logger.info('MCP compiled %s/%s to %d PNG page(s)', bucket, path, len(result['pages']))
    return {
        'success': True,
        'page_count': len(result['pages']),
        'overview': result['overview'] is not None,
        'zip': base64.b64encode(archive).decode('ascii'),
        'size': len(archive),
    }


@_tool()
def compile_pptx(bucket: str, path: str, animations: str = 'auto') -> dict:
    '''Export a Typst file as an editable PowerPoint (.pptx) presentation.

    Requires Touying 0.8 or newer. Returns ``{"success": true,
    "typst_pptx_version": "...", "pptx": "<base64>", "size": N,
    "report": {...}}`` or ``{"success": false, "error": "...",
    "diagnostics": [...]}``. The *report* says what was exported natively vs.
    baked as a picture (its ``baked`` list) — read it to see what won't be
    editable in PowerPoint. *animations* is ``auto``, ``none`` or ``slides``.
    '''
    logger.debug('MCP compile_pptx called: bucket=%s, path=%s', bucket, path)
    _require(bucket, 'viewer')

    if pptx_version() is None:
        raise ToolError('PPTX export is not available (typst-pptx is not installed)')

    try:
        pptx_path, report = get_compiler_service().compile_pptx(
            bucket, path, animations=animations)
        try:
            data = pptx_path.read_bytes()
        finally:
            pptx_path.unlink(missing_ok=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(str(exc)) from exc
    except CompileError as exc:
        return {'success': False, 'error': str(exc), 'diagnostics': exc.diagnostics}
    except (ValueError, RuntimeError) as exc:
        return {'success': False, 'error': str(exc)}

    logger.info('MCP exported %s/%s to PPTX (%d bytes)', bucket, path, len(data))
    return {
        'success': True,
        'typst_pptx_version': pptx_version(),
        'pptx': base64.b64encode(data).decode('ascii'),
        'size': len(data),
        'report': report,
    }


@_tool()
def git_status(bucket: str) -> list[dict]:
    '''Return the working-tree status (modified, untracked, deleted) of a bucket.'''
    logger.debug('MCP git_status called: bucket=%s', bucket)
    _require(bucket, 'viewer')
    return [s.model_dump() for s in get_git_service().status(bucket)]


@_tool()
def git_log(bucket: str, path: str | None = None, max_count: int = 20) -> list[dict]:
    '''Return commit history for a bucket, optionally filtered to a single file.'''
    logger.debug('MCP git_log called: bucket=%s, path=%s', bucket, path)
    _require(bucket, 'viewer')
    commits = get_git_service().log(bucket, path, max_count=max_count)
    return [c.model_dump() for c in commits]


async def commit(bucket: str, message: str, files: list[str] | None = None) -> dict:
    '''Commit changes in a bucket. Requires the committer role.

    If *files* is omitted, all changed files in the working tree are committed.
    '''
    user = _require(bucket, 'committer')

    if files is None:
        files = [s.path for s in get_git_service().status(bucket)]

    if not files:
        raise ValueError('Nothing to commit')

    result = get_git_service().commit(
        bucket, files, message, author=user.username, email=user.email,
    )
    logger.info('MCP committed %s: %r (user: %s)', bucket, message, user.username)
    await get_notifier().notify(bucket)
    return result.model_dump()


# Register the commit tool only when enabled, so deployments can offer a
# read/write-but-no-commit MCP surface (agents edit, humans commit).
if config.TINO_MCP_COMMIT_ENABLED:
    _tool(commit)
    logger.info('MCP commit tool registered (TINO_MCP_COMMIT_ENABLED)')
else:
    logger.info('MCP commit tool disabled (set TINO_MCP_COMMIT_ENABLED=true to enable)')


# Build the ASGI app once. In dev (auth disabled) an admin user is injected;
# otherwise the OAuth resource-server machinery enforces authentication.
_base_app = mcp.streamable_http_app(
    stateless_http=True,
    json_response=True,
    # The handler sits at the sub-app root; the app mounts it under /mcp.
    streamable_http_path='/',
    transport_security=_transport_security,
)
if config.TINO_AUTH_DISABLED:
    mcp_asgi_app = _DevAdminMiddleware(_base_app)
    logger.info('MCP ASGI app built with DevAdminMiddleware (auth disabled)')
else:
    mcp_asgi_app = _base_app
    logger.info('MCP ASGI app built with OAuth token verification')
