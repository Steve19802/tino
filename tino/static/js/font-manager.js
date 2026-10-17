import { escapeHtml } from './constants.js'

const KB = 1024
const MB = 1048576
const DECIMALS = 1

const EDITOR_ROLES = ['editor', 'committer']

/**
 * Manages the fonts dialog: an instance-wide "Global fonts" section (admin
 * only) and a per-bucket "Bucket fonts" section (visible when the user can
 * edit the active bucket).
 */

export class FontManager {

  /** @param {TinoApp} app */

  constructor(app) {
    this.app = app
    this._dialog = document.getElementById('font-dialog')
    this._bucketSection = document.getElementById('font-bucket-section')
    this._bucketTitle = document.getElementById('font-bucket-title')
    this._bucketList = document.getElementById('bucket-font-list')
    this._bucketInput = document.getElementById('bucket-font-upload-input')
    this._globalSection = document.getElementById('font-global-section')
    this._globalList = document.getElementById('font-list')
    this._globalInput = document.getElementById('font-upload-input')
  }

  bind() {
    document.getElementById('btn-font-close')
      .addEventListener('click', () => this.close())
    this._dialog.addEventListener('click', evt => {
      if (evt.target === this._dialog)
        this.close()
    })
    document.getElementById('btn-font-upload')
      .addEventListener('click', () => this._globalInput.click())
    document.getElementById('btn-bucket-font-upload')
      .addEventListener('click', () => this._bucketInput.click())
    this._globalInput.addEventListener('change', () => this._handleUpload('global'))
    this._bucketInput.addEventListener('change', () => this._handleUpload('bucket'))
    this._globalList.addEventListener('click', evt => this._onListClick(evt, 'global'))
    this._bucketList.addEventListener('click', evt => this._onListClick(evt, 'bucket'))
  }

  async open() {
    this._dialog.classList.add('visible')
    await this._load()
  }

  close() {
    this._dialog.classList.remove('visible')
  }

  async _load() {
    const canEditBucket =
      Boolean(this.app.bucket) && EDITOR_ROLES.includes(this.app.bucketRole)
    const showGlobal = this.app.isAdmin
    this._bucketSection.classList.toggle('hidden', !canEditBucket)
    this._globalSection.classList.toggle('hidden', !showGlobal)

    if (canEditBucket) {
      this._bucketTitle.textContent = `Bucket fonts — ${this.app.bucket}`
      await this._loadList(
        this._bucketList, () => this.app.api.listBucketFonts(this.app.bucket),
      )
    }
    if (showGlobal)
      await this._loadList(this._globalList, () => this.app.api.listFonts())
  }

  async _loadList(listEl, fetchFn) {
    listEl.innerHTML = '<li class="font-empty">Loading…</li>'
    try {
      this._render(listEl, await fetchFn())
    }
    catch (err) {
      listEl.innerHTML = '<li class="font-empty">Failed to load fonts.</li>'
      this.app.toast.error(err.message)
    }
  }

  _render(listEl, fonts) {
    if (!fonts.length) {
      listEl.innerHTML = '<li class="font-empty">No fonts installed.</li>'
      return
    }
    listEl.innerHTML = fonts.map(font =>
      '<li class="font-item">' +
        `<span class="font-name">${escapeHtml(font.filename)}</span>` +
        `<span class="font-size">${FontManager._formatSize(font.size)}</span>` +
        `<button class="icon-btn" data-delete="${escapeHtml(font.filename)}" title="Delete">` +
          '<span class="material-symbols-outlined">delete</span>' +
        '</button>' +
      '</li>',
    ).join('')
  }

  async _handleUpload(scope) {
    const isBucket = scope === 'bucket'
    const input = isBucket ? this._bucketInput : this._globalInput
    const { files } = input
    if (!files.length)
      return
    try {
      if (isBucket)
        await this.app.api.uploadBucketFonts(this.app.bucket, files)
      else
        await this.app.api.uploadFonts(files)
      this.app.toast.success('Fonts uploaded')
      await this._reload(scope)
    }
    catch (err) {
      this.app.toast.error(err.message)
    }
    input.value = ''
  }

  async _onListClick(evt, scope) {
    const btn = evt.target.closest('[data-delete]')
    if (!btn)
      return
    const filename = btn.dataset.delete
    // eslint-disable-next-line no-alert
    if (!confirm(`Delete font "${filename}"?`))
      return
    try {
      if (scope === 'bucket')
        await this.app.api.deleteBucketFont(this.app.bucket, filename)
      else
        await this.app.api.deleteFont(filename)
      this.app.toast.success('Font deleted')
      await this._reload(scope)
    }
    catch (err) {
      this.app.toast.error(err.message)
    }
  }

  async _reload(scope) {
    if (scope === 'bucket')
      await this._loadList(
        this._bucketList, () => this.app.api.listBucketFonts(this.app.bucket),
      )
    else
      await this._loadList(this._globalList, () => this.app.api.listFonts())
  }

  static _formatSize(bytes) {
    if (bytes < KB)
      return `${bytes} B`
    if (bytes < MB)
      return `${(bytes / KB).toFixed(DECIMALS)} KB`
    return `${(bytes / MB).toFixed(DECIMALS)} MB`
  }

}
