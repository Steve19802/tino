'''Server-level MCP instructions, shared by the MCP server and the REST API.

Kept free of the MCP SDK so the bucket settings dialog can fetch the full
instruction text (built-in plus the ``TINO_MCP_INSTRUCTIONS`` override) without
pulling in the MCP server machinery.
'''

from .. import config

#: Built-in instructions describing TINO and how an agent should use the tools.
BASE_INSTRUCTIONS = '''\
TINO is a collaborative Typst document platform.
Documents live in *buckets* (git repositories).
Use these tools to list, read, write, compile, and commit Typst source files.
Always compile after editing to verify the document is valid.
Use ``compile_png`` to rasterise a document's pages to PNG (add ``overview``
for a grid image of every page) when you need to inspect the rendered output.
Use ``compile_pptx`` to export editable PowerPoint slides (Touying 0.8 or
newer); read ``report.baked`` to see what couldn't be exported natively.
Each bucket may have specific instructions.
Always list buckets first and follow any per-bucket guidance.
To locate a document by file name or content, use the ``search`` tool instead of
listing and reading every file.
For regex searches (e.g. section headings or imports), use ``grep``.
For small edits, prefer ``edit_file``/``patch_file`` over ``write_file`` — they
send only the changed text, saving tokens. After editing, re-read the affected
lines with ``read_file`` (pass ``start_line``/``end_line``) rather than the whole
file.
``patch_file`` changes are applied in order against the *evolving* content; an
``old_text`` must match exactly (whitespace and line endings matter). Use
``replace_all: true`` to replace every occurrence in one call. Tool failures
include the reason — e.g. which ``old_text`` did not match.
In JSON payloads, encode a literal backslash as ``\\\\`` and a newline as ``\\n``;
a lone ``\\`` is an invalid JSON escape.
To add many assets at once, prefer ``write_files`` over repeated ``write_file``
calls, or transfer the whole bucket with ``download_bucket``/``upload_bucket_zip``
— large or binary content should go through the ZIP tools, not a single
``write_file``.
Manage per-bucket fonts with ``list_bucket_fonts``/``upload_bucket_fonts``/
``delete_bucket_font``; bucket fonts take precedence over global fonts.
The server's Typst version is reported by ``compile_typst``/``compile_svg``/
``compile_pdf``; adapt syntax and package versions to it.
'''


def server_instructions() -> str:
    '''Return the full server-level instructions an MCP agent receives.

    This is :data:`BASE_INSTRUCTIONS` plus the optional
    :attr:`~tino.config.TINO_MCP_INSTRUCTIONS` global override.  Per-bucket
    instructions are appended separately (see the ``list_buckets`` tool).
    '''
    text = BASE_INSTRUCTIONS
    if config.TINO_MCP_INSTRUCTIONS:
        text += '\n' + config.TINO_MCP_INSTRUCTIONS + '\n'
    return text
