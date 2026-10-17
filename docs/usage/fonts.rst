.. _Fonts:

🔤 Custom fonts
---------------

TINO supports custom fonts for Typst compilations. Fonts placed in the
:attr:`TINO_FONT_DIR <tino.config.TINO_FONT_DIR>` directory are
automatically available to all documents via the ``--font-path`` flag.

.. note::

    Supported formats: **TTF**, **OTF**, **WOFF**, **WOFF2**.

Managing fonts via the UI
~~~~~~~~~~~~~~~~~~~~~~~~~

Administrators can manage fonts directly from the toolbar:

1. Click the **font** icon in the top-right toolbar.
2. Click **Upload fonts** to add one or more font files.
3. Hover over a font and click the **delete** icon to remove it.

.. note::

    Font management is restricted to administrators.

Bucket-specific fonts
~~~~~~~~~~~~~~~~~~~~~

Each bucket can also carry its own fonts in a ``fonts/`` directory inside the
bucket's git repository. They are versioned with the documents, travel with the
bucket, and take **precedence over global fonts** when both provide the same
family.

Anyone with the **editor** role on a bucket can manage its fonts:

1. Open the **fonts** dialog from the toolbar.
2. The **Bucket fonts** section manages the active bucket's fonts; the
   **Global fonts** section (administrators only) manages the instance-wide set.

Bucket fonts are also exposed through the :ref:`MCP server <MCP server>`
(``list_bucket_fonts``, ``upload_bucket_fonts``, ``delete_bucket_font``) and
the REST API (``/api/buckets/{slug}/fonts``).

Providing fonts via Docker
~~~~~~~~~~~~~~~~~~~~~~~~~~

Fonts can also be provided at container level without the UI, for example
via a bind mount:

.. code-block:: bash

    docker run -d \
        -e TINO_FONT_DIR=/fonts
        -v /fonts:/fonts \
        …

Or by adding them to the image at build time:

.. code-block:: dockerfile

    # Set environment variable so TINO / Typst knows where to look for the fonts.
    ENV TINO_FONT_DIR=/fonts

    # Copy the fonts into the Docker image.
    COPY fonts/ /fonts
