# Spec 003: Version 3 Non-Web Native Desktop Application (`Yggdrasil.pyw`) & Smart PDF Workbench

- **Spec ID:** `SPEC-003`
- **Status:** `Approved`
- **Authoring Domain:** `/02-yggdrasil-lab/` & `[/userinterface]` (`07-userinterface-architect`)
- **Governs Downstream Targets:** `/03-agent-foundry/yggdrasil_agents/ui_agent.py`, `/04-yggdrasil-app/{native_gui.py,YggdrasilDesktop.pyw,dist_sync.py}`, `/Changelog/`, and `C:\AntiGravityFiles\output\Version 3\`
- **Depends On:** [`002-userinterface-agent-and-standalone-gui-spec.md`](002-userinterface-agent-and-standalone-gui-spec.md) (`SPEC-002`)

---

## 1. Objective & Architecture (Zero-Browser Desktop Software)

Version 3 (`v0.3.0`) delivers **Yggdrasil Sovereign Studio** as a native, console-less Windows desktop software application (`Yggdrasil.pyw` via `pythonw.exe` / `tkinter` + `ttk` + `tk.Canvas`), requiring **zero web browser, zero HTTP server, and zero external web assets**.

### Design Synthesis
- **PDF & Office Converter Workbench Inspiration (`PDF converter.pyw`):**
  - Automatic filename number extraction (`extract_numbers_from_filename`) and ascending numeric sort (`smart_sort_files`) prior to batch conversion/merging.
  - LibreOffice (`soffice.exe`) detection + `pypdf.PdfWriter` batch PDF merging + `yggdrasil_agents.pdf_converter_function` / `smart_pdf_handling_function` cross-page BM25 & $W_i$ smart index generation.
  - Persistent user preferences (`~/.yggdrasil_desktop_settings.json`), background worker threads (`threading.Thread` + `root.after`), determinate `ttk.Progressbar`, and desktop keyboard shortcuts (`Ctrl+O`, `Ctrl+B`, `Ctrl+S`, `Ctrl+F`, `Ctrl+P`, `F5`, `Escape`).
- **Gemini Desktop Shell Inspiration (`AppData\Local\Google\Gemini\app-1.19.0\`):**
  - Clean versioned application layout (`Yggdrasil.pyw`, `YggdrasilAppLauncher.bat`, `app-0.3.0/`, `resources/`, `logs/`, `version`, `YGGDRASIL_BUILD_INFO.txt`) paired with Yggdrasil's self-sufficient directories (`agents_and_lms/`, `data_and_vaults/`, `markdowns_and_specs/`, `user_content/`, `Changelog/`).
  - Gemini-inspired Nordic Aurora dark-mode `ttk` theme tokens (`build_native_tk_style_tokens`) with a left navigation rail, conversational tag-dispatch composer, native `tk.Canvas` animated $W_i$ tree, and Changelog/Vault explorer.

---

## 2. Updated `ui_agent.py` Contracts (`03-agent-foundry`)

1. `UiThemeSpec.ui_mode: Literal["native_desktop", "web_studio"] = "native_desktop"`
2. `build_native_tk_style_tokens(theme: UiThemeSpec | None = None) -> dict[str, str]`:
   - Returns strictly typed keys: `bg_canvas`, `bg_surface`, `bg_surface_alt`, `border`, `text_primary`, `text_muted`, `accent_primary`, `accent_secondary`, `accent_vault`, `accent_warning`, `font_ui`, `font_title`, `font_mono`.

---

## 3. Version 3 Directory Layout (`C:\AntiGravityFiles\output\Version 3\`)

```text
C:\AntiGravityFiles\output\Version 3\
├── Yggdrasil.pyw                  # Console-less native desktop entrypoint
├── YggdrasilAppLauncher.bat       # Launches pythonw.exe (GUI) or python.exe (CLI flags)
├── YggdrasilAppLauncher.ps1
├── YGGDRASIL_BUILD_INFO.txt
├── version                        # 0.3.0
├── app-0.3.0\                     # native_gui.py, YggdrasilDesktop.pyw, gui_app.py, app.py, exported_nano_agents.py, dist_sync.py
├── resources\                     # tk_theme_tokens.json, nano_agents_manifest.json, micro_model_1024_weights.json
├── logs\                          # yggdrasil_desktop.log
├── agents_and_lms\                # Self-contained yggdrasil_agents\ + Modelfile.yggdrasil-nano + pyproject.toml
├── data_and_vaults\               # personal_vault.db, state_tree.db, references.json, .env.example
├── markdowns_and_specs\           # AGENTS.md, PROJECT_STATE.md, specs\000..003.md, grounding logs
├── user_content\                  # brain\, instructions\, exports\, workspaces\
└── Changelog\                     # 0.1, 0.2, 0.3 tri-changelogs + CHANGELOG_INDEX.md
```
