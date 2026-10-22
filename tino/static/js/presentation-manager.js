import { PRESENTATION_COUNTER_MS, SINGLE_ITEM } from './constants.js'
import { PresentationGeometry } from './presentation-geometry.js'

/**
 * Full-screen presentation of the compiled preview pages.
 *
 * Shows the SVG pages the preview already compiled, one at a time, like a
 * slide deck. Navigation follows the Typst web app: arrows, space, Enter and
 * clicks move between slides, and Escape leaves. The page list stays in sync
 * with the preview, so a recompile while presenting updates the deck in place
 * without losing the current slide.
 */

/** Keys that advance to the next slide. */

const NEXT_KEYS = new Set([' ', 'ArrowDown', 'ArrowRight', 'Enter', 'PageDown'])

/** Keys that go back to the previous slide. */

const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp', 'PageUp'])

export class PresentationManager {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this.active = false
    this.pages = []
    this.index = 0
    this.ratio = PresentationGeometry.fallbackRatio()
    this._counterTimer = null
    this._onKey = ev => this._handleKey(ev)
    this._onClick = () => this.next()
    this._onContext = ev => {
      ev.preventDefault()
      this.prev()
    }

    this._onFullscreen = () => {
      if (this.active && !document.fullscreenElement)
        this.exit()
    }
  }

  /** Bind the preview's Present button and the overlay's exit button. */

  bind() {
    document.getElementById('btn-present')
      .addEventListener('click', () => this.start())
    document.getElementById('btn-present-exit')
      .addEventListener('click', ev => {
        ev.stopPropagation()
        this.exit()
      })
  }

  /**
   * Enter presentation mode for the file the preview is rendering. Full-screen
   * is requested straight away, inside the click that started this, because
   * awaiting first would spend the user gesture and the browser would refuse it.
   */

  start() {
    if (this.active)
      return
    const overlay = this.app.els.presentation
    this.active = true
    overlay.classList.remove('hidden')
    overlay.setAttribute('aria-hidden', 'false')
    this._bind()
    PresentationManager._requestFullscreen(overlay)
    this._load()
  }

  /** Leave presentation mode, release the screen, and clear the slide. */

  exit() {
    if (!this.active)
      return
    this.active = false
    this._unbind()
    const overlay = this.app.els.presentation
    overlay.classList.add('hidden')
    overlay.setAttribute('aria-hidden', 'true')
    this.app.els.presentationStage.replaceChildren()
    clearTimeout(this._counterTimer)
    PresentationManager._releaseFullscreen()
  }

  /** Advance to the next slide, if there is one. */

  next() {
    const last = this.pages.length - SINGLE_ITEM
    if (this.index >= last)
      return
    this._show(this.index + SINGLE_ITEM)
  }

  /** Go back to the previous slide, if there is one. */

  prev() {
    if (this.index <= 0)
      return
    this._show(this.index - SINGLE_ITEM)
  }

  /**
   * Adopt a fresh compile from the preview, so the deck tracks saves while it
   * is on screen without losing the current slide. The Present button follows
   * the render even when idle.
   */

  onPages(render) {
    const presentable = PresentationGeometry.canPresent(render && render.pages)
    document.getElementById('btn-present').classList.toggle('hidden', !presentable)
    if (!this.active)
      return
    if (!render || !render.pages.length) {
      this.app.toast.error('Nothing to present.')
      this.exit()
      return
    }
    this.pages = render.pages
    this._reflow()
  }

  /** Compile the target if needed, then adopt the render. */

  async _load() {
    const render = await PresentationManager._resolveRender(this.app)
    if (!this.active)
      return
    if (!render || !render.pages.length) {
      this.app.toast.error('Nothing to present.')
      this.exit()
      return
    }
    this._adopt(render)
  }

  /** The preview's current render, compiling first when it is stale. */

  static async _resolveRender(app) {
    const cached = PresentationManager._cachedRender(app)
    if (cached)
      return cached
    await app.preview.compile()
    return PresentationManager._cachedRender(app)
  }

  /** The preview's last good render, but only for the current target. */

  static _cachedRender(app) {
    const render = app.preview.lastRender
    if (!render || render.bucket !== app.bucket)
      return null
    if (render.target !== app.preview.target)
      return null
    return render
  }

  /** Take over *render*'s pages, starting at the first slide. */

  _adopt(render) {
    this.pages = render.pages
    this.index = 0
    this._reflow()
  }

  /** Measure the deck, size the overlay, and repaint at the current index. */

  _reflow() {
    const ratio = PresentationGeometry.pageRatio(this.pages[0])
    if (ratio)
      this.ratio = ratio
    this.app.els.presentation
      .style.setProperty('--presentation-ratio', String(this.ratio))
    this._show(this.index)
  }

  /** Paint the slide at *index* (clamped) and flash the progress counter. */

  _show(index) {
    const clamped = Math.min(Math.max(index, 0), this.pages.length - SINGLE_ITEM)
    const counter = this.app.els.presentationCounter
    this.index = clamped
    this.app.els.presentationStage.innerHTML = this.pages[clamped]
    counter.textContent = `${this.index + SINGLE_ITEM} / ${this.pages.length}`
    counter.classList.remove('presentation-counter-dim')
    clearTimeout(this._counterTimer)
    this._counterTimer = setTimeout(
      () => counter.classList.add('presentation-counter-dim'),
      PRESENTATION_COUNTER_MS,
    )
  }

  /** Handle a key while presenting: leave, or move through the deck. */

  _handleKey(ev) {
    if (!this.active)
      return
    if (ev.key === 'Escape') {
      this.exit()
      return
    }
    if (this._navigate(ev.key))
      ev.preventDefault()
  }

  /** Move for the navigation keys; true when the key was consumed. */

  _navigate(key) {
    if (NEXT_KEYS.has(key)) {
      this.next()
      return true
    }
    if (PREV_KEYS.has(key)) {
      this.prev()
      return true
    }
    return this._jump(key)
  }

  /** Jump to the first or last slide; true when the key was consumed. */

  _jump(key) {
    if (key === 'Home') {
      this._show(0)
      return true
    }
    if (key === 'End') {
      this._show(this.pages.length - SINGLE_ITEM)
      return true
    }
    return false
  }

  /** Attach the listeners that are only live while presenting. */

  _bind() {
    document.addEventListener('keydown', this._onKey)
    document.addEventListener('fullscreenchange', this._onFullscreen)
    const overlay = this.app.els.presentation
    overlay.addEventListener('click', this._onClick)
    overlay.addEventListener('contextmenu', this._onContext)
  }

  /** Detach the listeners bound by :meth:`_bind`. */

  _unbind() {
    document.removeEventListener('keydown', this._onKey)
    document.removeEventListener('fullscreenchange', this._onFullscreen)
    const overlay = this.app.els.presentation
    overlay.removeEventListener('click', this._onClick)
    overlay.removeEventListener('contextmenu', this._onContext)
  }

  /** Request full-screen on *overlay*, tolerating a refusal. */

  static _requestFullscreen(overlay) {
    if (!overlay.requestFullscreen)
      return
    overlay.requestFullscreen().catch(() => {
      // Full-screen can be refused, for instance with no transient activation.
      // The overlay still covers the app, so presenting continues in the tab.
    })
  }

  /** Leave full-screen, if we still hold it. */

  static _releaseFullscreen() {
    if (!document.fullscreenElement)
      return
    document.exitFullscreen().catch(() => {
      // The browser can refuse if the screen was already released; ignore it.
    })
  }

}
