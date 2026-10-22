.. _Editor:

✏️ Editor
---------

TINO's editor is built on `CodeMirror 6 <https://codemirror.net/>`_ and
offers Typst-aware syntax highlighting, structural indentation, search and
navigation, code folding, and optional Vim keybindings.

Tabs
~~~~

Every opened file appears as a tab above the editor.
Click a tab to switch to it, or click the **×** button on a tab to close it.
Use **Close all tabs** to clear them all at once.
Tabs are persisted across page reloads.

Syntax highlighting
~~~~~~~~~~~~~~~~~~~~~

``.typ`` files are highlighted with a Typst-aware grammar: comments, strings,
keywords (``#let``, ``#show``, ``#import``, …), function calls, headings,
strong and emphasis, math, labels and references, numbers, and punctuation each
get their own colour. The palette is drawn from the corporate-design colours
and adapts to the active :ref:`theme <Theming>` (dark and light).

Formatting toolbar
~~~~~~~~~~~~~~~~~~~~

The toolbar above the editor provides common Typst formatting actions.
For the full syntax reference, see the `Typst documentation <https://typst.app/docs/reference/>`_.

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Action
     - Typst syntax
     - Description
   * - Bold
     - :code:`*…*`
     - Wrap the selection in asterisks.
   * - Italic
     - :code:`_…_`
     - Wrap the selection in underscores.
   * - Heading
     - ``=``
     - Cycle the current line's heading level (``=`` → ``==`` → ``===`` → ``====`` → plain text).
   * - Bullet list
     - ``-``
     - Start a bullet list on the current line.
   * - Numbered list
     - ``+``
     - Start a numbered list on the current line.
   * - Link
     - :code:`#link("…")`
     - Insert a link function call.
   * - Image
     - :code:`#image("…")`
     - Insert an image function call.
   * - Table
     - :code:`#table(…)`
     - Insert a 2×2 table skeleton.
   * - Inline code
     - ````` `…` `````
     - Wrap the selection in backticks.
   * - Code block
     - ````` ```…``` `````
     - Wrap the selection in triple backticks.
   * - Math
     - :code:`$…$`
     - Wrap the selection in dollar signs.

Indentation
~~~~~~~~~~~

The editor indents structurally. Pressing :kbd:`Enter` keeps the surrounding
indentation, adds a level after an opening bracket (``(``, ``[`` or ``{``), and
a line that begins with a closing bracket snaps back to match its opener. Plain
prose is left at its current indentation.

Lists continue automatically: pressing :kbd:`Enter` on a list item starts the
next item (numbered markers increment), while pressing :kbd:`Enter` on an empty
item ends the list.

Keyboard shortcuts
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Shortcut
     - Action
   * - :kbd:`Ctrl+S` / :kbd:`⌘S`
     - Save the current file.
   * - :kbd:`Ctrl+Z` / :kbd:`Ctrl+Y`
     - Undo / redo.
   * - :kbd:`Tab` / :kbd:`Shift+Tab`
     - Indent / dedent.
   * - :kbd:`Enter`
     - New line with structural indentation; continue a list.
   * - :kbd:`Ctrl+F` / :kbd:`⌘F`
     - Open the search panel (find & replace, with match-case / regexp / by-word options).
   * - :kbd:`F3` / :kbd:`Shift+F3`
     - Find next / previous.
   * - :kbd:`Ctrl+G` / :kbd:`⌘G`
     - Go to line.
   * - :kbd:`Ctrl+D` / :kbd:`⌘D`
     - Select the next occurrence of the selection (multi-cursor).

Folding and brackets
~~~~~~~~~~~~~~~~~~~~~~

Collapse a ``{…}`` or ``[…]`` block from the fold gutter beside the line
numbers, and click again to expand it. When the cursor sits next to a bracket,
its matching partner is highlighted.

Vim mode
~~~~~~~~

Click **Vim** in the toolbar to enable Vim keybindings. A status bar at the
bottom of the editor shows the current mode and ``:`` command line, and the
caret becomes a block cursor in normal mode. The setting is remembered per
browser — click **Vim** again to return to the default editing mode.

The usual motions and operators apply; ``u`` / :kbd:`Ctrl+R` undo and redo, and
``:w`` saves the file.

Saving
~~~~~~

Files are **auto-saved** a short moment after you stop typing — by default
250 ms, configurable via
:attr:`TINO_SAVE_DEBOUNCE_MS <tino.config.TINO_SAVE_DEBOUNCE_MS>`.
You can also save manually with the **Save** button, :kbd:`Ctrl+S`, or ``:w`` in
Vim mode. Unsaved files are marked with a dot on their tab.

Preview
~~~~~~~

The right-hand panel shows an SVG preview of the current ``.typ`` file.
The preview is re-rendered automatically after each save.

Use the **Zoom in** / **Zoom out** buttons (or the displayed percentage) to adjust the preview scale.

The **Generate** split button exports the current document as **PDF**, a ZIP of
**PNG** pages (with an overview grid), or — when the ``typst-pptx`` binary is
available — **PowerPoint** (``.pptx``). PowerPoint output is editable and
requires decks built with Touying 0.8 or newer.

Presentation mode
~~~~~~~~~~~~~~~~~

A **Present** button appears next to the zoom controls when the previewed file
looks like a deck: anything with more than one page, or a single page in a 16:9
or 4:3 aspect ratio. It plays the rendered pages one slide at a time — animated
builds included, because every animation step is already its own page. The
arrow next to it offers two ways to present.

**Present in this window** takes over the tab in full screen. **Presenter view**
is the speaker mode: it opens an *audience window* — a plain window showing only
the slide, which you can put on the projector and fullscreen (the button in its
corner, or :kbd:`F11`) — while TINO shows the console:

* the current slide, large;
* the speaker notes for that slide;
* the slide coming up next;
* the wall clock and a timer of how long you have been presenting, with a
  **Reset** button to start it again;
* the slide counter and a progress bar through the deck;
* buttons for the previous and next slide, and one to leave.

The notes are the ones Touying and Polylux record with ``#speaker-note[…]`` (or
``#pdfpc.speaker-note(…)``): they are read from the deck's pdfpc metadata, so
each note appears beside the slide it belongs to and stays up while you step
through that slide's animations. A deck without any simply says so. Notes are
shown as plain text, keeping their line breaks; the Markdown pdfpc would render
is not interpreted.

**Pointer options** in the console's bottom bar switches between the plain
pointer, a laser dot that follows your mouse, and a pen for drawing on the
slide. In pen mode a row of ink colours appears next to it, along with
**Clear this slide** and **Clear all slides**. **Lights off** hides the slide
from the audience while dimming it in the console, so you can keep your
bearings. What you point at is mirrored in the audience window, and drawings
stay with the slide you made them on until you leave presentation mode.

Navigation is shared: moving in either window moves both. Presenting follows the
same keys as the Typst web app:

* :kbd:`→`, :kbd:`Space`, :kbd:`Enter`, :kbd:`PageDown`, :kbd:`↓` or a left
  click — next slide.
* :kbd:`←`, :kbd:`PageUp`, :kbd:`↑` or a right click — previous slide.
* :kbd:`Home` / :kbd:`End` — first / last slide.
* :kbd:`L` — laser pointer, :kbd:`Shift+L` — pen, :kbd:`B` — lights off. Each
  key toggles its tool.
* :kbd:`Esc` — leave presentation mode.

A counter shows the current slide for a moment after each move. The deck keeps up
with the preview, so saving while presenting refreshes the slides in place and
stays on the current one — the audience window is told and refetches them.
Closing the audience window ends the presenter view.

Presenting is read-only and available to anyone who can view the bucket.
