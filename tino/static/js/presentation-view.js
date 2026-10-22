import {
  PRESENTATION_COUNTER_MS, PRESENTATION_KEYS, SINGLE_ITEM,
} from './constants.js'

/**
 * The in-tab full-screen slide view.
 *
 * Shows the deck's pages one at a time on the app's own screen, and maps the
 * presentation keys and mouse buttons to presentation actions. It is one of the
 * two places a deck can be shown: the presenter console drives the other, an
 * audience window meant for a second display.
 */

export class PresentationView {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this._open = false
    this._dispatch = null
    this._counterTimer = null
    this._onKey = ev => this._key(ev)
    this._onClick = () => this._action('next')
    this._onContext = ev => this._context(ev)
    this._onFullscreen = () => this._fullscreenChange()
  }

  /** Whether the overlay is currently on screen. */

  get active() {
    return this._open
  }

  /**
   * Show the overlay and take over the screen. Full-screen is requested straight
   * away, inside the click that started presenting, because awaiting first would
   * spend the user gesture and the browser would refuse it.
   */

  open(dispatch) {
    this._dispatch = dispatch
    this._open = true
    const overlay = this.app.els.presentation
    overlay.classList.remove('hidden')
    overlay.setAttribute('aria-hidden', 'false')
    this._bind()
    PresentationView._requestFullscreen(overlay)
  }

  /** Hide the overlay, release the screen, and forget the slide. */

  close() {
    if (!this._open)
      return
    this._open = false
    this._unbind()
    const overlay = this.app.els.presentation
    overlay.classList.add('hidden')
    overlay.setAttribute('aria-hidden', 'true')
    this.app.els.presentationStage.replaceChildren()
    this.app.els.presentationCounter.classList.add('presentation-counter-dim')
    clearTimeout(this._counterTimer)
    PresentationView._releaseFullscreen()
  }

  /** Paint the slide at *index* and flash the progress counter. */

  render(pages, index) {
    const counter = this.app.els.presentationCounter
    this.app.els.presentationStage.innerHTML = pages[index] || ''
    counter.textContent = `${index + SINGLE_ITEM} / ${pages.length}`
    counter.classList.remove('presentation-counter-dim')
    clearTimeout(this._counterTimer)
    this._counterTimer = setTimeout(
      () => counter.classList.add('presentation-counter-dim'),
      PRESENTATION_COUNTER_MS,
    )
  }

  /** Map a key to a presentation action, if it is one. */

  _key(ev) {
    const action = PRESENTATION_KEYS.get(ev.key)
    if (!action)
      return

    // Escape also leaves full-screen; the browser owns that, so do not block it.
    if (action !== 'exit')
      ev.preventDefault()
    this._action(action)
  }

  /** Right-click goes back a slide, mirroring Typst's presentation mode. */

  _context(ev) {
    ev.preventDefault()
    this._action('prev')
  }

  /** Leaving full-screen (Escape) also leaves presentation mode. */

  _fullscreenChange() {
    if (this._open && !document.fullscreenElement)
      this._action('exit')
  }

  /** Dispatch unless the overlay has already been closed. */

  _action(action) {
    if (this._open)
      this._dispatch(action)
  }

  /** Attach the listeners that are only live while the overlay is up. */

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
