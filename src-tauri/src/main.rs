//! RagVault desktop shell.
//!
//! Responsibilities, in order:
//!   1. pick a per-user data directory,
//!   2. generate a one-shot local token,
//!   3. spawn the frozen Python backend as a child process on an ephemeral port,
//!   4. wait for its `RAGVAULT_READY port=<n>` handshake (and double-check /health),
//!   5. open a webview pointed at `http://127.0.0.1:<port>/`,
//!   6. make sure the child dies when the window closes.
//!
//! The backend serves the built SPA itself, so the webview loads the app and the
//! API from the same origin. That keeps `baseURL: '/api'` working unchanged and
//! removes CORS from the picture entirely.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::DialogExt;

const READY_PREFIX: &str = "RAGVAULT_READY port=";
const WINDOW_LABEL: &str = "main";
const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);

/// Holds the backend child so it can be killed exactly once, on either the
/// window close or the process exit path (whichever happens first).
struct BackendProcess {
    child: Mutex<Option<Child>>,
    /// Keeps the backend inside a kill-on-close job, so the OS reaps it even if
    /// this process is terminated without running any of our cleanup code.
    /// `None` means no job object was available; cleanup then relies on
    /// `shutdown()` alone.
    job: Option<job::JobObject>,
}

/// Windows Job Object wrapper.
///
/// `shutdown()` is the polite path, but it only runs when the shell gets to
/// handle `RunEvent::Exit`. A force-kill (Task Manager, a crash, a debugger
/// stop) skips it and would leave `ragvault-backend.exe` running forever,
/// holding the SQLite file and the port. Assigning the child to a job created
/// with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` makes the kernel kill it as soon as
/// the last handle to the job closes — which happens when this process dies for
/// any reason at all.
#[cfg(windows)]
mod job {
    use std::ffi::c_void;
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;

    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    pub struct JobObject(HANDLE);

    // The handle is only used through the Win32 API, which is thread safe.
    unsafe impl Send for JobObject {}
    unsafe impl Sync for JobObject {}

    impl JobObject {
        /// Returns `None` when job objects are unavailable; the shell still
        /// works, it just loses the crash-safety net.
        pub fn create() -> Option<Self> {
            let handle = unsafe { CreateJobObjectW(std::ptr::null_mut(), std::ptr::null()) };
            if handle.is_null() {
                return None;
            }

            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION =
                unsafe { std::mem::zeroed() };
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;

            let ok = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if ok == 0 {
                unsafe { CloseHandle(handle) };
                return None;
            }

            Some(Self(handle))
        }

        pub fn assign(&self, child: &Child) -> bool {
            let ok = unsafe { AssignProcessToJobObject(self.0, child.as_raw_handle() as HANDLE) };
            ok != 0
        }
    }

    impl Drop for JobObject {
        fn drop(&mut self) {
            unsafe { CloseHandle(self.0) };
        }
    }
}

#[cfg(not(windows))]
mod job {
    use std::process::Child;

    pub struct JobObject;

    impl JobObject {
        pub fn create() -> Option<Self> {
            Some(Self)
        }

        pub fn assign(&self, _child: &Child) -> bool {
            false
        }
    }
}

struct Launch {
    child: Child,
    lines: Receiver<String>,
    job: Option<job::JobObject>,
}

fn data_dir(app: &tauri::AppHandle) -> PathBuf {
    // Escape hatch used by automated tests and by "portable" runs where the
    // caller wants the database next to the executable instead of in APPDATA.
    if let Ok(custom) = std::env::var("RAGVAULT_DATA_DIR") {
        if !custom.trim().is_empty() {
            return PathBuf::from(custom);
        }
    }
    app.path()
        .app_data_dir()
        .map(|dir| dir.join("data"))
        .unwrap_or_else(|_| std::env::temp_dir().join("ragvault-data"))
}

/// Where WebView2 keeps its own profile (cookies, cache, GPU shaders).
///
/// It must be a writable directory: WebView2 creates the folder itself and
/// refuses to start if it cannot. Defaults to the platform cache dir, with the
/// same `RAGVAULT_WEBVIEW_DIR` escape hatch as `RAGVAULT_DATA_DIR`.
fn webview_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(custom) = std::env::var("RAGVAULT_WEBVIEW_DIR") {
        if !custom.trim().is_empty() {
            return PathBuf::from(custom);
        }
    }
    app.path()
        .app_local_data_dir()
        .map(|dir| dir.join("webview"))
        .unwrap_or_else(|_| std::env::temp_dir().join("ragvault-webview"))
}

