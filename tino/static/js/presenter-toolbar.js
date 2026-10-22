import { PRESENTATION_INK_COLOURS } from './constants.js'

/** Pointer tool → the icon shown on its menu button. */

const TOOL_ICONS = {
  laser: 'flare',
  none: 'mouse',
  pen: 'draw',
}

/**
 * The presenter console's pointer controls.
 *
 * Owns the pointer menu, the ink swatches and the lights button, and keeps them
 * in step with a ``PresentationTools`` instance. Every change is passed on to
 * the console, which forwards it to the audience window.
 */

export class PresenterToolbar {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this._tools = null
    this._onChange = null
  }

  /** Wire the controls to *tools*, reporting every change through *onChange*. */

  bind(tools, onChange) {
    this._tools = tools
    this._onChange = onChange
    tools.bind(state => this._changed(state))
    document.getElementById('btn-presenter-pointer')
      .addEventListener('click', ev => PresenterToolbar._toggle(ev))
    document.getElementById('presenter-pointer-menu')
      .addEventListener('click', ev => this._pick(ev))
    document.getElementById('presenter-swatches')
      .addEventListener('click', ev => this._swatch(ev))
    document.getElementById('btn-presenter-lights')
      .addEventListener('click', () => tools.toggleBlank())
    document.addEventListener('click', () => PresenterToolbar._close())
    PresenterToolbar._swatches()
    PresenterToolbar._show(tools.state())
  }

  /** Build the ink colour swatches from the shared palette. */

  static _swatches() {
    const container = document.getElementById('presenter-swatches')
    PRESENTATION_INK_COLOURS.forEach(colour => {
      const swatch = document.createElement('button')
      swatch.className = 'presenter-swatch'
      swatch.dataset.colour = colour
      swatch.style.background = colour
      swatch.title = colour
      container.append(swatch)
    })
  }

  /** Sync the controls with *state*, then pass it on. */

  _changed(state) {
    PresenterToolbar._show(state)
    if (this._onChange)
      this._onChange(state)
  }

  /** Reflect the tool state in the controls. */

  static _show(state) {
    document.getElementById('presenter-pointer-icon').textContent =
      TOOL_ICONS[state.tool]
    document.getElementById('presenter-swatches')
      .classList.toggle('hidden', state.tool !== 'pen')
    document.getElementById('btn-presenter-lights')
      .classList.toggle('active', state.blank)
    document.getElementById('presenter')
      .classList.toggle('presenter-lights-off', state.blank)
    PresenterToolbar._mark(state.colour)
  }

  /** Highlight the swatch for the active ink colour. */

  static _mark(colour) {
    document.querySelectorAll('.presenter-swatch').forEach(swatch =>
      swatch.classList.toggle('active', swatch.dataset.colour === colour))
  }

  /** Run the pointer-menu entry the user picked. */

  _pick(ev) {
    const item = ev.target.closest('.presenter-tool')
    if (!item)
      return
    PresenterToolbar._close()
    const { all, tool } = item.dataset
    if (tool === 'clear')
      this._tools.clear(all === 'true')
    else
      this._tools.setTool(tool)
  }

  /** Select the ink colour of the swatch that was clicked. */

  _swatch(ev) {
    const swatch = ev.target.closest('.presenter-swatch')
    if (!swatch)
      return
    this._tools.setColour(swatch.dataset.colour)
  }

  /** Open or close the pointer menu. */

  static _toggle(ev) {
    ev.stopPropagation()
    const menu = document.getElementById('presenter-pointer-menu')
    const open = menu.classList.contains('hidden')
    menu.classList.toggle('hidden', !open)
    document.getElementById('btn-presenter-pointer')
      .setAttribute('aria-expanded', String(open))
  }

  /** Close the pointer menu. */

  static _close() {
    const menu = document.getElementById('presenter-pointer-menu')
    if (menu.classList.contains('hidden'))
      return
    menu.classList.add('hidden')
    document.getElementById('btn-presenter-pointer')
      .setAttribute('aria-expanded', 'false')
  }

}
