import { PRESENTATION_CHANNEL, PRESENTATION_KEYS } from './constants.js'
import { PresentationGeometry } from './presentation-geometry.js'

/**
 * The audience window: the slide-only display meant for a second screen.
 *
 * Opened by the presenter console, it listens on the presentation channel for
 * the deck's identity, its revision, and the current slide. It refetches the
 * pages whenever the revision changes, so a recompile mid-talk reaches the
 * projector, and it forwards any navigation performed here to the console.
 */

export class PresentationAudience {

  constructor() {
    this._channel = new BroadcastChannel(PRESENTATION_CHANNEL)
    this._pages = null
    this._revision = null
    this._index = 0
    this._channel.addEventListener('message', ev => this._receive(ev.data))
    window.addEventListener('beforeunload', () => this._send('bye'))
  }

  /** Wire the local controls and tell the presenter that we are ready. */

  init() {
    document.getElementById('btn-audience-fullscreen')
      .addEventListener('click', () => PresentationAudience._fullscreen())
    const stage = document.getElementById('present-audience-stage')
    stage.addEventListener('click', () => this._send('action', 'next'))
    stage.addEventListener('contextmenu', ev => this._context(ev))
    document.addEventListener('keydown', ev => this._key(ev))
    this._send('hello')
  }

  /** Apply a message from the presenter console. */

  _receive(data) {
    if (!data || data.type !== 'sync')
      return
    this._index = data.index
    if (data.revision === this._revision)
      this._show()
    else
      this._load(data)
  }

  /** Fetch the deck's pages for the announced revision, then show them. */

  async _load(deck) {
    PresentationAudience._status('Loading the deck…')
    try {
      const response = await fetch(PresentationAudience._url(deck), {
        credentials: 'same-origin',
      })
      const body = await response.json()
      this._pages = body.pages
      this._revision = deck.revision
      PresentationAudience._status('')
      this._show()
    }
    catch {
      PresentationAudience._status('Could not load the deck.')
    }
  }

  /** Show the current slide, sized to the deck's aspect ratio. */

  _show() {
    if (!this._pages)
      return
    const ratio = PresentationGeometry.pageRatio(this._pages[0])
    if (ratio)
      PresentationAudience._size(ratio)
    document.getElementById('present-audience-stage').innerHTML =
      this._pages[this._index] || ''
  }

  /** Handle a key here, forwarding its action to the presenter. */

  _key(ev) {
    const action = PRESENTATION_KEYS.get(ev.key)
    if (!action)
      return
    ev.preventDefault()
    this._send('action', action)
  }

  /** Right-click goes back a slide, mirroring Typst's presentation mode. */

  _context(ev) {
    ev.preventDefault()
    this._send('action', 'prev')
  }

  /** Toggle full-screen here; it needs a click in this window to be allowed. */

  static _fullscreen() {
    if (document.fullscreenElement)
      PresentationAudience._ignore(document.exitFullscreen())
    else
      PresentationAudience._ignore(document.documentElement.requestFullscreen())
  }

  /** Show the status line, or hide it when *text* is empty. */

  static _status(text) {
    const status = document.getElementById('present-audience-status')
    status.textContent = text
    status.classList.toggle('hidden', !text)
  }

  /** Post a message to the presenter console. */

  _send(type, action) {
    this._channel.postMessage(action ? { action, type } : { type })
  }

  /** The compile URL for the deck the console announced. */

  static _url(deck) {
    const slug = encodeURIComponent(deck.bucket)
    return `/api/buckets/${slug}/compile/svg/${deck.target}`
  }

  /** Size the slide to *ratio* so it fills the window. */

  static _size(ratio) {
    document.documentElement
      .style.setProperty('--presentation-ratio', String(ratio))
  }

  /** Swallow a rejected promise: a full-screen refusal is not an error here. */

  static _ignore(promise) {
    promise.catch(() => {
      // A refusal (no transient activation, or a sandboxed frame) is harmless.
    })
  }

}

document.addEventListener('DOMContentLoaded', () => {
  const audience = new PresentationAudience()
  audience.init()
})