/// Locate the frozen backend executable.
///
/// * Packaged: `<resource_dir>/backend/ragvault-backend.exe`
/// * `cargo run` from the repo: `<repo>/dist/ragvault-backend/ragvault-backend.exe`
fn backend_exe(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let exe_name = if cfg!(windows) {
        "ragvault-backend.exe"
    } else {
        "ragvault-backend"
    };

    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join("backend").join(exe_name));
    }

    // Development convenience: cargo puts us in src-tauri/target/<profile>.
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo_root) = manifest.parent() {
        candidates.push(
            repo_root
                .join("dist")
                .join("ragvault-backend")
                .join(exe_name),
        );
        candidates.push(repo_root.join("dist").join(exe_name));
    }

    for candidate in &candidates {
        if candidate.is_file() {
            return Ok(candidate.clone());
        }
    }

    Err(format!(
        "Could not find {exe_name}. Looked in:\n{}",
        candidates
            .iter()
            .map(|p| format!("  - {}", p.display()))
            .collect::<Vec<_>>()
            .join("\n")
    ))
}

fn log_path(app: &tauri::AppHandle) -> PathBuf {
    // Keep the backend log next to the data so a support report is one folder.
    data_dir(app).join("backend.log")
}

/// Pick a directory WebView2 is actually allowed to write into.
///
/// The SPA saves PDFs through a `blob:` URL plus `<a download>`, which WebView2
/// routes through its own download machinery rather than the page. Left alone
/// that lands in the user's Downloads folder, and if anything rejects the write
/// the file simply never appears — no error, no dialog, nothing. Probing here
/// means we hand WebView2 a destination that is known to work, and we can log
/// which one we chose.
fn download_dir(app: &tauri::AppHandle) -> PathBuf {
    if let Ok(custom) = std::env::var("RAGVAULT_DOWNLOAD_DIR") {
        if !custom.trim().is_empty() {
            let dir = PathBuf::from(custom);
            if is_writable(&dir) {
                return dir;
            }
        }
    }

    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Some(home) = std::env::var_os("USERPROFILE") {
        candidates.push(PathBuf::from(home).join("Downloads"));
    }
    candidates.push(data_dir(app).join("downloads"));
    candidates.push(std::env::temp_dir().join("ragvault-downloads"));

    for candidate in candidates {
        if is_writable(&candidate) {
            return candidate;
        }
    }
    // Nothing is writable; let WebView2 try its own default and report failure.
    std::env::temp_dir()
}

