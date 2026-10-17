'''REST endpoints for managing per-bucket fonts (stored in the bucket's fonts/ dir).'''

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.params import File

from ..dependencies import get_bucket_font_service, get_notifier, require_editor, require_viewer
from ..models import FontEntry
from ..services.font import FontService

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/buckets/{slug}/fonts', tags=['bucket-fonts'])


@router.get('', response_model=list[FontEntry])
async def list_bucket_fonts(
    slug: str,
    user=Depends(require_viewer),
    svc: FontService = Depends(get_bucket_font_service),
):
    '''Return the fonts installed in a bucket's ``fonts/`` directory.'''
    logger.debug('Listing fonts for %s (user: %s)', slug, user.username)
    return svc.list()


@router.post('/upload', status_code=201)
async def upload_bucket_fonts(
    slug: str,
    files: list[UploadFile] = File(...),
    user=Depends(require_editor),
    svc: FontService = Depends(get_bucket_font_service),
):
    '''Upload one or more font files (TTF, OTF, WOFF, WOFF2) into a bucket.'''
    uploaded = []

    for file in files:
        data = await file.read()
        if not svc.upload(file.filename, data):
            logger.warning(
                'Font upload rejected for %s: invalid file %s (user: %s)',
                slug, file.filename, user.username,
            )
            raise HTTPException(400, f'Invalid font file: {file.filename}')
        uploaded.append(file.filename)

    logger.info('Uploaded %d font(s) to %s (user: %s)', len(uploaded), slug, user.username)
    await get_notifier().notify(slug)
    return {'uploaded': uploaded}


@router.delete('/{filename}', status_code=204)
async def delete_bucket_font(
    slug: str, filename: str,
    user=Depends(require_editor),
    svc: FontService = Depends(get_bucket_font_service),
):
    '''Delete a font file from a bucket.'''
    if not svc.delete(filename):
        logger.warning(
            'Font deletion rejected for %s: %s not found (user: %s)',
            slug, filename, user.username,
        )
        raise HTTPException(404, 'Font not found')

    logger.info('Deleted font %s from %s (user: %s)', filename, slug, user.username)
    await get_notifier().notify(slug)
