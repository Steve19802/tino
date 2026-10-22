import {
  PRESENTATION_RATIOS, PRESENTATION_RATIO_TOLERANCE, SINGLE_ITEM,
} from './constants.js'

/**
 * Page-measurement helpers for presentation mode.
 *
 * A compiled page is a self-contained SVG document whose root carries the page
 * size, as a ``viewBox`` or as ``width``/``height`` attributes. These helpers
 * read that size so the presentation overlay can fit a slide to the screen, and
 * decide whether a document looks like a slide deck at all.
 */

/** Number of numbers in an SVG ``viewBox`` (min-x, min-y, width, height). */

const VIEWBOX_PARTS = 4

export class PresentationGeometry {

  /**
   * Whether *pages* forms a deck worth presenting: any multi-page document
   * qualifies, a single page only when it has a slide aspect ratio.
   */

  static canPresent(pages) {
    if (!pages || !pages.length)
      return false
    if (pages.length > SINGLE_ITEM)
      return true
    return PresentationGeometry.isSlideRatio(
      PresentationGeometry.pageRatio(pages[0]),
    )
  }

  /** The page's aspect ratio (width / height), or null when unreadable. */

  static pageRatio(svg) {
    if (!svg)
      return null
    const tag = /<svg\b[^>]*>/u.exec(svg)
    if (!tag)
      return null
    const box = /viewBox="(?<box>[^"]+)"/u.exec(tag[0])
    if (box)
      return PresentationGeometry._viewBoxRatio(box.groups.box)
    return PresentationGeometry._sizeRatio(tag[0])
  }

  /** Whether *ratio* matches one of the known slide aspect ratios. */

  static isSlideRatio(ratio) {
    if (!ratio)
      return false
    return PRESENTATION_RATIOS.some(item =>
      Math.abs(ratio - item.width / item.height) <= PRESENTATION_RATIO_TOLERANCE)
  }

  /** Ratio used before a slide is measured: the widescreen default. */

  static fallbackRatio() {
    const [wide] = PRESENTATION_RATIOS
    return wide.width / wide.height
  }

  /** Parse ``viewBox="min-x min-y width height"`` into a ratio. */

  static _viewBoxRatio(box) {
    const parts = box.trim().split(/[\s,]+/u)
    if (parts.length !== VIEWBOX_PARTS)
      return null
    return PresentationGeometry._saneRatio(
      Number(parts[2]) / Number(parts[3]),
    )
  }

  /** Fall back to the SVG root's ``width``/``height`` attributes. */

  static _sizeRatio(tag) {
    const width = /\bwidth="(?<n>[\d.]+)/u.exec(tag)
    const height = /\bheight="(?<n>[\d.]+)/u.exec(tag)
    if (!width || !height)
      return null
    return PresentationGeometry._saneRatio(
      Number(width.groups.n) / Number(height.groups.n),
    )
  }

  /** Keep a ratio only when it is a positive, finite number. */

  static _saneRatio(value) {
    if (Number.isFinite(value) && value > 0)
      return value
    return null
  }

}