fn is_writable(dir: &Path) -> bool {
    if std::fs::create_dir_all(dir).is_err() {
        return false;
    }
    let probe = dir.join(".ragvault-write-probe");
    match std::fs::write(&probe, b"ok") {
        Ok(()) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

/// Make `name` unique inside `dir` without asking the user anything.
fn unique_path(dir: &Path, name: &str) -> PathBuf {
    let candidate = dir.join(name);
    if !candidate.exists() {
        return candidate;
    }

    let path = Path::new(name);
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "download".to_string());
    let ext = path
        .extension()
        .map(|s| format!(".{}", s.to_string_lossy()))
        .unwrap_or_default();

    for index in 1..1000 {
        let next = dir.join(format!("{stem} ({index}){ext}"));
        if !next.exists() {
            return next;
        }
    }
    dir.join(format!("{stem}-{}{ext}", std::process::id()))
}

fn launch_backend(app: &tauri::AppHandle, token: &str) -> Result<Launch, String> {
    let exe = backend_exe(app)?;
    let workdir = exe
        .parent()
        .ok_or_else(|| "backend executable has no parent directory".to_string())?
        .to_path_buf();
    let data = data_dir(app);
    std::fs::create_dir_all(&data)
        .map_err(|err| format!("Could not create data dir {}: {err}", data.display()))?;

    // Create the job before spawning so there is no window in which a crash
    // leaves an unowned child behind.
    let job = job::JobObject::create();
    if job.is_none() {
        eprintln!("[shell] warning: could not create a job object; the backend will not be");
        eprintln!("[shell]          reaped automatically if this process is force-killed");
    }

    let mut command = Command::new(&exe);
    command
        .current_dir(&workdir)
        // `--port 0` lets the OS pick a free port; the backend reports it back
        // on stdout. Asking the OS first and then binding would race.
        .arg("--data-dir")
        .arg(&data)
        .arg("--port")
        .arg("0")
        .arg("--host")
        .arg("127.0.0.1")
        .env("RAGVAULT_LOCAL_TOKEN", token)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    // A console window popping up behind the app would look broken.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|err| format!("Failed to start {}: {err}", exe.display()))?;
    eprintln!(
        "[shell] spawned backend pid={} exe={} data={}",
        child.id(),
        exe.display(),
        data.display()
    );

    let job = match job {
        Some(job) => {
            if job.assign(&child) {
                eprintln!("[shell] backend assigned to job object");
            } else {
                eprintln!("[shell] warning: could not assign the backend to a job object");
            }
            Some(job)
        }
        None => None,
    };

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    let (tx, rx) = mpsc::channel::<String>();

    // Forward both streams into the channel (for the handshake) and into the
    // log file (so a crash after startup is still diagnosable).
    let log_file_path = log_path(app);
    if let Some(parent) = log_file_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_file_path)
        .ok();

    if let Some(stream) = stdout {
        let tx_out = tx.clone();
        let mut sink = log_file;
        thread::spawn(move || {
            let mut reader = BufReader::new(stream);
            let mut raw: Vec<u8> = Vec::new();
            loop {
                raw.clear();
                match reader.read_until(b'\n', &mut raw) {
                    Ok(0) => break,
                    Ok(_) => {}
                    Err(err) => {
                        // A read error must not silently end the pump: that
                        // closes the channel and looks exactly like "the child
                        // exited" even though it is still running.
                        eprintln!("[shell] stdout read error: {err}");
                        break;
                    }
                }
                // Python may emit the console code page (cp936 on a zh-CN
                // machine) instead of UTF-8, so never assume valid UTF-8 here.
                let trimmed = decode_lossy(&raw);
                let trimmed = trimmed.trim_end();
                if let Some(sink) = sink.as_mut() {
                    let _ = writeln!(sink, "{trimmed}");
                }
                let _ = tx_out.send(trimmed.to_string());
            }
        });
    }

    if let Some(stream) = stderr {
        let err_path = log_file_path.with_file_name("backend.stderr.log");
        let mut sink = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&err_path)
            .ok();
        let tx_err = tx.clone();
        thread::spawn(move || {
            let mut reader = BufReader::new(stream);
            let mut raw: Vec<u8> = Vec::new();
            loop {
                raw.clear();
                match reader.read_until(b'\n', &mut raw) {
                    Ok(0) => break,
                    Ok(_) => {}
                    Err(err) => {
                        eprintln!("[shell] stderr read error: {err}");
                        break;
                    }
                }
                let trimmed = decode_lossy(&raw);
                let trimmed = trimmed.trim_end();
                if let Some(sink) = sink.as_mut() {
                    let _ = writeln!(sink, "{trimmed}");
                }
                let _ = tx_err.send(trimmed.to_string());
                eprintln!("[backend] {trimmed}");
            }
        });
    }
    drop(tx);

    Ok(Launch {
        child,
        lines: rx,
        job,
    })
}

/// Decode one line of child output without ever failing.
///
/// The frozen backend prints paths that can contain non-ASCII characters. When
/// its stdio is a pipe (rather than a console) Python still picks an encoding
/// from the environment, and on a zh-CN Windows box that can be cp936. Treating
/// the bytes as UTF-8 first and falling back to a lossy conversion keeps the
/// reader alive; a hard `read_line` into a `String` would return `Err` and end
/// the pump thread, which looks identical to the child exiting.
fn decode_lossy(raw: &[u8]) -> String {
    String::from_utf8_lossy(raw).to_string()
}

