/**
 * Shared constants, icons, and utilities used across the TINO frontend.
 */

/** HTTP status code for responses with no body. */

export const HTTP_NO_CONTENT = 204

/** HTTP status code for unauthenticated requests. */

export const HTTP_UNAUTHORIZED = 401

/** Percentage increment for preview zoom in/out. */

export const ZOOM_STEP = 10

/** Minimum allowed preview zoom percentage. */

export const ZOOM_MIN = 50

/** Maximum allowed preview zoom percentage. */

export const ZOOM_MAX = 200

/** Base layout width (px) of the preview page at 100% zoom. */

export const PREVIEW_PAGE_WIDTH = 595

/** Multiplicative zoom factor applied per mouse-wheel notch. */

export const ZOOM_WHEEL_FACTOR = 1.1

/** Minimum drag width in px for the left (file tree) panel. */

export const PANEL_MIN_WIDTH_LEFT = 200

/** Minimum drag width in px for the right (preview) panel. */

export const PANEL_MIN_WIDTH_RIGHT = 350

/** Maximum drag width in px for resizable panels. */

export const PANEL_MAX_WIDTH = 500

/** Sentinel returned by indexOf when an element is not found. */

export const INDEX_NOT_FOUND = -1

/** Minimum query length before the global search runs. */

export const SEARCH_MIN_CHARS = 2

/** Debounce delay (ms) for the global search input. */

export const SEARCH_DEBOUNCE_MS = 200

/** Length argument for single-item splice operations. */

export const SINGLE_ITEM = 1

/** Characters to keep when slicing an ISO timestamp (YYYY-MM-DD HH:MM:SS). */

export const ISO_DATETIME_LEN = 19

/** Number of hex characters shown for abbreviated commit SHAs. */

export const SHA_SHORT_LEN = 7

/** Material Symbols icon for a file node in the tree. */

export const FILE_ICON =
  '<span class="material-symbols-outlined file-icon">' +
  'description</span>'

/** Material Symbols icon for a folder node in the tree. */

export const FOLDER_ICON =
  '<span class="material-symbols-outlined folder-icon">' +
  'folder</span>'

/** Material Symbols expand/collapse icon for folder nodes. */

export const TOGGLE_ICON =
  '<span class="material-symbols-outlined folder-toggle">' +
  'expand_more</span>'

/** Maps git file status to its Material Symbols icon name. */

export const STATUS_ICONS = {
  deleted: 'do_not_disturb_on',
  modified: 'pending',
  untracked: 'add_circle',
}

/** Escape &, <, > for safe insertion into HTML. */

export const escapeHtml = str =>
  str.replace(/&/gu, '&amp;').replace(/</gu, '&lt;').replace(/>/gu, '&gt;')

/** Maps git file status to its CSS badge class. */

export const STATUS_CLASSES = {
  deleted: 'status-deleted',
  modified: 'status-modified',
  untracked: 'status-untracked',
}

/** Aspect ratios (width/height) that mark a page as a slide. */

export const PRESENTATION_RATIOS = [
  { height: 9, width: 16 },
  { height: 3, width: 4 },
]

/** Tolerance when matching a page's aspect ratio to a known slide ratio. */

export const PRESENTATION_RATIO_TOLERANCE = 0.03

/** Time (ms) the slide counter stays visible after navigating. */

export const PRESENTATION_COUNTER_MS = 1600

/** BroadcastChannel name shared by the presenter console and its audience. */

export const PRESENTATION_CHANNEL = 'tino-presentation'

/** Window name for the audience window, so relaunches reuse the same one. */

export const PRESENTATION_WINDOW = 'tino-presentation'

/** Window features for the audience window: a plain, resizable popup. */

export const PRESENTATION_WINDOW_FEATURES = 'popup,width=1280,height=800'

/** Static page loaded in the audience window. */

export const PRESENTATION_PAGE = 'present.html'

/** Presentation action performed for each key, shared by console and audience. */

export const PRESENTATION_KEYS = new Map([
  [' ', 'next'],
  ['ArrowDown', 'next'],
  ['ArrowRight', 'next'],
  ['Enter', 'next'],
  ['PageDown', 'next'],
  ['ArrowLeft', 'prev'],
  ['ArrowUp', 'prev'],
  ['PageUp', 'prev'],
  ['End', 'last'],
  ['Home', 'first'],
  ['Escape', 'exit'],
])

/** Interval (ms) between presenter-console clock ticks. */

export const PRESENTATION_TICK_MS = 1000
