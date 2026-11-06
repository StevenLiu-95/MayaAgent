# Maya Agent Windows Installer

Commercial-style Setup built with **Inno Setup 6**. End users do **not** need system Python — the installer runs hooks via **mayapy**.

## Prerequisites (build machine only)

1. [Inno Setup 6](https://jrsoftware.org/isdl.php) (`ISCC.exe`)
2. System Python 3 (to build offline `vendor_cache`)
3. Network access to PyPI / mirrors (first cache build)

## Version

App version comes from the repo-root ``VERSION`` file. `build.bat` runs
`python scripts/sync_version.py` before compiling so `MyAppVersion` in
`MayaAgent.iss` matches. To bump:

```bat
python scripts\bump_version.py --patch
installer\build.bat
```

## Build

From repo root or `installer/`:

```bat
installer\build.bat
```

Options:

```bat
installer\build.bat --skip-cache
```

Steps:

1. If `vendor_cache/MANIFEST.txt` is missing → `python scripts/build_vendor_cache.py`
2. Compile `MayaAgent.iss` → `dist/MayaAgent-Setup-1.6.0.exe`

Rebuild cache:

```bat
python scripts/build_vendor_cache.py --force
python scripts/build_vendor_cache.py --tags cp311
```

## What the Setup does

1. Copies the app to `%LOCALAPPDATA%\MayaAgent` (user-writable, no admin)
2. Wizard page: multi-select Maya 2020–2026 (auto-checks detected installs)
3. Runs `installer\run_engine.bat` → `mayapy scripts\install_engine.py`
   - Applies `vendor_cache/<abi>/` → `.vendor/<abi>/`
   - Writes userSetup / module / plug-in autoload hooks
4. Uninstall removes hooks (same engine `--uninstall`) then deletes files

## End-user requirements

- Windows 10/11
- Autodesk Maya installed (for mayapy)
- No system Python required

## Smoke checklist

- [ ] Machine without system Python: Setup completes
- [ ] Restart Maya → menu **Maya Agent** + shelf **MayaAgent**
- [ ] Script Editor: `import httpx` succeeds (vendor or site-packages)
- [ ] Uninstall from Windows Apps → hooks gone; restart Maya → menu gone
- [ ] `install_dragdrop.mel` still works as emergency path

## Fallback without Inno

Users can still run repo `install.bat` (mayapy-first) or drag `install_dragdrop.mel`.
