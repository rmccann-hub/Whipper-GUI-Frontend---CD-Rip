# AppImage build & testing procedure

The AppImage is built by exactly one recipe — `build/build_appimage.sh` — used
locally, in CI, and at release time. This doc is the procedure for testing it
in each situation, including branches that don't have a published release yet.

## When the AppImage is built

| Trigger | Workflow | Result |
|---|---|---|
| Every push to `main` | `.github/workflows/appimage.yml` | Builds + smoke-tests (`--version`); uploads the AppImage as a **run artifact**. Catches a broken build recipe immediately. |
| Manual run on **any branch** | `appimage.yml` (`workflow_dispatch`) | Same — a downloadable AppImage artifact for a branch with no release. |
| Push a `vX.Y.Z` tag | `.github/workflows/release.yml` | Builds, checksums, and **publishes** the AppImage + `install.sh`/`install-appimage.sh` to a GitHub Release (`v0.*` → pre-release). |

## Testing `main`

Every push to `main` runs the **AppImage** workflow. Confirm it's green in the
**Actions** tab. To test the actual binary, open the latest `AppImage` run and
download the `whipper-gui-x86_64.AppImage` artifact, then:

```bash
chmod +x whipper-gui-x86_64.AppImage
./whipper-gui-x86_64.AppImage --version       # quick smoke test
bash install-appimage.sh ./whipper-gui-x86_64.AppImage   # desktop-integrate it
```

## Testing a feature branch (no release yet)

A branch won't have a published AppImage. Two ways to get one:

1. **CI artifact (recommended).** Actions tab → **AppImage** workflow → **Run
   workflow** → pick your branch. When it finishes, download the
   `whipper-gui-x86_64.AppImage` artifact from the run and test as above.
2. **Build locally** from the checkout:
   ```bash
   git checkout my-branch
   bash build/build_appimage.sh          # → whipper-gui-x86_64.AppImage
   bash install.sh --build               # build + host stack + integrate
   # or, if the host stack is already set up:
   bash install.sh --no-host --appimage ./whipper-gui-x86_64.AppImage
   ```

## Testing the release flow

1. Bump `__version__` in `src/whipper_gui/__init__.py` and add a `CHANGELOG.md`
   entry.
2. `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. Watch the **Release** workflow; confirm the GitHub Release has the AppImage,
   its `.sha256`, and the installer scripts attached.
4. Test the published artifact as an end user would:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/rmccann-hub/Whipper-GUI-Frontend---CD-Rip/main/install.sh | bash
   ```

## Testing the installer / uninstaller without a real machine

`install.sh`, `install-appimage.sh`, and `uninstall.sh` are guarded by smoke
tests (`tests/test_install_script.py`, `tests/test_install_appimage_script.py`,
`tests/test_setup_host_script.py`) that check syntax, `--help`, and `--dry-run`
behaviour, and exercise an install→uninstall round-trip against a sandboxed
`HOME`. Run them with `pytest`. The full host-stack bootstrap (Distrobox +
whipper) still needs a real-hardware confirmation — CI only dry-run-tests it.
