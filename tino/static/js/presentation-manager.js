import { PresentationGeometry } from './presentation-geometry.js'
import { PresentationView } from './presentation-view.js'
import { PresenterConsole } from './presenter-console.js'
import { PresenterWindow } from './presenter-window.js'
import { SINGLE_ITEM } from './constants.js'

/**
 * Presentation mode: the deck state, its navigation, and the ways to show it.
 *
 * The pages are the ones the preview already compiled — nothing is rendered
 * here. A deck can be shown full screen in the app's own tab, or through the
 * presenter console, which drives a separate audience window on a second display
 * while showing the presenter the next slide, the clock and the elapsed timer.
 * The page list stays in sync with the preview, so a recompile while presenting
 * updates the deck in place without losing the current slide.
 */

export class PresentationManager {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this.pages = []
    this.index = 0
    this.ratio = PresentationGeometry.fallbackRatio()
    this.view = new PresentationView(app)
    this.console = new PresenterConsole(app)
    this.audience = new PresenterWindow(app)
  }

  /** Whether a deck is being presented, in either mode. */

  get active() {
    return this.view.active || this.audience.active
  }

  /** Bind the Present control, the console, and the audience window. */

  bind() {
    document.getElementById('btn-present')
      .addEventListener('click', () => this.start())
    document.getElementById('btn-present-arrow')
      .addEventListener('click', ev => PresentationManager._toggleMenu(ev))
    document.getElementById('present-menu')
      .addEventListener('click', ev => this._menuClick(ev))
    document.addEventListener('click', () => PresentationManager._closeMenu())
    document.addEventListener('keydown', ev => PresentationManager._escape(ev))
    this.console.bind(action => this.dispatch(action))
    this.audience.bind(
      action => this.dispatch(action),
      () => this._audienceClosed(),
    )
  }

  /** Present the deck full screen in this tab. */

  start() {
    if (this.active)
      return
    this.view.open(action => this.dispatch(action))
    this._load()
  }

  /**
   * Present through the audience window: open it, show the console here, and let
   * the two keep each other in step.
   */

  startPresenter() {
    if (this.active)
      return
    if (!this.audience.open()) {
      this.app.toast.error('Allow pop-ups to open the presenter view.')
      return
    }
    this.console.open()
    this._load()
  }

  /** Leave presentation mode and close whatever was showing the deck. */

  exit() {
    if (!this.active)
      return
    this.audience.close()
    this.console.close()
    this.view.close()
  }

  /** Perform a presentation action, from a view or from the audience. */

  dispatch(action) {
    if (action === 'exit') {
      this.exit()
      return
    }
    if (action === 'next') {
      this._step(SINGLE_ITEM)
      return
    }
    if (action === 'prev') {
      this._step(-SINGLE_ITEM)
      return
    }
    this._jump(action)
  }

  /**
   * Adopt a fresh compile from the preview, so the deck tracks saves while it is
   * on screen without losing the current slide. The Present control follows the
   * render even when nothing is being presented.
   */

  onPages(render) {
    const presentable = PresentationGeometry.canPresent(render && render.pages)
    document.getElementById('present-group').classList.toggle('hidden', !presentable)
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

  /** Move the given number of slides from the current one. */

  _step(delta) {
    this._show(this.index + delta)
  }

  /** Jump to the first or last slide. */

  _jump(action) {
    if (action === 'first')
      this._show(0)
    else if (action === 'last')
      this._show(this.pages.length - SINGLE_ITEM)
  }

  /** Clamp *index* and repaint every surface showing the deck. */

  _show(index) {
    if (!this.pages.length)
      return
    this.index = Math.min(Math.max(index, 0), this.pages.length - SINGLE_ITEM)
    this._paint()
  }

  /** Repaint the console and the audience, or the tab's own full-screen view. */

  _paint() {
    if (this.audience.active) {
      this.console.render(this.pages, this.index)
      this.audience.sync(this.pages, this.index)
      return
    }
    this.view.render(this.pages, this.index)
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

  /** Measure the deck, size the slides, and paint at the current index. */

  _reflow() {
    const ratio = PresentationGeometry.pageRatio(this.pages[0])
    if (ratio)
      this.ratio = ratio
    document.documentElement
      .style.setProperty('--presentation-ratio', String(this.ratio))
    this._paint()
  }

  /** A closed audience window leaves the console with nothing to drive. */

  _audienceClosed() {
    this.app.toast.info('The audience window was closed.')
    this.exit()
  }

  /** Run the Present menu entry the user picked. */

  _menuClick(ev) {
    const item = ev.target.closest('.present-item')
    if (!item)
      return
    PresentationManager._closeMenu()
    if (item.dataset.present === 'presenter')
      this.startPresenter()
    else
      this.start()
  }

  /** Open or close the Present menu. */

  static _toggleMenu(ev) {
    ev.stopPropagation()
    const menu = document.getElementById('present-menu')
    const open = menu.classList.contains('hidden')
    menu.classList.toggle('hidden', !open)
    document.getElementById('btn-present-arrow')
      .setAttribute('aria-expanded', String(open))
  }

  /** Close the Present menu. */

  static _closeMenu() {
    const menu = document.getElementById('present-menu')
    if (menu.classList.contains('hidden'))
      return
    menu.classList.add('hidden')
    document.getElementById('btn-present-arrow')
      .setAttribute('aria-expanded', 'false')
  }

  /** Escape closes the Present menu, as it does the export menu. */

  static _escape(ev) {
    if (ev.key === 'Escape')
      PresentationManager._closeMenu()
  }

}
