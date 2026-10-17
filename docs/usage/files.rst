.. _Files:

📄 Files
--------

Creating files
~~~~~~~~~~~~~~

Click the **New file** button in the file panel header to create an empty file.
You will be prompted for a file name, including any path prefix (e.g. ``chapters/intro.typ``).

From template
~~~~~~~~~~~~~

Click the **New from template** button to initialise the bucket from a Typst template.
The dialog offers two tabs:

- **Custom** — templates from the local package directory.
- **Typst Universe** — templates from the public `Typst package registry <https://typst.app/universe>`_.

Uploading files
~~~~~~~~~~~~~~~

Drag and drop files from your desktop onto the file explorer panel.
If you drop onto a folder, the files are uploaded into that folder.

.. hint::

    ZIP archives are extracted automatically on upload.

Bulk transfer via the API
~~~~~~~~~~~~~~~~~~~~~~~~~

A bucket's working tree can be downloaded as a ZIP and re-uploaded as a ZIP,
which acts as a simple *clone / push* workflow for agents or automation:

- ``GET /api/buckets/{slug}/files/download`` — download all source files as ``<slug>.zip``.
- ``POST /api/buckets/{slug}/files/upload`` — upload one or more files; ZIP
  archives are extracted automatically (optionally under a ``prefix``).

Extraction is additive: it overwrites matching files and leaves everything else
untouched. Uploads require the editor role.

The :ref:`MCP server <MCP server>` exposes the same workflow through the
``download_bucket`` and ``upload_bucket_zip`` tools.

Renaming and deleting
~~~~~~~~~~~~~~~~~~~~~

Hover over a file or folder in the tree to reveal the **Rename** and **Delete** action buttons.
Files can also be moved into directories by drag and drop.
