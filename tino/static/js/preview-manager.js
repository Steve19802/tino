import {
  PREVIEW_PAGE_WIDTH, SINGLE_ITEM, ZOOM_MAX, ZOOM_MIN, ZOOM_STEP,
  ZOOM_WHEEL_FACTOR,
} from './constants.js'
import { HttpClient } from './http-client.js'

/**
 * Manages preview rendering and zoom controls.
 */

export class PreviewManager {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this.exportFormat = 'pdf'
    this.exportAnimations = 'auto'
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
    const hasPptx = Boolean(this.app.config && this.app.config.pptxVersion)
    document.getElementById('export-pptx').classList.toggle('hidden', !hasPptx)
    document.getElementById('export-animations').classList.toggle('hidden', !hasPptx)
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
      if (gen === this._renderGen)
        this._renderError(preview, err)
    }
  }

  /** Render a compile error: structured diagnostics, or the raw message. */

  _renderError(preview, err) {
    const diagnostics = err.diagnostics || []
    if (diagnostics.length)
      preview.replaceChildren(this._renderDiagnostics(diagnostics))
    else
      preview.replaceChildren(PreviewManager._renderRawError(err.message))
  }

  /** Build the list of diagnostics. */

  _renderDiagnostics(diagnostics) {
    const list = document.createElement('div')
    list.className = 'preview-errors'
    diagnostics.forEach(diag => list.appendChild(this._renderDiagnostic(diag)))
    return list
  }

  /** Build one diagnostic entry, clickable only when it has a location. */

  _renderDiagnostic(diag) {
    const item = document.createElement(diag.file ? 'button' : 'div')
    item.className = `preview-error-item preview-error-${diag.severity}`
    item.appendChild(PreviewManager._span('preview-error-message', diag.message))
    if (diag.file)
      this._makeClickable(item, diag)
    return item
  }

  /** Wire the entry to jump to its location on click. */

  _makeClickable(item, diag) {
    item.appendChild(PreviewManager._span(
      'preview-error-loc', `${diag.file}:${diag.line}:${diag.column}`))
    item.type = 'button'
    item.addEventListener('click', () => this._jumpToDiagnostic(diag))
  }

  /** Open the diagnostic's file and move the caret to its position. */

  async _jumpToDiagnostic(diag) {
    await this.app.editor.openFile(diag.file)
    // Typst can report column 0; setCursor is 1-based.
    this.app.els.editor.setCursor(diag.line, Math.max(SINGLE_ITEM, diag.column))
  }

  /** Create a span with a class and text content. */

  static _span(className, text) {
    const span = document.createElement('span')
    span.className = className
    span.textContent = text
    return span
  }

  /** Fallback when there are no structured diagnostics. */

  static _renderRawError(message) {
    const pre = document.createElement('pre')
    pre.className = 'preview-error'
    pre.textContent = message
    return pre
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
    return this._download('pdf')
  }

  /** Download the current .typ file as a ZIP of rendered PNG pages. */

  downloadPng() {
    return this._download('png')
  }

  /** Download the current .typ file as an editable PowerPoint (.pptx). */

  downloadPptx() {
    return this._download('pptx')
  }

  /** Trigger a browser download of the current file in *format*. */

  async _download(format) {
    if (!this.app.bucket || !this.target)
      return
    const slug = encodeURIComponent(this.app.bucket)
    const params = new URLSearchParams()
    if (format === 'png')
      params.set('overview', 'true')
    if (format === 'pptx')
      params.set('animations', this.exportAnimations)
    const query = params.toString() ? `?${params}` : ''
    const url = `/api/buckets/${slug}/compile/${format}/${this.target}${query}`

    try {
      const res = await fetch(url, { credentials: 'same-origin' })
      if (!res.ok)
        throw await HttpClient._error(res)
      const objectUrl = URL.createObjectURL(await res.blob())
      PreviewManager._saveUrl(objectUrl, this._exportName(format))
      setTimeout(() => URL.revokeObjectURL(objectUrl), 10000)
      if (format === 'pptx') {
        const fallbacks = Number(res.headers.get('X-Tino-Pptx-Fallbacks') || '0')
        if (fallbacks > 0) {
          this.app.toast.info(
            `${fallbacks} element(s) exported as pictures, not editable text.`,
          )
        }
      }
    }
    catch (err) {
      this.app.toast.error(err.message)
    }
  }

  /** The current file's name with the export's extension. */

  _exportName(format) {
    const extension = format === 'png' ? 'zip' : format
    return this.target.split('/').pop().replace(/\.typ$/u, `.${extension}`)
  }

  /** Trigger a download for *url*, optionally under a given file name. */

  static _saveUrl(url, name = '') {
    const link = document.createElement('a')
    link.href = url
    link.download = name
    link.click()
  }

  /** Run the export format currently selected in the split button. */

  exportCurrent() {
    if (this.exportFormat === 'png')
      this.downloadPng()
    else if (this.exportFormat === 'pptx')
      this.downloadPptx()
    else
      this.downloadPdf()
  }

  /** Select the export format and sync the main button label. */

  setExportFormat(format) {
    this.exportFormat = format
    const labels = {
      pdf: ['Generate PDF', 'Download PDF'],
      png: ['Generate PNGs', 'Download PNGs (ZIP)'],
      pptx: ['Generate PowerPoint', 'Download PowerPoint (.pptx)'],
    }
    const [label, title] = labels[format] || labels.pdf
    document.getElementById('btn-export-label').textContent = label
    document.getElementById('btn-export-main').title = title
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

  /** Bind zoom (buttons + Ctrl+wheel), export (PDF/PNG/PPTX), and pin. */

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

    document.getElementById('export-animations')
      .addEventListener('click', evt => evt.stopPropagation())

    document.getElementById('export-animations-select')
      .addEventListener('change', evt => {
        this.exportAnimations = evt.target.value
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
