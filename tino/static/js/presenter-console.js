import {
  PRESENTATION_KEYS, PRESENTATION_TICK_MS, SINGLE_ITEM,
} from './constants.js'

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
  }

  /** Whether the console is currently on screen. */

  get active() {
    return this._open
  }

  /** Show the console and start its clock. */

  open() {
    this._open = true
    this.app.els.presenter.classList.remove('hidden')
    this.app.els.presenter.setAttribute('aria-hidden', 'false')
    this.resetTimer()
    this._clockTimer = setInterval(() => this._tick(), PRESENTATION_TICK_MS)
  }

  /** Hide the console and stop its clock. */

  close() {
    if (!this._open)
      return
    this._open = false
    this.app.els.presenter.classList.add('hidden')
    this.app.els.presenter.setAttribute('aria-hidden', 'true')
    clearInterval(this._clockTimer)
    this._clockTimer = null
  }

  /** Wire the console's buttons and keys to the presentation actions. */

  bind(dispatch) {
    this._dispatch = dispatch
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

  /** Paint the current slide, the next slide, the counter and the progress. */

  render(pages, index) {
    const position = index + SINGLE_ITEM
    PresenterConsole._paint(this.app.els.presenterStage, pages[index])
    PresenterConsole._paint(this.app.els.presenterNext, pages[position])
    this.app.els.presenterCounter.textContent = `${position} / ${pages.length}`
    this.app.els.presenterProgress.style.width =
      `${position * 100 / pages.length}%`
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
