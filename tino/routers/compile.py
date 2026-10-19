'''REST endpoints for compiling Typst files to SVG, PDF, or PNG.'''

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from ..dependencies import get_compiler_service, require_viewer
from ..services.compiler import CompileError, CompilerService, zip_pngs

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/buckets/{slug}/compile', tags=['compile'])


def _compile_failed(exc: CompileError) -> HTTPException:
    '''Build the 422 response for a failed compile, with its diagnostics.'''
    return HTTPException(422, detail={
        'message': str(exc),
        'diagnostics': exc.diagnostics,
    })


@router.get('/pdf/{path:path}')
async def compile_pdf(
    slug: str, path: str,
    user=Depends(require_viewer),
    svc: CompilerService = Depends(get_compiler_service),
):
    '''Compile a .typ file and return the PDF.'''
    logger.info('Compiling PDF for %s/%s (user: %s)', slug, path, user.username)
    try:
        pdf_path = svc.compile_pdf(slug, path)
        filename = path.rsplit('/', maxsplit=1)[-1].replace('.typ', '.pdf')

        return FileResponse(
            pdf_path,
            filename=filename,
            media_type='application/pdf',
            background=BackgroundTask(pdf_path.unlink, missing_ok=True),
        )

    except FileNotFoundError as exc:
        raise HTTPException(404, 'File not found') from exc

    except CompileError as exc:
        raise _compile_failed(exc) from exc

    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/svg/{path:path}')
async def compile_svg(
    slug: str, path: str,
    user=Depends(require_viewer),
    svc: CompilerService = Depends(get_compiler_service),
):
    '''Compile a .typ file and return a list of SVG strings (one per page).'''
    logger.debug('Compiling SVG for %s/%s (user: %s)', slug, path, user.username)
    try:
        pages = svc.compile_svg(slug, path)
        return {'pages': pages}

    except FileNotFoundError as exc:
        raise HTTPException(404, 'File not found') from exc

    except CompileError as exc:
        raise _compile_failed(exc) from exc

    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/png/{path:path}')
async def compile_png(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    slug: str, path: str,
    ppi: int = 144, overview: bool = False,
    max_width: int = 2000, max_height: int = 2000,
    user=Depends(require_viewer),
    svc: CompilerService = Depends(get_compiler_service),
):
    '''Compile a .typ file and return a ZIP of ``page_N.png`` per page.

    Pass ``overview=true`` to also include an ``overview.png`` grid of all
    pages. *ppi* controls the rasterisation resolution (36-300).
    '''
    logger.debug('Compiling PNG for %s/%s (user: %s)', slug, path, user.username)
    try:
        result = svc.compile_png(
            slug, path, ppi=ppi, overview=overview,
            max_width=max_width, max_height=max_height,
        )

    except FileNotFoundError as exc:
        raise HTTPException(404, 'File not found') from exc

    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    except CompileError as exc:
        raise _compile_failed(exc) from exc

    except RuntimeError as exc:
        raise HTTPException(422, str(exc)) from exc

    filename = path.rsplit('/', maxsplit=1)[-1].rsplit('.', maxsplit=1)[0] + '.zip'
    return Response(
        content=zip_pngs(result['pages'], result['overview']),
        media_type='application/zip',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
