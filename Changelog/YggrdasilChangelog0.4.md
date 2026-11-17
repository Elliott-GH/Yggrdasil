# Yggdrasil Application Changelog — Version 0.4.0

- **Version:** `0.4.0`
- **Date:** `2026-11-17`
- **Scope:** Gemini-Clone Native `PySide6` Desktop Studio (`YggdrasilStudio.pyw`), Persistent Projects & Conversations (`studio.db`), and `Version 4` Distribution

## Changed / Added
1. **Gemini-Style Native Desktop UI (`/04-yggdrasil-app/studio/{theme.py,app.py}` & `YggdrasilStudio.pyw`):**
   - Built in `PySide6` with a custom-painted radial dark-blue glow (`RadialGlowCanvas`), centered `"Where should we start?"` greeting, rounded 26px pill composer (`PillComposerWidget` with `+` attachment button, auto-growing input, model picker, and send/stop button), and 3 clickable starter chips.
   - Collapsible left sidebar (`Ctrl+B` toggles 264px expanded vs. 56px icon rail):
     - `+ New chat` (`Ctrl+N`), `Ctrl+K` conversation search, `PDF Workbench`, and `Pipeline & Changelogs`.
     - **Projects** section (in Gemini's "Notebooks" slot): `+` create project, `All` filter reset, project scope selection, air-gap lock indicators, and `ProjectEditorDialog` (custom instructions, air-gap privacy toggle, and pinned project notes).
     - **Conversations** list: pinned-first ordering, right-click context menu (`Rename`, `Pin/Unpin`, `Move to project`, `Delete`).
   - Multi-turn **Conversation View**: right-aligned user bubbles (`UserMessageBubble`), left-aligned Markdown assistant responses (`AssistantMessageCard`) with live token streaming and expandable pipeline route badges (`⚡ Deterministic · 0 LLM tokens`, `🦙 Local Nano`, `🔒 Air-Gapped Vault`).
2. **Persistent SQLite Projects & Conversations (`/04-yggdrasil-app/studio/{store.py,paths.py,settings.py}`):**
   - Thread-safe `StudioStore` (`studio.db`, WAL + foreign keys) storing `projects`, `project_notes`, `conversations`, and `messages`.
   - `StudioPaths` & `resolve_studio_paths()` supporting both monorepo and standalone `Version 4` (`app-0.4.0/`) layouts.
3. **Standalone `Version 4` Distribution (`/04-yggdrasil-app/dist_sync.py`):**
   - Generates `C:\AntiGravityFiles\output\Version 4\` (`Yggdrasil.pyw`, `YggdrasilAppLauncher.bat/.ps1`, `app-0.4.0/`, `agents_and_lms/`, `data_and_vaults/`, `markdowns_and_specs/`, `user_content/`, `resources/`, `logs/`, `Changelog/`) and points root launchers to `Version 4`.
