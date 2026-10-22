/** Width of the pen's line, as a fraction of the slide's width. */

const INK_WIDTH = 0.004

/** Device pixel ratio assumed when the browser does not report one. */

const DEFAULT_PIXEL_RATIO = 1

/**
 * The ink layer: a canvas for the pen, with a dot for the laser on top.
 *
 * A stroke is ``{colour, points}`` and every point is a ``{col, row}`` fraction
 * of the slide rather than a pixel. That is what lets the same drawing land in
 * the same place on every surface — the presenter's slide and the audience
 * window alike — whatever size each of them happens to be.
 */

/** Trace one stroke onto *context*, scaling its fractional points up. */

const trace = (context, stroke) => {
  const width = context.canvas.clientWidth
  const height = context.canvas.clientHeight
  context.strokeStyle = stroke.colour
  context.beginPath()
  stroke.points.forEach(point =>
    context.lineTo(point.col * width, point.row * height))
  context.stroke()
}

/** Draw every stroke of a slide onto *canvas*. */

const paint = (canvas, strokes) => {
  const context = canvas.getContext('2d')
  const ratio = window.devicePixelRatio || DEFAULT_PIXEL_RATIO
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, canvas.width, canvas.height)
  context.lineCap = 'round'
  context.lineJoin = 'round'
  context.lineWidth = canvas.clientWidth * INK_WIDTH
  strokes.forEach(stroke => trace(context, stroke))
}

/** Match a canvas' backing store to its displayed size, in device pixels. */

const fit = canvas => {
  const ratio = window.devicePixelRatio || DEFAULT_PIXEL_RATIO
  const width = Math.round(canvas.clientWidth * ratio)
  const height = Math.round(canvas.clientHeight * ratio)
  if (canvas.width === width && canvas.height === height)
    return
  canvas.width = width
  canvas.height = height
}

/** Put the laser dot at *point*, or hide it when there is none. */

const place = (element, point) => {
  element.classList.toggle('hidden', !point)
  if (!point)
    return
  element.style.left = `${point.col * 100}%`
  element.style.top = `${point.row * 100}%`
}

/** Build an ink layer; its laser dot stays hidden until it is given a place. */

export const createInkLayer = () => {
  const layer = document.createElement('div')
  layer.className = 'presentation-ink'
  const canvas = document.createElement('canvas')
  canvas.className = 'presentation-ink-canvas'
  const laser = document.createElement('div')
  laser.className = 'presentation-ink-laser hidden'
  layer.append(canvas, laser)
  return layer
}

/** Repaint *layer* with *strokes* and put the laser dot at *laser*. */

export const renderInk = (layer, strokes, laser) => {
  const canvas = layer.firstElementChild
  fit(canvas)
  paint(canvas, strokes)
  place(layer.lastElementChild, laser)
}

/**
 * Build a slide's own element plus the ink layer that overlays it.
 *
 * A slide is drawn into its own element, not into the panel around it, so the
 * ink layer can sit beside it and survive every slide change.
 */

export const createSurface = () => {
  const slide = document.createElement('div')
  slide.className = 'presentation-slide'
  const layer = createInkLayer()
  return { layer, slide }
}
