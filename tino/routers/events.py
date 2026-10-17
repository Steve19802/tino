'''WebSocket endpoint for bucket-level file change notifications.'''

import logging

from fastapi import APIRouter, HTTPException, WebSocket

from ..auth import check_access, get_ws_user
from ..dependencies import get_bucket_service, get_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/buckets/{slug}', tags=['events'])


@router.websocket('/events')
async def bucket_events(websocket: WebSocket, slug: str):
    '''Subscribe to file-change events for a bucket.'''
    user = get_ws_user(websocket)

    if user is None:
        await websocket.close(code=4401, reason='Not authenticated')
        return

    bucket = get_bucket_service().get(slug)

    if not bucket:
        await websocket.close(code=4004, reason='Bucket not found')
        return

    try:
        check_access(user, bucket.access, 'viewer', slug)
    except HTTPException:
        await websocket.close(code=4403, reason='Viewer role required')
        return

    notifier = get_notifier()
    logger.info('Bucket selected: %s (user: %s)', slug, user.username)
    await notifier.serve(websocket, slug)
