/**
 * Paint the remembered theme before the app bundle loads.
 *
 * The stylesheet ships dark defaults and React only applies the saved theme
 * after hydration, so a light-mode user watched the window flash dark on every
 * launch. `applyTheme()` (src/theme.ts) caches the mode and the variables it
 * computed into localStorage; this script replays them synchronously, before
 * first paint.
 *
 * This is a plain classic script loaded from `<head>` on purpose:
 *   - it must run before the module bundle, not after it;
 *   - it has to stay tiny and dependency-free, because anything slower than the
 *     stylesheet is a visible flash;
 *   - it must never throw, or the page would render unstyled.
 *
 * Keep the keys in sync with BOOT_MODE_KEY / BOOT_VARS_KEY in src/theme.ts.
 */
;(function () {
  var MODE_KEY = 'ragvault-theme-mode'
  var VARS_KEY = 'ragvault-theme-vars'

  try {
    var mode = window.localStorage.getItem(MODE_KEY)
    if (mode !== 'light' && mode !== 'dark') return

    var root = document.documentElement
    root.classList.remove(mode === 'light' ? 'dark' : 'light')
    root.classList.add(mode)

    var raw = window.localStorage.getItem(VARS_KEY)
    if (!raw) return

    var vars = JSON.parse(raw)
    for (var key in vars) {
      if (Object.prototype.hasOwnProperty.call(vars, key)) {
        root.style.setProperty(key, vars[key])
      }
    }
  } catch (err) {
    /* No storage, corrupt JSON, or a hostile sandbox: keep the defaults. */
  }
})()
