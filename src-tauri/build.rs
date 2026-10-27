fn main() {
    // The shell exposes one privileged command to the SPA (`save_download`).
    // Declaring it here makes tauri-build autogenerate the `allow-save-download`
    // permission, which `capabilities/remote.json` then grants to the
    // http://127.0.0.1:* origin the window actually loads.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["save_download"]),
        ),
    )
    .expect("failed to run tauri-build");
}
