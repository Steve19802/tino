import { createSurface, renderInk } from './presentation-ink.js'
import { PRESENTATION_INK_COLOURS } from './constants.js'

/** Ink colour the pen starts with: the first of the offered palette. */

const [DEFAULT_INK] = PRESENTATION_INK_COLOURS

/** Milliseconds between coalesced tool updates, so a drag cannot flood the channel. */

const EMIT_MS = 80

/**
 * The presenter's pointer: the laser dot, the pen, and the lights.
 *
 * One instance drives whichever surface is on screen — the tab's full-screen
 * view, or the presenter console's slide. A point is a fraction of the slide
 * (``col`` across, ``row`` down), so what the presenter points at is what the
 * audience window draws, whatever size either surface happens to be.
 *
 * The pen's strokes are kept per slide, so annotations stay put as the deck
 * moves on. The owner hears about every change, which is how the audience
 * window is told what to draw.
 */

export class PresentationTools {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this.active = false
    this.blank = false
    this.colour = DEFAULT_INK
    this.tool = 'none'
    this._at = null
    this._drawing = null
    this._onChange = null
    this._page = 0
    this._strokes = new Map()
  }

  /** Register the callback told about every change. */

  bind(onChange) {
    this._onChange = onChange
  }

  /** Lay the ink layer over *stage*; returns the element slides are drawn in. */

  attach(stage) {
    this.detach()
    this._stage = stage
    const surface = createSurface()
    this._slide = surface.slide
    this._layer = surface.layer
    stage.replaceChildren(this._slide, this._layer)
    this._listen(stage)
    this.active = true
    return this._slide
  }

  /** Take the ink layer away and stop responding. */

  detach() {
    if (!this.active)
      return
    this.active = false
    this._drawing = null
    this._unlisten()
    clearTimeout(this._timer)
    this._layer.remove()
    this._layer = null
  }

  /** Select the pointer tool. */

  setTool(tool) {
    this.tool = tool
    this._drawing = null
    this._change()
  }

  /** Select the ink colour. */

  setColour(colour) {
    this.colour = colour
    this._change()
  }

  /** Blank the audience, or bring the slide back. */

  toggleBlank() {
    this.blank = !this.blank
    this._change()
  }

  /** Clear the drawings, on this slide or on every one. */

  clear(all) {
    if (all)
      this._strokes.clear()
    else
      this._strokes.delete(this._page)
    this._change()
  }

  /** Follow the deck to the slide at *index*. */

  page(index) {
    this._page = index
    this._at = null
    this._render()
  }

  /** The tool state the audience window needs to draw the same picture. */

  state() {
    return {
      blank: this.blank,
      colour: this.colour,
      laser: this.tool === 'laser' ? this._at : null,
      strokes: this._pageStrokes(),
      tool: this.tool,
    }
  }

  /** Listen for the pointer on *stage*, and for the tool keys anywhere. */

  _listen(stage) {
    this._timer = null
    this._at = null
    this._handlers = {
      down: ev => this._down(ev),
      key: ev => this._key(ev),
      leave: () => this._leave(),
      move: ev => this._move(ev),
      up: ev => this._up(ev),
    }
    stage.addEventListener('pointerdown', this._handlers.down)
    stage.addEventListener('pointermove', this._handlers.move)
    stage.addEventListener('pointerup', this._handlers.up)
    stage.addEventListener('pointerleave', this._handlers.leave)
    document.addEventListener('keydown', this._handlers.key)
  }

  /** Stop listening; the stage outlives the ink layer. */

  _unlisten() {
    const { down, key, leave, move, up } = this._handlers
    this._stage.removeEventListener('pointerdown', down)
    this._stage.removeEventListener('pointermove', move)
    this._stage.removeEventListener('pointerup', up)
    this._stage.removeEventListener('pointerleave', leave)
    document.removeEventListener('keydown', key)
  }

  /** Start a pen stroke. */

  _down(ev) {
    if (!this.active || this.tool !== 'pen' || ev.button !== 0)
      return
    ev.preventDefault()
    this._stage.setPointerCapture(ev.pointerId)
    this._drawing = { colour: this.colour, points: [this._point(ev)] }
    this._pageStrokes().push(this._drawing)
    this._render()
  }

  /** Extend the stroke being drawn, or move the laser. */

  _move(ev) {
    if (!this.active || this.tool === 'none')
      return
    this._at = this._point(ev)
    if (this._drawing)
      this._drawing.points.push(this._at)
    this._render()
    this._emit()
  }

  /** Finish the stroke, keeping what was drawn. */

  _up() {
    if (!this._drawing)
      return
    this._drawing = null
    this._render()
    this._emit(true)
  }

  /** Hide the laser when the pointer leaves the slide. */

  _leave() {
    if (!this.active)
      return
    this._at = null
    this._render()
    this._emit(true)
  }

  /** The pointer's position as a fraction of the slide, on both axes. */

  _point(ev) {
    const box = this._stage.getBoundingClientRect()
    return {
      col: (ev.clientX - box.left) / box.width,
      row: (ev.clientY - box.top) / box.height,
    }
  }

  /** Toggle a tool from the keyboard: L for the laser, Shift+L for the pen. */

  _key(ev) {
    if (!this.active)
      return
    if (ev.key === 'l')
      this._toggle('laser')
    else if (ev.key === 'L')
      this._toggle('pen')
    else if (ev.key === 'b' || ev.key === 'B')
      this.toggleBlank()
  }

  /** Turn *tool* on, or off when it is already the active one. */

  _toggle(tool) {
    this.setTool(this.tool === tool ? 'none' : tool)
  }

  /** The strokes drawn on the current slide. */

  _pageStrokes() {
    if (!this._strokes.has(this._page))
      this._strokes.set(this._page, [])
    return this._strokes.get(this._page)
  }

  /** Repaint, then tell the owner. */

  _change() {
    this._render()
    this._emit(true)
  }

  /**
   * Tell the owner the state. A deliberate change goes at once; a drag is
   * coalesced into one update per *_EMIT_MS*, and because the send reads the
   * state when it fires, the latest pointer position always goes out.
   */

  _emit(force) {
    if (force) {
      this._force()
      return
    }
    if (this._timer)
      return
    this._timer = setTimeout(() => this._flush(), EMIT_MS)
  }

  /** Send now, cancelling any pending coalesced update. */

  _force() {
    clearTimeout(this._timer)
    this._flush()
  }

  /** Hand the current state to the owner. */

  _flush() {
    this._timer = null
    if (this._onChange)
      this._onChange(this.state())
  }

  /** Repaint the ink layer and place the laser dot. */

  _render() {
    if (!this._layer)
      return
    renderInk(this._layer, this._pageStrokes(), this._laserPoint())
  }

  /** The laser's position, or null when the laser is not the active tool. */

  _laserPoint() {
    return this.tool === 'laser' ? this._at : null
  }

}
