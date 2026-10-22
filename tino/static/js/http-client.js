import { HTTP_NO_CONTENT, HTTP_UNAUTHORIZED } from './constants.js'

/**
 * Low-level HTTP transport for the REST API client.
 * Handles auth redirects, error parsing, and JSON-body requests.
 */

export class HttpClient {

  /** @param {string} [baseUrl] - Base URL of the backend. */

  constructor(baseUrl) {
    this.baseUrl = baseUrl || ''
  }

  /**
   * Internal fetch wrapper. Throws on non-OK responses,
   * returns parsed JSON or null for 204 No Content.
   */

  async _fetch(path, options) {
    const res = await fetch(this.baseUrl + path, options)
    if (res.status === HTTP_UNAUTHORIZED) {
      window.location.href = '/login'
      throw new Error('Session expired')
    }
    if (!res.ok)
      throw await HttpClient._error(res)
    if (res.status === HTTP_NO_CONTENT)
      return null
    return res.json()
  }

  /**
   * Build an Error from a failed response. A structured ``detail`` object
   * (e.g. the compile endpoints' ``{message, diagnostics}``) becomes the
   * message plus a ``diagnostics`` array; anything else becomes the message.
   */

  static async _error(res) {
    const body = await res.text()
    let detail = body
    try {
      detail = JSON.parse(body).detail || body
    }
    catch {
      // Not JSON — keep the raw body.
    }
    if (detail && typeof detail === 'object') {
      const err = new Error(detail.message || body)
      err.diagnostics = detail.diagnostics || []
      return err
    }
    return new Error(detail)
  }

  /** Send a JSON-body request (POST/PUT). */

  _json(method, path, data) {
    return this._fetch(path, {
      body: JSON.stringify(data),
      headers: { 'Content-Type': 'application/json' },
      method,
    })
  }

}
