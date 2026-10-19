import {
  PREVIEW_PAGE_WIDTH, SINGLE_ITEM, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP,
  ZOOM_WHEEL_FACTOR, escapeHtml,
} from './constants.js'

/**
 * Manages preview rendering and zoom controls.
 */

export class PreviewManager {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this.exportFormat = 'pdf'
  }

  /** The file the preview renders: the pinned file, else the active file. */

  get target() {
    return this.app.pinnedPreview || this.app.currentFile
  }

  /**
   * Compile the preview target (the pinned file when one is pinned, otherwise
   * the current file) and render its SVG pages in the preview pane.
   */

  async update() {
    const isTyp = this.target && this.target.endsWith('.typ')
    this._renderPinControls()
    document.getElementById('btn-export')
      .classList.toggle('hidden', !isTyp)
    if (isTyp)
      await this.compile()
    else
      this.clear()
  }

  /** Pin the preview to the current .typ file, or unpin if already pinned. */

  togglePin() {
    if (this.app.pinnedPreview)
      this.app.pinnedPreview = null
    else if (this.app.currentFile && this.app.currentFile.endsWith('.typ'))
      this.app.pinnedPreview = this.app.currentFile
    this.update()
  }

  /** Sync the pin button and pinned-file label with the current pin state. */

  _renderPinControls() {
    const pinned = this.app.pinnedPreview
    const cur = this.app.currentFile
    const canPin = Boolean(pinned) || Boolean(cur && cur.endsWith('.typ'))
    const btn = document.getElementById('btn-pin-preview')
    btn.classList.toggle('hidden', !canPin)
    btn.classList.toggle('active', Boolean(pinned))
    btn.title = PreviewManager._pinTitle(pinned)
    PreviewManager._renderPinLabel(pinned)
  }

  static _pinTitle(pinned) {
    if (pinned)
      return `Preview pinned to ${pinned} — click to unpin`
    return 'Pin preview to this file'
  }

  static _renderPinLabel(pinned) {
    const label = document.getElementById('preview-pin-label')
    label.classList.toggle('hidden', !pinned)
    if (pinned) {
      // Show only the filename; the full path lives in the hover tooltip.
      label.textContent = pinned.split('/').pop()
      label.title = pinned
    }
  }

  /** Show a placeholder when the current file has no preview. */

  clear() {
    this.app.els.previewPage.innerHTML =
      '<p class="preview-empty">No preview available for this file.</p>'
  }

  /** Compile the current .typ file via the API and render SVG pages. */

  async compile() {
    if (!this.app.bucket || !this.target)
      return
    this._renderGen = (this._renderGen || 0) + SINGLE_ITEM
    const gen = this._renderGen
    const preview = this.app.els.previewPage
    try {
      const result = await this.app.api.compile(this.app.bucket, this.target)
      if (gen === this._renderGen)
        PreviewManager._renderPages(preview, result.pages)
    }
    catch (err) {
      if (gen === this._renderGen) {
        preview.innerHTML =
          `<pre class="preview-error">${escapeHtml(err.message)}</pre>`
      }
    }
  }

  /** Build all SVG pages off-DOM and swap them in with a single reflow. */

  static _renderPages(preview, pages) {
    const fragment = document.createDocumentFragment()
    pages.forEach(svg => {
      const page = document.createElement('div')
      page.className = 'preview-svg-page'
      page.innerHTML = svg
      fragment.appendChild(page)
    })
    preview.replaceChildren(fragment)
  }

  /** Download the current .typ file as a compiled PDF. */

  downloadPdf() {
    this._download('pdf')
  }

  /** Download the current .typ file as a ZIP of rendered PNG pages. */

  downloadPng() {
    this._download('png')
  }

  /** Trigger a browser download of the current file in *format*. */

  _download(format) {
    if (!this.app.bucket || !this.target)
      return
    const slug = encodeURIComponent(this.app.bucket)
    const query = format === 'png' ? '?overview=true' : ''
    const link = document.createElement('a')
    link.href = `/api/buckets/${slug}/compile/${format}/${this.target}${query}`
    link.download = ''
    link.click()
  }

  /** Run the export format currently selected in the split button. */

  exportCurrent() {
    if (this.exportFormat === 'png')
      this.downloadPng()
    else
      this.downloadPdf()
  }

  /** Select the export format and sync the main button label. */

  setExportFormat(format) {
    this.exportFormat = format
    const isPng = format === 'png'
    document.getElementById('btn-export-label').textContent =
      isPng ? 'Generate PNGs' : 'Generate PDF'
    document.getElementById('btn-export-main').title =
      isPng ? 'Download PNGs (ZIP)' : 'Download PDF'
  }

  /** Close the export format menu. */

  _closeExportMenu() {
    const menu = document.getElementById('export-menu')
    if (menu.classList.contains('hidden'))
      return
    menu.classList.add('hidden')
    document.getElementById('btn-export-arrow')
      .setAttribute('aria-expanded', 'false')
  }

  /** Bind zoom (buttons + Ctrl+wheel), export (PDF/PNG), and pin controls. */

  bindZoom() {
    document.getElementById('btn-zoom-in')
      .addEventListener('click', () => this.setZoom(this.app.zoom + ZOOM_STEP))

    document.getElementById('btn-zoom-out')
      .addEventListener('click', () => this.setZoom(this.app.zoom - ZOOM_STEP))

    const viewport = document.getElementById('preview-viewport')
    viewport.addEventListener('wheel', ev => this._onWheelZoom(ev), { passive: false })

    const menu = document.getElementById('export-menu')
    const arrow = document.getElementById('btn-export-arrow')

    document.getElementById('btn-export-main')
      .addEventListener('click', () => this.exportCurrent())

    arrow.addEventListener('click', evt => {
      evt.stopPropagation()
      const willOpen = menu.classList.contains('hidden')
      menu.classList.toggle('hidden', !willOpen)
      arrow.setAttribute('aria-expanded', String(willOpen))
    })

    menu.addEventListener('click', evt => {
      const item = evt.target.closest('.export-item')
      if (!item)
        return
      this._closeExportMenu()
      this.setExportFormat(item.dataset.format)
      this.exportCurrent()
    })

    document.addEventListener('click', () => this._closeExportMenu())
    document.addEventListener('keydown', evt => {
      if (evt.key === 'Escape')
        this._closeExportMenu()
    })

    document.getElementById('btn-pin-preview')
      .addEventListener('click', () => this.togglePin())
  }

  /** Set the preview zoom percentage (clamped), reflowing the page width. */

  setZoom(zoom) {
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(zoom)))
    if (clamped === this.app.zoom)
      return
    this.app.zoom = clamped
    this.app.els.previewPage.style.width =
      `${PREVIEW_PAGE_WIDTH * clamped / 100}px`
    this.app.els.zoomLabel.textContent = `${clamped}%`
  }

  /**
   * Zoom on Ctrl/⌘ + wheel. Plain wheel is left to normal scrolling. Trackpad
   * pinch arrives in Chrome as wheel events with ctrlKey set, so it works for
   * free. Behaves exactly like the zoom buttons: the browser keeps the scroll
   * position as the page width reflows, so no scroll compensation is needed.
   */

  _onWheelZoom(ev) {
    if (!ev.ctrlKey)
      return
    ev.preventDefault()
    this.setZoom(
      this.app.zoom * (ev.deltaY < 0 ? ZOOM_WHEEL_FACTOR : SINGLE_ITEM / ZOOM_WHEEL_FACTOR),
    )
  }

}
