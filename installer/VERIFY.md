# Maya Agent Setup — manual verification

## Build machine

- [ ] `python scripts/build_vendor_cache.py` creates `vendor_cache/cp37|cp39|cp311` + `MANIFEST.txt`
- [ ] `installer\build.bat` produces `dist\MayaAgent-Setup-1.6.0.exe`
- [ ] Slim pack: `python scripts/build_vendor_cache.py --tags cp311 --force` then rebuild

## End-user PC (no system Python)

- [ ] Maya installed; `python` not on PATH
- [ ] Run Setup → pick detected Maya versions → finish without fatal error
- [ ] `%LOCALAPPDATA%\MayaAgent` contains `maya_agent`, `scripts`, `.vendor\cp*`, `unins_versions.txt`
- [ ] Fully quit Maya, restart
- [ ] Menu **Maya Agent** visible; shelf **MayaAgent** present
- [ ] Script Editor: `import httpx` OK
- [ ] Open panel, send a trivial chat (needs API key)

## Uninstall

- [ ] Windows Settings → Apps → uninstall Maya Agent
- [ ] Restart Maya → menu/shelf gone
- [ ] `Documents\maya\plug-ins\MayaAgent.py` removed
- [ ] Install folder removed (or empty)

## Fallbacks

- [ ] `install.bat` works with only mayapy on a custom `MAYA_AGENT_MAYAPY_ROOTS`
- [ ] Drag `install_dragdrop.mel` after Setup does not break hooks (same marker blocks)
- [ ] `mayapy scripts/install_engine.py --dry-run` prints paths only
