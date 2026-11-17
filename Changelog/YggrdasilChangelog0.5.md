# Yggdrasil Application Changelog — Version 0.5.0

- **Version:** `0.5.0`
- **Date:** `2026-11-17`
- **Scope:** Split-Screen Gemini Canvas Co-Editor, Universal `+` Mode Menu (`Canvas`, `Deep Research`, `Deep Think`), Collapsible Thinking Trace, Gems & Library (`studio.db`), and Antigravity SDK Hub

## Changed / Added
1. **Split-Screen `CanvasWorkspacePanel` (`/04-yggdrasil-app/studio/{app.py,theme.py}`):**
   - Right-hand `QSplitter` workspace opening alongside the chat when `canvas_content` is returned, when clicking `📝 Open in Canvas` on any message, or when opening an artifact from `📚 Library`.
   - Dual tabs: `✏️ Co-Editor` (live source editing) and `👁️ Live Preview` (rendered Markdown/HTML/Python preview).
   - Interactive deterministic transformation bar: `✨ Refine / Strip Filler` (`optimise_user_prompt`), `📐 Format CSV/Table to Markdown` (`data_handling_function`), `⚡ AST Optimize Python Code` (`coding_optimiser_function`), `💾 Save to Library`, `📤 Export File…`, and `📋 Copy`.
2. **Universal `+` Composer Menu & Active Mode/Gem Pills (`PillComposerWidget`):**
   - `+` button opens a dark Gemini menu with `📎 Upload Files…`, checkable toggles for `📝 Canvas Mode`, `🔬 Deep Research Mode`, `🧠 Deep Think Mode`, and `📄 Open Smart PDF Workbench`.
   - Active modes and active `💎 Gem` persona render as removable glowing pill chips inside the composer bar.
3. **Collapsible Thinking & Routing Trace + Per-Message Action Bar (`AssistantMessageCard`):**
   - `🧠 Show/Hide Thinking & Routing Trace (N stages)` accordion above each assistant response displaying prompt optimisation diffs, 1,024-parameter micro-model tag predictions, $W_i$ context weights, and stage latencies.
   - Per-message action bar: `📝 Open in Canvas`, `📋 Copy`, `🔄 Regenerate`, `💾 Save to Library`.
4. **Gems, Artifact Library & Antigravity SDK Hub (`/04-yggdrasil-app/studio/{store.py,app.py}`):**
   - Added `gems` (seeded with `⚗️ ChemEng Process Architect`, `🐍 Python AST & Code Optimizer`, `🎛️ PID & Control Loop Tuner`, `🔬 Deep Research & Theory Verifier`) and `artifacts` tables to `studio.db`.
   - Added `📚 Library` view (`ArtifactLibraryView`) and a dedicated **Google Antigravity SDK (`/google-antigravity-sdk`) Hub** tab inside `Pipeline & Changelogs`.
