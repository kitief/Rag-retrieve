/**
 * Desktop (single-process) build glue.
 *
 * The Python backend serves the SPA *and* the API on a loopback port, which
 * means any process — or any web page the user happens to have open — can reach
 * the API too.
 *
 * The Tauri shell therefore generates a random token per launch, passes it to
 * the sidecar as `RAGVAULT_LOCAL_TOKEN`, and has the backend inject it into
 * `index.html` as `<meta name="ragvault-token" content="…">`. Every API request
 * from the SPA echoes it back. Nothing ships in the bundle, and the token dies
 * with the process.
 */

const TOKEN_META = 'meta[name="ragvault-token"]'
const TOKEN_HEADER = 'X-RagVault-Token'

let cachedToken: string | null | undefined

/** The per-launch local API token, or null when the backend injected none. */
export function localApiToken(): string | null {
  if (cachedToken !== undefined) return cachedToken
  if (typeof document === 'undefined') {
    cachedToken = null
    return cachedToken
  }
  const meta = document.querySelector(TOKEN_META)
  const value = meta?.getAttribute('content')?.trim()
  cachedToken = value ? value : null
  return cachedToken
}

/** True when the SPA was served by the local backend rather than the Vite dev server. */
export function isDesktopBuild(): boolean {
  return localApiToken() !== null
}

/** Headers required by the local backend; empty when it injected no token. */
export function localAuthHeaders(): Record<string, string> {
  const token = localApiToken()
  return token ? { [TOKEN_HEADER]: token } : {}
}

/**
 * Save a generated file to disk.
 *
 * In a browser this is the usual blob-URL + `<a download>` dance. Inside
 * WebView2 that path is broken: the transfer is handed to the WebView2
 * download machinery, lands in the profile cache and then reports a download
 * error, so the user clicks "Download" and nothing appears — no dialog, no
 * error message from the page. When the shell is present the bytes go over IPC
 * instead and Rust writes the file, which also lets it pick a writable folder
 * and avoid overwriting an existing file.
 *
 * Returns the absolute path when the shell wrote the file, or null when the
 * save was cancelled (desktop) or the browser path was used (web, where the
 * download is asynchronous and opaque).
 */
export async function saveFile(
  data: Blob,
  filename: string,
): Promise<string | null> {
  if (isDesktopBuild()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core')
      const bytes = Array.from(new Uint8Array(await data.arrayBuffer()))
      // The shell opens a native "Save as" dialog and returns the chosen path,
      // or null when the user cancelled — in which case there is nothing to
      // fall back to, so report it as a cancelled save rather than downloading
      // the file somewhere the user did not ask for.
      const path = await invoke<string | null>('save_download', {
        filename,
        data: bytes,
      })
      return path
    } catch (error) {
      // Fall through to the browser path so a shell that predates this command
      // (or a failed IPC call) still produces a file somewhere.
      console.warn('[desktop] IPC save failed, falling back to a download', error)
    }
  }

  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revoking immediately can cancel an in-flight download in WebKit, so give
  // the browser a moment to pick the blob up.
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
  return null
}