fn wait_for_ready(child: &mut Child, lines: &Receiver<String>) -> Result<u16, String> {
    let deadline = Instant::now() + STARTUP_TIMEOUT;
    let mut observed: Vec<String> = Vec::new();

    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(format!(
                "The backend did not report a port within {}s. Last output:\n{}",
                STARTUP_TIMEOUT.as_secs(),
                observed
                    .iter()
                    .rev()
                    .take(15)
                    .cloned()
                    .collect::<Vec<_>>()
                    .join("\n")
            ));
        }

        match lines.recv_timeout(remaining) {
            Ok(line) => {
                if let Some(rest) = line.trim().strip_prefix(READY_PREFIX) {
                    let port: u16 = rest
                        .trim()
                        .parse()
                        .map_err(|err| format!("Bad port in handshake '{line}': {err}"))?;
                    return Ok(port);
                }
                observed.push(line);
                if observed.len() > 200 {
                    observed.remove(0);
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => continue,
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                let status = child.wait().ok();
                return Err(format!(
                    "The backend exited before reporting a port (status: {}). Last output:\n{}",
                    match status {
                        Some(st) => format!("{st:?}"),
                        None => "unknown".to_string(),
                    },
                    observed
                        .iter()
                        .rev()
                        .take(15)
                        .cloned()
                        .collect::<Vec<_>>()
                        .join("\n")
                ));
            }
        }
    }
}

fn wait_for_health(port: u16) -> bool {
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    let url = format!("http://127.0.0.1:{port}/health");

    while Instant::now() < deadline {
        // A plain TCP connect is enough: uvicorn only accepts once the routes
        // are mounted, and pulling in an HTTP client here buys nothing.
        if std::net::TcpStream::connect_timeout(
            &format!("127.0.0.1:{port}")
                .parse()
                .expect("static socket address parses"),
            Duration::from_millis(500),
        )
        .is_ok()
        {
            eprintln!("[shell] backend reachable at {url}");
            return true;
        }
        thread::sleep(Duration::from_millis(200));
    }

    eprintln!("[shell] backend never became reachable at {url}");
    false
}

fn open_window(app: &tauri::AppHandle, port: u16) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/");
    let parsed = url
        .parse()
        .map_err(|err| format!("Could not parse {url}: {err}"))?;

    let profile = webview_dir(app);
    std::fs::create_dir_all(&profile)
        .map_err(|err| format!("Could not create the WebView2 profile dir {}: {err}", profile.display()))?;

    // Downloads the SPA triggers no longer come through here: WebView2's
    // download stack fails for every scheme (blob:, data:, http:), so
    // generated PDFs are handed to the shell over IPC instead (`save_download`).
    // This handler stays as a safety net for genuine http(s) links the user
    // clicks, so they land in the data dir rather than the WebView2 cache.
    let download_target = download_dir(app);
    std::fs::create_dir_all(&download_target).ok();
    eprintln!("[shell] downloads go to {}", download_target.display());
    let download_target_for_handler = download_target.clone();

    WebviewWindowBuilder::new(app, WINDOW_LABEL, WebviewUrl::External(parsed))
        .title("RagVault")
        .inner_size(1280.0, 860.0)
        .min_inner_size(1100.0, 720.0)
        .center()
        .data_directory(profile)
        // Tauri installs its own IDropTarget on Windows so it can emit
        // DragDropEvents. That replacement swallows the drop before the DOM sees
        // it, so react-dropzone's onDrop never fires and dragging a PDF onto the
        // window does nothing. The SPA has no use for the Tauri drag events, so
        // hand the platform behaviour back to WebView2 and let HTML5 drag and
        // drop work.
        .disable_drag_drop_handler()
        .on_download(move |_webview, event| {
            match event {
                tauri::webview::DownloadEvent::Requested { url, destination } => {
                    // `destination` starts as WebView2's guess, usually the
                    // suggested filename inside the default download folder.
                    let name = destination
                        .file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .filter(|n| !n.is_empty())
                        .unwrap_or_else(|| "download".to_string());
                    let target = unique_path(&download_target_for_handler, &name);
                    eprintln!("[shell] download {} -> {}", url, target.display());
                    *destination = target;
                    true
                }
                tauri::webview::DownloadEvent::Finished { url, path, success } => {
                    match path {
                        Some(path) if success => {
                            eprintln!("[shell] download saved to {}", path.display());
                        }
                        _ => eprintln!("[shell] download failed: {url}"),
                    }
                    true
                }
                _ => true,
            }
        })
        .build()
        .map_err(|err| format!("Could not create the app window: {err}"))?;

    Ok(())
}

fn shutdown(state: &BackendProcess) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
            eprintln!("[shell] backend stopped");
        }
    }
    // Dropping the job handle is what guarantees the child is gone even if the
    // kill above failed (for example because the pid was already reused).
    let _ = &state.job;
}

