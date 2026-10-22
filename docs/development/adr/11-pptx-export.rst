.. _ADR-11:

ADR-11: PowerPoint export
=========================

Context
-------

Users want editable PowerPoint (``.pptx``) output, not only the PDF and SVG that
Typst produces. A ``.pptx`` cannot be reconstructed reliably from a rasterised
PDF: real text boxes, tables, lists, shapes and speaker notes have to be
recovered from the document, not guessed from pixels.

TINO decks are built with Touying, the Typst presentation framework. Three
approaches were considered:

1. **PDF → PPTX** (LibreOffice or a PDF converter): yields static pictures or a
   poorly editable approximation, needs a heavyweight runtime, and loses text.
2. **SVG/PDF intermediate**: Typst's SVG often carries text as positioned glyphs,
   so a converter would have to re-derive text runs and styles.
3. **A dedicated exporter on Typst's frames**: read the document model directly
   and emit DrawingML objects.

Decision
--------

TINO delegates PowerPoint export to the standalone `typst-pptx
<https://github.com/Steve19802/typst-pptx>`_ binary — a separate Rust tool that
builds editable slides from Typst's frames with no PDF/SVG intermediate.

- The binary is installed in the image from its GitHub release. Its per-target
  static builds use the same target names as Typst, so TINO's existing
  ``TYPST_TARGET`` switch is reused (``TYPST_PPTX_VERSION`` pins the release).
- Export is exposed as ``GET /api/buckets/{slug}/compile/pptx/{path}``, the
  ``compile_pptx`` MCP tool, and the preview's **Generate** split button.
- :attr:`TINO_PPTX_BINARY <tino.config.TINO_PPTX_BINARY>` names the binary. When
  it is not found on ``$PATH`` the feature is disabled: ``/health`` and
  ``/api/config`` report ``null``, the endpoint answers ``501``, and the UI hides
  the option. A missing binary is never a startup error.
- The binary embeds the exact Typst version it was built against. The image's
  ``typst --version`` must match it, so a CI check verifies the pair and
  ``TYPST_PPTX_VERSION`` is bumped together with ``TYPST_VERSION``.
- Content PowerPoint cannot express (equations, skewed or mirrored text, tiling
  fills, …) is exported as a picture at its exact position and listed in the
  ``--report`` JSON. Its ``baked`` count is returned in the
  ``X-Tino-Pptx-Fallbacks`` header and surfaced as a toast.
- Font paths, the package path and the root are passed through exactly as for
  ``typst``, so bucket/global fonts and the package resolution behave the same.

Consequences
------------

Positive
~~~~~~~~

- | **Editable output**
  | Text, tables, lists and shapes map to native PowerPoint objects, not images.
- | **Typst's look**
  | Layout derives from Typst's frames; text is verified to within ~0.5 pt.
- | **No new app runtime**
  | The exporter is a static binary; nothing is added to the Python process.
- | **Explicit fidelity report**
  | Baked items and non-embedded fonts are reported per slide and source position.

Negative
~~~~~~~~

- | **An extra binary to ship**
  | The image grows by ~44 MB and the release must be tracked per platform.
- | **Version coupling**
  | ``typst`` and ``typst-pptx`` must be upgraded together, enforced by CI.
- | **Touying 0.8+ only**
  | Decks built with Touying 0.7 or older cannot be exported; the exporter
  | returns an export error naming the required version.
- | **Best-effort conversion**
  | The exporter is young (``0.x``); complex constructs may fall back to a baked
  | picture, which the report and the fallback toast make visible.
