# Yggdrasil App Changelog — Version 0.2.0

- **Version:** `0.2.0`
- **Date:** `2026-11-17`
- **Scope:** Gemini-Branded Yggdrasil Studio GUI, Standalone Path Detection & Self-Sufficient `output/` Packager

## Changed / Added
1. **Central Studio GUI Controller (`/04-yggdrasil-app/gui_app.py` -> `Version 2/executables/yggdrasil_studio.py`):**
   - Added zero-CDN offline single-page Gemini-inspired **Yggdrasil Studio** UI with Nordic Aurora theme, interactive tag quick-chips (`#TABLE_DATA`..`#RESEARCH_GAP`, `[/userinterface]`), animated $W_i$ SVG tree panel, Air-Gap Privacy Shield badge, Changelog inspector tab, and User Content inventory view.
   - Added interactive `[/userinterface]` handoff confirmation UI card whenever visual/GUI keywords are submitted without `[/userinterface]`.
   - Added `--self-test` verification mode generating `user_content/brain/studio_snapshot.html` and verifying standalone isolation.
2. **Self-Sufficient Distribution Packager (`/04-yggdrasil-app/dist_sync.py`):**
   - Populates `C:\AntiGravityFiles\output\Version 1` (`v0.1.0` backup) and `C:\AntiGravityFiles\output\Version 2` (`v0.2.0` full Studio release) with organized `executables/`, `agents_and_lms/`, `data_and_vaults/`, `markdowns_and_specs/`, `user_content/{brain,instructions,exports,workspaces}`, and `Changelog/`.
   - Generates one-click Windows launchers (`Launch-Yggdrasil.bat` / `.ps1` and `Launch-Yggdrasil-Studio.bat` / `.ps1`).
3. **Dual-Layout Self-Sufficiency in `app.py` & `exported_nano_agents.py`:**
   - Updated path resolution to prefer local `../agents_and_lms/` and `../data_and_vaults/` when launched inside a standalone `output/Version X/` bundle.