/// Write a generated PDF to disk on behalf of the SPA.
///
/// The SPA exports notes as a PDF by turning an `axios` blob response into a
/// `blob:` URL and clicking a synthetic `<a download>`. Chromium treats that as
/// a normal download; WebView2 does not — the transfer goes into the WebView2
/// cache and then reports a download error, so the user clicks "Download" and
/// no file ever appears. Handling `DownloadStarting` is not enough (the
/// transfer itself fails for `blob:`, `data:` and `http:` alike), so the bytes
/// take a different route: the frontend sends them over IPC and Rust writes the
/// file after asking the user where it should go.
///
/// Returns the chosen path, or `None` when the user cancelled the dialog.
///
/// This is an `async` command on purpose. Tauri runs non-`async` commands on
/// the main thread, and the dialog plugin implements its "blocking" helpers by
/// posting the dialog to that same thread — from there it deadlocks, the window
/// never appears, and the call resolves with the suggested path as if the user
/// had accepted it. Using the callback API from an async command keeps the
/// event loop free while the dialog is up.
#[tauri::command]
async fn save_download(
    app: tauri::AppHandle,
    filename: String,
    data: Vec<u8>,
) -> Result<Option<String>, String> {
    let safe = sanitise_filename(&filename);

    let mut builder = app
        .dialog()
        .file()
        .set_title(&safe)
        .set_file_name(&safe)
        .add_filter("PDF document", &["pdf"]);

    let start_dir = download_dir(&app);
    if start_dir.is_dir() {
        builder = builder.set_directory(&start_dir);
    }

    let (tx, rx) = std::sync::mpsc::channel();
    builder.save_file(move |picked| {
        let _ = tx.send(picked);
    });

    // `save_file` hands the answer to a callback on another thread; park a
    // blocking-pool thread on the channel instead of the async reactor.
    let chosen = tauri::async_runtime::spawn_blocking(move || rx.recv().ok().flatten())
        .await
        .map_err(|err| format!("Save dialog task failed: {err}"))?;

    let chosen = match chosen {
        Some(path) => path,
        None => {
            eprintln!("[shell] save cancelled for {safe}");
            return Ok(None);
        }
    };

    let target = chosen
        .into_path()
        .map_err(|err| format!("Unusable save location: {err}"))?;

    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|err| format!("Could not create {}: {err}", parent.display()))?;
    }

    std::fs::write(&target, &data)
        .map_err(|err| format!("Could not write {}: {err}", target.display()))?;

    eprintln!("[shell] saved {} bytes to {}", data.len(), target.display());
    Ok(Some(target.to_string_lossy().to_string()))
}

/// Keep only the final path component and drop characters Windows rejects.
fn sanitise_filename(name: &str) -> String {
    let base = Path::new(name)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();

    let cleaned: String = base
        .chars()
        .map(|c| match c {
            '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*' => '_',
            c if (c as u32) < 0x20 => '_',
            c => c,
        })
        .collect();

    let trimmed = cleaned.trim().trim_matches('.').to_string();
    if trimmed.is_empty() {
        "ragvault-download.pdf".to_string()
    } else {
        trimmed
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            // Second launch: surface the existing window instead of starting a
            // second backend on a second port.
            if let Some(window) = app.get_webview_window(WINDOW_LABEL) {
                let _ = window.set_focus();
                let _ = window.unminimize();
            }
        }))
        .invoke_handler(tauri::generate_handler![save_download])
        .setup(|app| {
            let handle = app.handle().clone();

            let token = uuid::Uuid::new_v4().simple().to_string();
            eprintln!("[shell] data dir: {}", data_dir(&handle).display());

            let mut launch = match launch_backend(&handle, &token) {
                Ok(launch) => launch,
                Err(err) => return Err(err.into()),
            };

            let port = match wait_for_ready(&mut launch.child, &launch.lines) {
                Ok(port) => port,
                Err(err) => {
                    let _ = launch.child.kill();
                    let _ = launch.child.wait();
                    return Err(err.into());
                }
            };

            eprintln!("[shell] backend ready on port {port}");
            let state = BackendProcess {
                child: Mutex::new(Some(launch.child)),
                job: launch.job.take(),
            };

            wait_for_health(port);
            if let Err(err) = open_window(&handle, port) {
                // The window is the whole product: if it cannot be created the
                // process is about to exit, so do not leave the backend behind.
                shutdown(&state);
                return Err(err.into());
            }

            app.manage(state);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build the RagVault shell")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<BackendProcess>() {
                    shutdown(&state);
                }
            }
        });
}
