.. _ADR-12:

ADR-12: Presentation mode
=========================

Context
-------

TINO renders a ``.typ`` document as a stack of SVG pages — one per page, with
fonts inlined — and shows them in the preview panel. Decks built with Touying
compile to one page per animation step, so that same stack is already a slide
deck. Users wanted to give a talk straight from TINO instead of exporting a PDF
and opening a separate viewer, and the Typst web app's presentation mode is the
reference experience.

Two questions had to be answered.

1. **Reuse the preview pane, or build a separate component?** The preview panel
   owns zoom, the export split button and compile diagnostics. Presentation is a
   modal, full-screen experience with its own lifecycle (keyboard capture, the
   full-screen API, entering and leaving), which does not belong in that panel.
2. **Where does slide geometry come from?** The preview needs the page count and
   the page aspect ratio to fit a slide to the screen. Neither is returned by the
   compile API today.

Decision
--------

TINO adds a dedicated ``PresentationManager`` that reuses the pages the preview
has already compiled; it never re-renders anything itself.

- ``PreviewManager`` remembers the last good render and publishes it to the
  presentation manager after every successful compile. The deck therefore tracks
  saves while it is on screen and stays on the current slide, and a failed
  compile leaves the last good deck in place.
- Presentation is a full-screen overlay that shows one page at a time. It follows
  the Typst web app's navigation (arrows, space, Enter and clicks move; Escape
  leaves) and requests full-screen inside the click that started it, because
  awaiting the compile first would spend the user gesture. When the request is
  refused the covering overlay still presents in the tab, and leaving full-screen
  by any route leaves presentation mode.
- Slide geometry is derived client-side by ``PresentationGeometry`` from the SVG
  root's ``viewBox`` or ``width``/``height`` attributes. No backend, API or MCP
  change is needed: presentation compiles through the existing
  ``GET /api/buckets/{slug}/compile/svg/{path}`` route.
- The Present button appears only for decks — more than one page, or a single
  page in a 16:9 or 4:3 aspect ratio — mirroring the web app's automatic
  detection, and stays out of the way for ordinary documents.
- Presenting is read-only and needs no new permission: it is available to anyone
  who can view the bucket.

Consequences
------------

Positive
~~~~~~~~

- | **Reuses the compile**
  | Presentation shows the pages the preview already produced, inlined fonts and
  | all, so entering a talk is instant and needs no second render path.
- | **No backend change**
  | Geometry comes from the SVG the preview already has; the API, the compiler
  | service and the MCP tools are untouched.
- | **Works for any document**
  | Nothing is Touying-specific: any multi-page or slide-sized ``.typ`` can be
  | presented, animated builds included.
- | **Keeps up with edits**
  | Saving while presenting refreshes the slides in place and preserves the
  | current slide, so a late fix does not restart the talk.

Negative
~~~~~~~~

- | **SVG only**
  | Slides are rendered SVG, not a PDF viewer, so there is no text selection or
  | PDF outline in presentation mode.
- | **No presenter window or notes yet**
  | Speaker notes, a second-monitor presenter view, the timer and the laser and
  | pen tools are not part of this change.
- | **Animation steps are pages**
  | ``#pause`` steps appear as separate slides, which matches the PDF but means
  | the slide count is the page count.
- | **Heuristic detection**
  | The Present button's visibility and the slide fit rely on reading page size
  | from the SVG; an unusual document may need the button to be shown by hand.
