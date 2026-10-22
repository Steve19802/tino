import {
  PRESENTATION_KEYS, PRESENTATION_TICK_MS, SINGLE_ITEM,
} from './constants.js'
import { PresentationTools } from './presentation-tools.js'
import { PresenterToolbar } from './presenter-toolbar.js'

/** Milliseconds in one second. */

const MILLISECONDS = 1000

/** Seconds in one minute. */

const SECONDS_PER_MINUTE = 60

/** Digits used when padding the timer's minutes and seconds. */

const PAD_WIDTH = 2

/**
 * The presenter console, shown in the app's own window.
 *
 * On a second display the audience sees only the current slide; here the
 * presenter sees that slide large, the slide coming up, the wall clock, how
 * long the talk has been running, and how far through the deck they are.
 */

export class PresenterConsole {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this._open = false
    this._startedAt = 0
    this._clockTimer = null
    this._dispatch = null
    this._index = 0
    this._notes = null
    this._pages = null
    this._tools = new PresentationTools(app)
    this._toolbar = new PresenterToolbar(app)
  }

  /** Whether the console is currently on screen. */

  get active() {
    return this._open
  }

  /** Show the console, start its clock, and load the deck's speaker notes. */

  open() {
    this._open = true
    this._notes = null
    this._pages = null
    clearInterval(this._clockTimer)
    this.app.els.presenter.classList.remove('hidden')
    this.app.els.presenter.setAttribute('aria-hidden', 'false')
    this._slide = this._tools.attach(this.app.els.presenterStage)
    this.resetTimer()
    this._clockTimer = setInterval(() => this._tick(), PRESENTATION_TICK_MS)
  }

  /** Hide the console and stop its clock. */

  close() {
    if (!this._open)
      return
    this._open = false
    this._tools.detach()
    this.app.els.presenter.classList.add('hidden')
    this.app.els.presenter.setAttribute('aria-hidden', 'true')
    clearInterval(this._clockTimer)
    this._clockTimer = null
  }

  /** Wire the console's buttons and keys, and the pointer controls. */

  bind(dispatch, onTools) {
    this._dispatch = dispatch
    this._onTools = onTools
    this._toolbar.bind(this._tools, onTools)
    document.getElementById('btn-presenter-prev')
      .addEventListener('click', () => this._act('prev'))
    document.getElementById('btn-presenter-next')
      .addEventListener('click', () => this._act('next'))
    document.getElementById('btn-presenter-exit')
      .addEventListener('click', () => this._act('exit'))
    document.getElementById('btn-presenter-reset')
      .addEventListener('click', () => this.resetTimer())
    document.addEventListener('keydown', ev => this._key(ev))
  }

  /** Paint the console: the slides, the progress, and the current slide's note. */

  render(pages, index) {
    this._index = index
    this._paintSlides(pages, index)
    this._syncNotes(pages)
    this._showNote()
    this._tools.page(index)
    if (this._onTools)
      this._onTools(this._tools.state())
  }

  /** Paint the current slide, the next slide, the counter and the progress. */

  _paintSlides(pages, index) {
    const position = index + SINGLE_ITEM
    PresenterConsole._paint(this._slide, pages[index])
    PresenterConsole._paint(this.app.els.presenterNext, pages[index + SINGLE_ITEM])
    this.app.els.presenterCounter.textContent = `${position} / ${pages.length}`
    this.app.els.presenterProgress.style.width =
      `${position * 100 / pages.length}%`
  }

  /** Fetch the deck's speaker notes when the deck itself changes. */

  _syncNotes(pages) {
    if (pages === this._pages)
      return
    this._pages = pages
    this._loadNotes()
  }

  /** Read the speaker notes for the deck the preview is showing. */

  async _loadNotes() {
    const notes = await PresenterConsole._fetchNotes(this.app)
    this._notes = notes
    this._showNote()
  }

  /** The notes endpoint's contents, or an empty list when it cannot be read. */

  static async _fetchNotes(app) {
    try {
      const body = await app.api.notes(app.bucket, app.preview.target)
      return body.notes
    }
    catch {
      return []
    }
  }

  /** Show the note for the current slide, or a hint when there is none. */

  _showNote() {
    const element = this.app.els.presenterNote
    const note = this._notes ? this._notes[this._index] : null
    element.textContent = note || PresenterConsole._noNote(this._notes)
    element.classList.toggle('presenter-note-muted', !note)
  }

  /** What the notes pane says when there is no note to show. */

  static _noNote(notes) {
    if (!notes)
      return 'Loading speaker notes…'
    if (notes.every(note => !note))
      return 'No speaker notes for this deck.'
    return 'No note for this slide.'
  }

  /** Restart the elapsed timer from zero. */

  resetTimer() {
    this._startedAt = Date.now()
    this._tick()
  }

  /** Update the wall clock and the elapsed timer. */

  _tick() {
    if (!this._open)
      return
    this.app.els.presenterClock.textContent = new Date().toLocaleTimeString()
    this.app.els.presenterTimer.textContent =
      PresenterConsole._elapsed(this._startedAt)
  }

  /** Handle a key while the console is up. */

  _key(ev) {
    if (!this._open)
      return
    const action = PRESENTATION_KEYS.get(ev.key)
    if (!action)
      return

    // Escape also closes the audience window, so let the default through.
    if (action !== 'exit')
      ev.preventDefault()
    this._act(action)
  }

  /** Dispatch unless the console has been closed. */

  _act(action) {
    if (this._open)
      this._dispatch(action)
  }

  /** Put *svg* into *el*, leaving it empty when there is no next slide. */

  static _paint(el, svg) {
    el.innerHTML = svg || ''
  }

  /** The time since *startedAt*, as ``MM:SS``. */

  static _elapsed(startedAt) {
    const total = Math.floor((Date.now() - startedAt) / MILLISECONDS)
    const minutes = Math.floor(total / SECONDS_PER_MINUTE)
    const seconds = total % SECONDS_PER_MINUTE
    return `${PresenterConsole._pad(minutes)}:${PresenterConsole._pad(seconds)}`
  }

  /** Zero-pad a timer component. */

  static _pad(value) {
    return String(value).padStart(PAD_WIDTH, '0')
  }

}
