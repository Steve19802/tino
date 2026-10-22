import {
  PRESENTATION_CHANNEL, PRESENTATION_PAGE, PRESENTATION_WINDOW,
  PRESENTATION_WINDOW_FEATURES, SINGLE_ITEM,
} from './constants.js'

/**
 * The presenter's link to the audience window.
 *
 * Opens the audience window, keeps a BroadcastChannel to it, and keeps it in
 * step with the deck. A sync message carries the deck's identity, a revision
 * that changes whenever the pages change, and the current slide; the audience
 * refetches the pages on a new revision, so a recompile mid-talk reaches the
 * projector. The audience can send actions back — clicking its slide advances
 * it — and tells us when it is closed.
 */

export class PresenterWindow {

  /** @param {TinoApp} app - Main application instance. */

  constructor(app) {
    this.app = app
    this._open = false
    this._window = null
    this._channel = null
    this._pages = null
    this._revision = 0
    this._index = 0
    this._onAction = null
    this._onClosed = null
  }

  /** Whether the audience window is open. */

  get active() {
    return this._open
  }

  /** Register the callbacks for audience actions and for a closed window. */

  bind(onAction, onClosed) {
    this._onAction = onAction
    this._onClosed = onClosed
  }

  /**
   * Open the audience window and start listening to it. Must run inside the
   * click that starts presenting, or the browser will refuse the pop-up.
   */

  open() {
    this._window = window.open(
      PRESENTATION_PAGE, PRESENTATION_WINDOW, PRESENTATION_WINDOW_FEATURES,
    )
    if (!this._window)
      return false
    this._open = true
    this._pages = null
    this._revision = 0
    this._channel = new BroadcastChannel(PRESENTATION_CHANNEL)
    this._channel.addEventListener('message', ev => this._receive(ev.data))
    return true
  }

  /** Close the audience window and drop the channel. */

  close() {
    if (!this._open)
      return
    this._open = false
    if (this._channel) {
      this._channel.close()
      this._channel = null
    }
    if (this._window) {
      this._window.close()
      this._window = null
    }
  }

  /** Tell the audience which deck and slide to show. */

  sync(pages, index) {
    if (!this._open)
      return
    this._index = index
    if (pages !== this._pages) {
      this._pages = pages
      this._revision += SINGLE_ITEM
    }
    this._post()
  }

  /** Send the current deck identity, revision and slide to the audience. */

  _post() {
    this._channel.postMessage({
      bucket: this.app.bucket,
      index: this._index,
      revision: this._revision,
      target: this.app.preview.target,
      total: this._pages.length,
      type: 'sync',
    })
  }

  /** Handle a message from the audience window. */

  _receive(data) {
    if (!this._open || !data)
      return
    if (data.type === 'hello')
      this._post()
    else if (data.type === 'action' && this._onAction)
      this._onAction(data.action)
    else if (data.type === 'bye')
      this._closeFromAudience()
  }

  /** Tear down when the audience window closes itself. */

  _closeFromAudience() {
    this.close()
    if (this._onClosed)
      this._onClosed()
  }

}
