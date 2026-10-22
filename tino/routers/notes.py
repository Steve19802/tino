'''REST endpoint for a document's speaker notes.'''

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_compiler_service, require_viewer
from ..services.compiler import CompilerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/buckets/{slug}/notes', tags=['notes'])


@router.get('/{path:path}')
async def get_notes(
    slug: str, path: str,
    user=Depends(require_viewer),
    svc: CompilerService = Depends(get_compiler_service),
):
    '''Return a document's speaker notes, one entry per page.

    Notes come from the pdfpc metadata Touying and Polylux record, so they arrive
    in page order with ``null`` where a page has none. A document without that
    metadata simply has no notes: the list comes back empty, not as an error.
    '''
    logger.debug('Reading speaker notes for %s/%s (user: %s)', slug, path, user.username)
    try:
        return {'notes': svc.compile_notes(slug, path)}

    except FileNotFoundError as exc:
        raise HTTPException(404, 'File not found') from exc
