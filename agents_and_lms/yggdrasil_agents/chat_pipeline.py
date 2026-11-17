"""Nested conversational chat pipeline for Yggdrasil Studio (SPEC-004 Section 2).

Implements the deterministic-first, token-conserving conversational pipeline:
1. ``optimise_user_prompt`` — pure-Python conversational filler stripping & intent detection
2. ``pre_group_prompt`` & ``ThousandParamMicroModel`` — zero-LLM tag & attachment slicing
3. ``NestedModelOrchestrator`` — pure-Python deterministic execution with readable Markdown rendering
4. Single shared ``LocalEngine.stream_chat`` or air-gap-guarded ``LeavesCloudAgent.stream_chat``
5. Thread-safe persistent background ``asyncio`` event loop for non-blocking GUI integration
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import math
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .deterministic_tools import (
    CalculationSolverOutput,
    CodingOptimiserOutput,
    ControlSystemOutput,
    DataComparisonOutput,
    PdfConverterOutput,
    ResearchToolOutput,
    SmartPdfOutput,
    TableHandlingOutput,
)
from .leaves import LeavesCloudAgent, SanitizedCloudRequest
from .local_engine import LocalEngine, LocalEngineConfig
from .micro_model import ThousandParamMicroModel
from .orchestrator import (
    NestedModelOrchestrator,
    OrchestratorConfig,
    SliceExecutionResult,
)
from .pre_slicer import (
    DETERMINISTIC_TAGS,
    DataSlice,
    PreGroupedBundle,
    TagType,
    contains_pii_or_vault_taint,
    pre_group_prompt,
)
from .trunk import compute_decay_weight

ChatRole = Literal["user", "assistant", "system"]
TurnRoute = Literal["deterministic", "local_llm", "cloud", "mixed", "offline_fallback"]
CanvasKind = Literal["markdown", "code", "html", "report"]


class ChatHistoryMessage(BaseModel):
    """Single message entry in a conversation history window."""

    role: ChatRole
    content: str


class ProjectContext(BaseModel):
    """Project-scoped instructions, pinned notes, and privacy policy."""

    project_id: str | None = None
    name: str = ""
    instructions: str = ""
    pinned_notes: list[str] = Field(default_factory=list)
    air_gapped: bool = False


class OptimisedPrompt(BaseModel):
    """Result of pure-Python prompt optimisation and micro-model intent detection."""

    original: str
    optimised_text: str
    removed_filler: list[str] = Field(default_factory=list)
    detected_intents: list[str] = Field(default_factory=list)


class PipelineStage(BaseModel):
    """Telemetry record for a single stage of the StudioChatPipeline turn."""

    name: str
    detail: str
    latency_ms: float = 0.0


class ChatTurnRequest(BaseModel):
    """Input contract for a single conversational turn in Yggdrasil Studio."""

    turn_id: str
    user_text: str = Field(min_length=1)
    history: list[ChatHistoryMessage] = Field(default_factory=list)
    project: ProjectContext | None = None
    model_choice: str = "auto"
    local_only: bool = False
    attachments: list[str] = Field(default_factory=list)
    deep_research: bool = False
    thinking_mode: bool = False
    open_in_canvas: bool = False
    gem_name: str | None = None
    gem_instructions: str = ""


class ChatTurnResult(BaseModel):
    """Output contract produced by StudioChatPipeline for a single conversational turn."""

    turn_id: str
    answer_markdown: str
    route: TurnRoute
    model_used: str | None = None
    tags_detected: list[str] = Field(default_factory=list)
    stages: list[PipelineStage] = Field(default_factory=list)
    deterministic_hits: int = 0
    llm_tokens_used: int = 0
    air_gap_enforced: bool = False
    suggested_title: str | None = None
    error: str | None = None
    thinking_trace_markdown: str = ""
    canvas_title: str | None = None
    canvas_content: str | None = None
    canvas_kind: CanvasKind = "markdown"
    citations: list[str] = Field(default_factory=list)


class ChatPipelineConfig(BaseModel):
    """Configuration for StudioChatPipeline local and cloud endpoints."""

    default_local_model: str = "qwen2.5:0.5b"
    ollama_base_url: str = "http://localhost:11434/v1"
    gemini_model: str = "gemini-2.5-flash"
    history_window: int = 12
    references_json_path: str | None = None


# Ordered conversational filler patterns stripped outside of code blocks.
_FILLER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("could you please", re.compile(r"\bcould\s+you\s+please\b", re.IGNORECASE)),
    ("can you please", re.compile(r"\bcan\s+you\s+please\b", re.IGNORECASE)),
    ("would you please", re.compile(r"\bwould\s+you\s+please\b", re.IGNORECASE)),
    ("i would like you to", re.compile(r"\bi\s+would\s+like\s+you\s+to\b", re.IGNORECASE)),
    ("i want you to", re.compile(r"\bi\s+want\s+you\s+to\b", re.IGNORECASE)),
    ("could you", re.compile(r"\bcould\s+you\b", re.IGNORECASE)),
    ("can you", re.compile(r"\bcan\s+you\b", re.IGNORECASE)),
    ("would you", re.compile(r"\bwould\s+you\b", re.IGNORECASE)),
    ("help me to", re.compile(r"\bhelp\s+me\s+to\b", re.IGNORECASE)),
    ("help me", re.compile(r"\bhelp\s+me\b", re.IGNORECASE)),
    ("please", re.compile(r"\bplease\b[,:]?", re.IGNORECASE)),
    ("kindly", re.compile(r"\bkindly\b[,:]?", re.IGNORECASE)),
    ("for me", re.compile(r"\bfor\s+me\b", re.IGNORECASE)),
    ("hey", re.compile(r"^\s*\bhey\b[,!.]?\s*", re.IGNORECASE)),
    ("hi", re.compile(r"^\s*\bhi\b[,!.]?\s*", re.IGNORECASE)),
    ("hello", re.compile(r"^\s*\bhello\b[,!.]?\s*", re.IGNORECASE)),
    ("um", re.compile(r"\bum+\b[,:]?", re.IGNORECASE)),
    ("uh", re.compile(r"\buh+\b[,:]?", re.IGNORECASE)),
)

_CALC_PREFIX_RE = re.compile(
    r"^\s*(?:what\s+is|what's|calculate|compute|evaluate|solve)\s+(.+?)\s*\??\s*$",
    re.IGNORECASE,
)
_PURE_MATH_EXPR_RE = re.compile(
    r"^[0-9+\-*/^().%,\s_A-Za-z]+$"
)
_ALLOWED_MATH_IDENTS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "exp",
        "log",
        "log10",
        "sqrt",
        "abs",
        "pow",
        "min",
        "max",
        "pi",
        "e",
        "R_gas",
    }
)


def _looks_like_math_expression(candidate: str) -> bool:
    """Return True if candidate is a clean arithmetic/scientific expression suitable for AST eval."""
    stripped = candidate.strip()
    if not stripped or not any(ch.isdigit() for ch in stripped):
        return False
    if not _PURE_MATH_EXPR_RE.match(stripped):
        return False
    if not re.search(r"(?:[+\-*/^]|\*\*|\b(?:sqrt|sin|cos|tan|log|log10|exp|pow)\b)", stripped):
        return False
    words = re.findall(r"[A-Za-z_]+", stripped)
    return all(w in _ALLOWED_MATH_IDENTS for w in words)


def optimise_user_prompt(text: str) -> OptimisedPrompt:
    """Strip conversational filler, normalise whitespace, and predict intents in pure Python."""
    original = text
    removed_filler: list[str] = []

    lines = text.splitlines()
    processed_lines: list[str] = []
    in_fence = False

    for line in lines:
        stripped_line = line.strip()
        if stripped_line.startswith("```"):
            in_fence = not in_fence
            processed_lines.append(line.rstrip())
            continue

        if in_fence or stripped_line.startswith(("#", "|")):
            processed_lines.append(re.sub(r"[ \t]+", " ", line).strip())
            continue

        working = line
        for label, pattern in _FILLER_PATTERNS:
            if pattern.search(working):
                removed_filler.append(label)
                working = pattern.sub(" ", working)

        working = re.sub(r"[ \t]+", " ", working).strip(" ,;:")
        processed_lines.append(working)

    non_empty_lines = [ln for ln in processed_lines if ln.strip()]
    if len(non_empty_lines) == 1:
        single = non_empty_lines[0]
        calc_match = _CALC_PREFIX_RE.match(single)
        if calc_match:
            candidate_expr = calc_match.group(1).strip().rstrip("?")
            if _looks_like_math_expression(candidate_expr):
                prefix_word = single.split()[0].lower()
                removed_filler.append(prefix_word)
                single = candidate_expr
        elif single.endswith("?") and _looks_like_math_expression(single[:-1]):
            single = single[:-1].strip()
        optimised_text = single
    else:
        joined = "\n".join(processed_lines).strip()
        optimised_text = re.sub(r"\n{3,}", "\n\n", joined)

    if not optimised_text.strip():
        optimised_text = " ".join(original.split()).strip()

    dedup_filler = list(dict.fromkeys(removed_filler))

    bundle = pre_group_prompt(
        raw_text=optimised_text,
        source_id="optimiser",
        from_personal_vault=False,
    )
    detected_intents = list(dict.fromkeys(s.tag.value for s in bundle.slices))

    return OptimisedPrompt(
        original=original,
        optimised_text=optimised_text,
        removed_filler=dedup_filler,
        detected_intents=detected_intents,
    )


def suggest_conversation_title(text: str) -> str:
    """Generate a clean conversation title (<= 48 chars) in pure Python."""
    optimised = optimise_user_prompt(text).optimised_text
    candidate = ""
    for raw_line in optimised.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("```", "[/")):
            continue
        line = re.sub(
            r"^(?:\[)?#[A-Z_]+(?:\])?(?:\s*[:|-]\s*)?",
            "",
            line,
        ).strip()
        line = re.sub(r"^[#*>`\-|]+\s*", "", line).strip()
        if line:
            candidate = line
            break

    if not candidate:
        candidate = " ".join(text.split()).strip()
    if not candidate:
        return "New chat"

    candidate = re.sub(r"[`*_~]+", "", candidate)
    candidate = " ".join(candidate.split()).strip(" ?!.,;:-")
    if not candidate:
        return "New chat"

    candidate = candidate[0].upper() + candidate[1:]
    if len(candidate) <= 48:
        return candidate

    truncated = candidate[:47].rsplit(" ", 1)[0].strip()
    if len(truncated) < 16:
        truncated = candidate[:47].strip()
    return f"{truncated}…"


def _format_calc_markdown(out: CalculationSolverOutput) -> str:
    lines = [
        f"### 🧮 Calculation Result (`{out.mode}`)",
        "",
        f"- **Result:** `{out.formatted_result}`",
        f"- **Formula Applied:** `{out.formula_applied}`",
    ]
    if out.unit_conversion_factor is not None:
        lines.append(f"- **Conversion Factor:** `{out.unit_conversion_factor:.6g}`")
    if out.iterations_used > 0:
        lines.append(
            f"- **Convergence:** `{out.iterations_used}` iterations "
            f"(residual `{out.residual_error:.3e}`)"
        )
    elif out.residual_error > 0.0:
        lines.append(f"- **Residual Error:** `{out.residual_error:.3e}`")
    for warn in out.warnings:
        lines.append(f"- **Note:** {warn}")
    return "\n".join(lines)


def _format_table_markdown(out: TableHandlingOutput) -> str:
    lines = [
        f"### 📊 Table Analysis ({out.row_count} rows × {out.column_count} columns)",
        "",
        f"- **Detected Format:** `{out.detected_format}`",
        f"- **Columns:** {', '.join(f'`{h}`' for h in out.headers) if out.headers else 'None'}",
    ]
    if out.rendered_markdown.strip():
        lines.extend(["", "#### Cleaned Table", "", out.rendered_markdown.strip()])

    if out.column_stats:
        lines.extend(
            [
                "",
                "#### Column Summary Statistics",
                "",
                "| Column | Type | Non-Null | Mean | Std Dev | Min | Median | Max | Outliers |",
                "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for st in out.column_stats:
            mean_s = f"{st.mean:.4g}" if st.mean is not None else "—"
            std_s = f"{st.std_dev:.4g}" if st.std_dev is not None else "—"
            min_s = f"{st.min_val:.4g}" if st.min_val is not None else "—"
            med_s = f"{st.median_val:.4g}" if st.median_val is not None else "—"
            max_s = f"{st.max_val:.4g}" if st.max_val is not None else "—"
            lines.append(
                f"| `{st.column}` | {st.inferred_dtype} | {st.non_null_count} | "
                f"{mean_s} | {std_s} | {min_s} | {med_s} | {max_s} | "
                f"{len(st.outlier_row_indices)} |"
            )

    if out.grouped_aggregates:
        lines.extend(["", "#### Grouped Aggregates", ""])
        for grp in out.grouped_aggregates:
            means_str = ", ".join(f"{k}: {v:.4g}" for k, v in grp.numeric_means.items())
            lines.append(f"- **{grp.group_key}** ({grp.row_count} rows) — Means: {means_str}")

    for warn in out.warnings:
        lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)


def _format_comparison_markdown(out: DataComparisonOutput) -> str:
    badge = "✅ Within Tolerance" if out.all_within_tolerance else "⚠️ Tolerance Exceeded"
    lines = [
        f"### 🔍 Data Comparison (`{out.comparison_mode}`) — {badge}",
        "",
        f"**Summary:** {out.summary}",
    ]
    if out.numeric_metrics is not None:
        m = out.numeric_metrics
        mape_s = f"{m.mape_percent:.3f}%" if m.mape_percent is not None else "—"
        r_s = f"{m.pearson_r:.4f}" if m.pearson_r is not None else "—"
        r2_s = f"{m.r_squared:.4f}" if m.r_squared is not None else "—"
        lines.extend(
            [
                "",
                "| Samples | MAE | RMSE | Max Abs Error | MAPE | Pearson r | R² | Within Tol |",
                "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| {m.sample_count} | {m.mae:.5g} | {m.rmse:.5g} | {m.max_abs_error:.5g} | "
                    f"{mape_s} | {r_s} | {r2_s} | {m.within_tolerance_count}/{m.total_compared} |"
                ),
            ]
        )
    if out.field_deltas:
        lines.extend(
            [
                "",
                "#### Field Deltas",
                "",
                "| Key | Status | Baseline | Candidate | Abs Delta |",
                "| :--- | :--- | ---: | ---: | ---: |",
            ]
        )
        for delta in out.field_deltas[:15]:
            abs_d = f"{delta.abs_delta:.5g}" if delta.abs_delta is not None else "—"
            lines.append(
                f"| `{delta.key}` | `{delta.status}` | {delta.baseline_value} | "
                f"{delta.candidate_value} | {abs_d} |"
            )
    return "\n".join(lines)


def _format_pdf_convert_markdown(out: PdfConverterOutput) -> str:
    lines = [
        f"### 📄 PDF Document Extraction ({out.total_pages} pages)",
        "",
        f"- **SHA-256:** `{out.source_sha256[:16]}…`",
        f"- **Detected Equations:** `{out.detected_equations_count}`",
    ]
    if out.detected_dois:
        lines.append(f"- **Detected DOIs:** {', '.join(f'`{d}`' for d in out.detected_dois)}")
    for page in out.converted_pages[:5]:
        headings_s = (
            f" — Headings: {', '.join(page.detected_headings[:3])}"
            if page.detected_headings
            else ""
        )
        excerpt = page.extracted_text[:280].replace("\n", " ").strip()
        lines.append(
            f"- **Page {page.page_number}** ({page.word_count} words{headings_s}): {excerpt}"
        )
    for warn in out.warnings:
        lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)


def _format_smart_pdf_markdown(out: SmartPdfOutput) -> str:
    lines = [
        f"### 🔗 Smart PDF Section & Citation Index ({len(out.sections)} sections)",
        "",
    ]
    if out.top_matching_sections:
        lines.append("#### Top Ranked Sections (BM25 + $W_i$ Decay)")
        lines.append("")
        for sec in out.top_matching_sections[:5]:
            lines.append(
                f"- **{sec.heading}** (p. {sec.page_start}, "
                f"BM25=`{sec.relevance_score:.3f}`, $W_i$=`{sec.decay_weight_wi:.3f}`): "
                f"{sec.text_excerpt[:200].replace(chr(10), ' ')}"
            )
    if out.citation_keys_found:
        lines.append(
            f"\n- **Citations Found:** {', '.join(f'`{c}`' for c in out.citation_keys_found[:15])}"
        )
    if out.cross_links:
        lines.append(f"- **Cross-Reference Links Extracted:** `{len(out.cross_links)}`")
    return "\n".join(lines)


def _format_code_optimiser_markdown(out: CodingOptimiserOutput) -> str:
    gate_badge = "✅ Passed" if out.passes_qa_static_gate else "❌ Action Required"
    syntax_badge = "Valid" if out.syntax_valid else f"Syntax Error ({out.syntax_error})"
    lines = [
        f"### 🛠️ Static AST & QA Code Audit — {gate_badge}",
        "",
        f"- **Syntax:** {syntax_badge}",
        f"- **Lines of Code:** `{out.loc}`",
        f"- **Maintainability Score:** `{out.maintainability_score:.1f} / 100`",
    ]
    if out.function_metrics:
        lines.extend(
            [
                "",
                "#### Function Metrics",
                "",
                "| Function | Lines | McCabe Complexity | Max Nesting | Type Annotations |",
                "| :--- | :--- | ---: | ---: | :--- |",
            ]
        )
        for fn in out.function_metrics:
            typed_s = "✅ Complete" if fn.has_complete_type_annotations else "⚠️ Incomplete"
            lines.append(
                f"| `{fn.name}` | {fn.line_start}–{fn.line_end} | "
                f"{fn.cyclomatic_complexity} | {fn.max_nesting_depth} | {typed_s} |"
            )
    if out.findings:
        lines.extend(["", "#### Findings", ""])
        for finding in out.findings:
            hint = (
                f" *(Fix: {finding.deterministic_fix_hint})*"
                if finding.deterministic_fix_hint
                else ""
            )
            lines.append(
                f"- **[{finding.severity.upper()}] `{finding.rule_id}`** "
                f"(line {finding.line_number}): {finding.message}{hint}"
            )
    return "\n".join(lines)


def _format_control_system_markdown(out: ControlSystemOutput) -> str:
    fopdt = out.identified_fopdt
    g = out.recommended_gains
    perf = out.performance
    stable_s = "✅ Stable" if perf.is_stable else "⚠️ Unstable"
    lines = [
        f"### ⚙️ Control System & PID Tuning ({g.controller_type} — `{g.tuning_method}`)",
        "",
        (
            f"- **Identified FOPDT Model:** $K_p = {fopdt.kp:.4g}$, "
            f"$\\tau = {fopdt.tau:.4g}$, $\\theta = {fopdt.theta:.4g}$ "
            f"($\\theta/\\tau = {out.theta_over_tau:.3f}$)"
        ),
        (
            f"- **Recommended Gains:** $K_c = {g.kc:.4g}$, $\\tau_i = {g.tau_i:.4g}$, "
            f"$\\tau_d = {g.tau_d:.4g}$ ($K_i = {g.ki:.4g}$, $K_d = {g.kd:.4g}$)"
        ),
        "",
        "#### Closed-Loop Step Response Metrics",
        "",
        "| Status | IAE | ISE | ITAE | Overshoot | Rise Time | Settling Time | Steady-State Error |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {stable_s} | {perf.iae:.4g} | {perf.ise:.4g} | {perf.itae:.4g} | "
            f"{perf.overshoot_percent:.2f}% | "
            f"{f'{perf.rise_time:.4g}' if perf.rise_time is not None else '—'} | "
            f"{f'{perf.settling_time:.4g}' if perf.settling_time is not None else '—'} | "
            f"{perf.steady_state_error:.3e} |"
        ),
    ]
    for warn in out.warnings:
        lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)


def _format_research_markdown(out: ResearchToolOutput) -> str:
    lines = [
        f"### 📚 Research & Citation Gap Analysis (`{out.air_gap_status}`)",
        "",
    ]
    if out.local_matches:
        lines.append("#### Local Reference Matches")
        lines.append("")
        for m in out.local_matches[:5]:
            yr = f" ({m.year})" if m.year else ""
            doi_s = f" — DOI: `{m.doi}`" if m.doi else ""
            lines.append(f"- **{m.title}**{yr}{doi_s} *(score: {m.relevance_score:.2f})*")
    if out.external_matches:
        lines.append("")
        lines.append("#### External Reference Matches")
        lines.append("")
        for m in out.external_matches[:5]:
            yr = f" ({m.year})" if m.year else ""
            doi_s = f" — DOI: `{m.doi}`" if m.doi else ""
            lines.append(
                f"- [{m.source}] **{m.title}**{yr}{doi_s} *(score: {m.relevance_score:.2f})*"
            )
    if out.identified_gaps:
        lines.append("")
        lines.append("#### Identified Research Gaps")
        lines.append("")
        for gap in out.identified_gaps:
            queries = (
                f" — Suggested search: `{', '.join(gap.suggested_queries)}`"
                if gap.suggested_queries
                else ""
            )
            lines.append(
                f"- **[{gap.severity.upper()}] `{gap.gap_type}`**: "
                f"\"{gap.excerpt}\"{queries}"
            )
    if not out.local_matches and not out.external_matches and not out.identified_gaps:
        lines.append("- No citation gaps or unverified quantitative claims detected.")
    for warn in out.warnings:
        lines.append(f"- ⚠️ {warn}")
    return "\n".join(lines)


def format_slice_result_markdown(result: SliceExecutionResult) -> str:
    """Format a deterministic SliceExecutionResult into rich, human-readable Markdown."""
    det = result.deterministic_output
    if isinstance(det, CalculationSolverOutput):
        return _format_calc_markdown(det)
    if isinstance(det, TableHandlingOutput):
        return _format_table_markdown(det)
    if isinstance(det, DataComparisonOutput):
        return _format_comparison_markdown(det)
    if isinstance(det, PdfConverterOutput):
        return _format_pdf_convert_markdown(det)
    if isinstance(det, SmartPdfOutput):
        return _format_smart_pdf_markdown(det)
    if isinstance(det, CodingOptimiserOutput):
        return _format_code_optimiser_markdown(det)
    if isinstance(det, ControlSystemOutput):
        return _format_control_system_markdown(det)
    if isinstance(det, ResearchToolOutput):
        return _format_research_markdown(det)

    if result.error:
        return f"### ⚠️ Slice `{result.slice_id}` ({result.tag.value})\n\n- **Notice:** {result.error}"
    if result.cloud_output is not None:
        return result.cloud_output.synthesis
    if result.nano_output is not None:
        return result.nano_output.concise_answer
    if det is not None:
        summary_pairs = [
            f"- **{k}:** `{v}`"
            for k, v in det.model_dump().items()
            if k not in {"slice_id", "executed_locally", "llm_tokens_used"}
            and v not in (None, [], {}, "")
        ]
        return f"### ✅ {result.tag.value} Result\n\n" + "\n".join(summary_pairs[:10])
    return f"### ✅ {result.tag.value} (`{result.slice_id}`)"


def _summarize_deterministic_for_llm(result: SliceExecutionResult) -> str:
    """Create a compact one-line summary of a deterministic slice output for LLM context."""
    det = result.deterministic_output
    if isinstance(det, CalculationSolverOutput):
        return f"[{result.tag.value}] {det.formula_applied} => {det.formatted_result}"
    if isinstance(det, TableHandlingOutput):
        return (
            f"[{result.tag.value}] {det.row_count}x{det.column_count} table "
            f"({', '.join(det.headers[:6])})"
        )
    if isinstance(det, DataComparisonOutput):
        return f"[{result.tag.value}] {det.summary}"
    if isinstance(det, PdfConverterOutput):
        return f"[{result.tag.value}] Extracted {det.total_pages} PDF pages."
    if isinstance(det, SmartPdfOutput):
        return f"[{result.tag.value}] Indexed {len(det.sections)} PDF sections."
    if isinstance(det, CodingOptimiserOutput):
        return (
            f"[{result.tag.value}] LOC={det.loc}, score={det.maintainability_score:.1f}, "
            f"findings={len(det.findings)}"
        )
    if isinstance(det, ControlSystemOutput):
        g = det.recommended_gains
        return (
            f"[{result.tag.value}] {g.controller_type} ({g.tuning_method}): "
            f"Kc={g.kc:.4g}, tau_i={g.tau_i:.4g}, tau_d={g.tau_d:.4g}"
        )
    if isinstance(det, ResearchToolOutput):
        return (
            f"[{result.tag.value}] local_matches={len(det.local_matches)}, "
            f"gaps={len(det.identified_gaps)}"
        )
    return f"[{result.tag.value}] completed."


def _build_attachment_blocks(attachments: list[str]) -> list[str]:
    """Convert attached file paths into explicit tagged slice blocks."""
    blocks: list[str] = []
    for raw_path in attachments:
        cleaned = raw_path.strip()
        if not cleaned:
            continue
        p = Path(cleaned)
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            blocks.append(
                f'#PDF_CONVERT source_path="{p.as_posix()}"\n{p.name}\n[/#PDF_CONVERT]'
            )
        elif suffix in {".csv", ".tsv"} and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:32768]
                if content.strip():
                    fmt = "tsv" if suffix == ".tsv" else "csv"
                    blocks.append(
                        f"#TABLE_DATA format={fmt} {p.name}\n{content.strip()}\n[/#TABLE_DATA]"
                    )
            except OSError:
                pass
        elif suffix in {".py"} and p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:32768]
                if content.strip():
                    blocks.append(f"#CODE_OPTIMISE {p.name}\n{content.strip()}\n[/#CODE_OPTIMISE]")
            except OSError:
                pass
        elif p.is_file():
            try:
                content = p.read_text(encoding="utf-8", errors="replace")[:16384]
                if content.strip():
                    blocks.append(f"Attachment ({p.name}):\n{content.strip()}")
            except OSError:
                pass
    return blocks


def _build_thinking_trace_markdown(
    *,
    request: ChatTurnRequest,
    optimised: OptimisedPrompt,
    bundle: PreGroupedBundle,
    stages: list[PipelineStage],
    air_gap_enforced: bool,
) -> str:
    """Compile a structured Markdown deliberation and routing trace for the UI accordion."""
    filler_str = (
        ", ".join(f"`{f}`" for f in optimised.removed_filler)
        if optimised.removed_filler
        else "none"
    )
    lines: list[str] = [
        "#### 1. Prompt Optimisation & Intent Classification",
        f"- **Original Input:** `{optimised.original[:160]}`",
        f"- **Optimised Core:** `{optimised.optimised_text[:160]}`",
        f"- **Stripped Filler:** {filler_str}",
        (
            f"- **Predicted Intents (1,024-Param MLP):** "
            f"{', '.join(f'`{t}`' for t in optimised.detected_intents) or '`#SEMANTIC_MICRO`'}"
        ),
    ]
    if request.gem_name:
        lines.append(f"- **Active Gem Persona:** `{request.gem_name}`")
    if request.thinking_mode:
        lines.append("- **Deep Think Mode:** `Active (First-Principles Deliberation)`")

    lines.extend(
        [
            "",
            "#### 2. Isolated DataSlices & $W_i$ Context-Decay Weights",
        ]
    )
    if bundle.slices:
        for idx, s_obj in enumerate(bundle.slices):
            wi = compute_decay_weight(
                initial_weight=s_obj.priority_weight,
                decay_rate=0.05,
                elapsed_hours=0.0,
                alpha=0.15,
                resonance_count=idx,
            )
            solver_badge = (
                "Pure-Python Deterministic (0 VRAM)"
                if (s_obj.tag in DETERMINISTIC_TAGS and s_obj.can_execute_in_pure_python)
                else "Semantic / Conversational"
            )
            lines.append(
                f"- **`{s_obj.slice_id}`** (`{s_obj.tag.value}`) — "
                f"$W_i = {wi:.3f}$ | `{solver_badge}` | "
                f"`~{s_obj.estimated_tokens} tok` | privacy=`{s_obj.privacy_tier}`"
            )
    else:
        lines.append("- Single conversational turn (no multi-slice partition needed).")

    lines.extend(
        [
            "",
            "#### 3. Execution Stages & Privacy Gate",
            f"- **Air-Gap Privacy Enforced:** `{'Yes (Local-Only)' if air_gap_enforced else 'No (Sanitized)'}`",
        ]
    )
    for st in stages:
        lines.append(f"- **`{st.name}`** ({st.latency_ms:.2f} ms): {st.detail}")

    return "\n".join(lines)


def _extract_canvas_payload(
    *,
    request: ChatTurnRequest,
    bundle: PreGroupedBundle,
    answer_markdown: str,
    det_markdown_sections: list[str],
    suggested_title: str,
) -> tuple[str | None, str | None, CanvasKind]:
    """Determine if the turn output should populate the interactive Canvas workspace."""
    has_code_tag = any(s.tag == TagType.CODE_OPTIMISE for s in bundle.slices)
    has_table_tag = any(s.tag == TagType.TABLE_DATA for s in bundle.slices)
    has_pdf_or_research = any(
        s.tag in {TagType.PDF_CONVERT, TagType.SMART_PDF_LINK, TagType.RESEARCH_GAP}
        for s in bundle.slices
    )

    code_fence_match = re.search(
        r"```(?:python|py|html|markdown|md|csv|json)?\s*\n(.*?)```",
        answer_markdown,
        re.DOTALL | re.IGNORECASE,
    )
    raw_code_slice = next(
        (s.raw_payload for s in bundle.slices if s.tag == TagType.CODE_OPTIMISE),
        None,
    )

    should_open = bool(
        request.open_in_canvas
        or has_code_tag
        or has_table_tag
        or has_pdf_or_research
        or (code_fence_match is not None and len(code_fence_match.group(1).strip()) >= 40)
    )
    if not should_open:
        return None, None, "markdown"

    if has_code_tag and raw_code_slice:
        clean_code = raw_code_slice.strip()
        if clean_code.startswith("```"):
            c_lines = clean_code.splitlines()
            clean_code = "\n".join(
                c_lines[1:-1] if c_lines[-1].strip().startswith("```") else c_lines[1:]
            )
        content = f"{clean_code}\n\n# --- Audit Report ---\n" + "\n".join(det_markdown_sections)
        return f"Code Audit: {suggested_title}", content.strip(), "code"

    if code_fence_match is not None and not det_markdown_sections:
        return f"Code: {suggested_title}", code_fence_match.group(1).strip(), "code"

    if has_table_tag and det_markdown_sections:
        return f"Table: {suggested_title}", "\n\n".join(det_markdown_sections), "markdown"

    if has_pdf_or_research and det_markdown_sections:
        return f"Report: {suggested_title}", answer_markdown, "report"

    return suggested_title or "Canvas Workspace", answer_markdown, "markdown"


class StudioChatPipeline:
    """Conversational turn pipeline combining deterministic solvers, local Ollama, and Gemini."""

    def __init__(self, config: ChatPipelineConfig | None = None) -> None:
        self.config: ChatPipelineConfig = config or ChatPipelineConfig()
        self._micro_model: ThousandParamMicroModel = ThousandParamMicroModel()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_ready: threading.Event = threading.Event()
        self._state_lock: threading.Lock = threading.Lock()
        self._current_future: concurrent.futures.Future[ChatTurnResult] | None = None
        self._current_task: asyncio.Task[ChatTurnResult] | None = None

    def list_local_models(self) -> list[str]:
        """Synchronously query Ollama for installed local models; return [] if offline."""
        base = self.config.ollama_base_url.rstrip("/")
        root = base.removesuffix("/v1")
        tags_url = f"{root}/api/tags"
        v1_models_url = f"{base}/models"

        try:
            with httpx.Client(timeout=1.5) as client:
                resp = client.get(tags_url)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_models = data.get("models", []) if isinstance(data, dict) else []
                    names = [
                        str(item.get("name") or item.get("model"))
                        for item in raw_models
                        if isinstance(item, dict) and (item.get("name") or item.get("model"))
                    ]
                    if names:
                        return names

                resp_v1 = client.get(v1_models_url)
                if resp_v1.status_code == 200:
                    data_v1 = resp_v1.json()
                    raw_items = data_v1.get("data", []) if isinstance(data_v1, dict) else []
                    return [
                        str(item["id"])
                        for item in raw_items
                        if isinstance(item, dict) and "id" in item
                    ]
        except (httpx.HTTPError, ValueError, OSError):
            return []
        return []

    def cloud_available(self) -> bool:
        """Return True if GEMINI_API_KEY is configured and google-genai is importable."""
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            return False
        try:
            from google import genai as _genai  # noqa: F401
        except ImportError:
            return False
        return True

    async def _obtain_local_engine(self, model_name: str) -> LocalEngine:
        """Return the singleton LocalEngine configured for model_name, resetting if switched."""
        desired_config = LocalEngineConfig(
            provider="ollama",
            ollama_base_url=self.config.ollama_base_url,
            model_name=model_name,
            timeout_seconds=30.0,
        )
        if LocalEngine._instance is not None and LocalEngine._instance.config != desired_config:
            await LocalEngine.reset_shared()
        return LocalEngine.get_shared(desired_config)

    def _build_llm_messages(
        self,
        request: ChatTurnRequest,
        optimised_text: str,
        det_summaries: list[str],
    ) -> list[dict[str, str]]:
        """Build the compact message list for local or cloud conversational synthesis."""
        sys_parts: list[str] = [
            (
                "You are Yggdrasil, a concise, accurate scientific and engineering assistant. "
                "Respond in clear, well-structured Markdown."
            )
        ]
        if request.gem_name or request.gem_instructions.strip():
            gem_header = f"Active Gem Persona: {request.gem_name or 'Custom Specialist'}"
            if request.gem_instructions.strip():
                gem_header += f"\nGem Instructions:\n{request.gem_instructions.strip()}"
            sys_parts.append(gem_header)

        if request.thinking_mode:
            sys_parts.append(
                "Deep Think Mode: Structure your response with explicit first-principles "
                "assumptions, governing equations, and step-by-step verification."
            )

        if request.project is not None:
            if request.project.name:
                sys_parts.append(f"Active Project: {request.project.name}")
            if request.project.instructions.strip():
                sys_parts.append(
                    f"Project Instructions:\n{request.project.instructions.strip()}"
                )
            if request.project.pinned_notes:
                notes_joined = "\n".join(
                    f"- {note.strip()}" for note in request.project.pinned_notes if note.strip()
                )
                if notes_joined:
                    sys_parts.append(f"Pinned Project Notes:\n{notes_joined}")

        if det_summaries:
            sys_parts.append(
                "Deterministic Tool Outputs Already Computed (incorporate seamlessly, do not repeat raw dumps):\n"
                + "\n".join(f"- {s}" for s in det_summaries)
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": "\n\n".join(sys_parts)}
        ]
        window = max(0, self.config.history_window)
        recent = request.history[-window:] if window > 0 else []
        for msg in recent:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": optimised_text or request.user_text})
        return messages

    async def run_turn(
        self,
        request: ChatTurnRequest,
        on_token: Callable[[str], None] | None = None,
    ) -> ChatTurnResult:
        """Execute a complete conversational turn following SPEC-004 Section 2.1."""
        stages: list[PipelineStage] = []
        suggested_title = suggest_conversation_title(request.user_text)

        # 1. Optimise prompt (pure Python, 0 LLM tokens)
        t0 = time.perf_counter()
        optimised = optimise_user_prompt(request.user_text)
        opt_ms = (time.perf_counter() - t0) * 1000.0
        filler_note = (
            f"stripped {len(optimised.removed_filler)} filler token(s)"
            if optimised.removed_filler
            else "clean input"
        )
        stages.append(
            PipelineStage(
                name="optimise",
                detail=f"Optimised prompt ({filler_note})",
                latency_ms=opt_ms,
            )
        )

        # 2. Tag & slice (with attachments + project air-gap propagation)
        t_tag = time.perf_counter()
        project_air_gapped = bool(request.project and request.project.air_gapped)
        attachment_blocks = _build_attachment_blocks(request.attachments)
        combined_input = optimised.optimised_text
        if attachment_blocks:
            combined_input = f"{combined_input}\n\n" + "\n\n".join(attachment_blocks)

        bundle = pre_group_prompt(
            raw_text=combined_input,
            source_id=request.turn_id,
            from_personal_vault=project_air_gapped,
            micro_model=self._micro_model,
        )
        tags_detected = list(dict.fromkeys(s.tag.value for s in bundle.slices))
        tag_ms = (time.perf_counter() - t_tag) * 1000.0
        stages.append(
            PipelineStage(
                name="tag",
                detail=(
                    f"Sliced into {len(bundle.slices)} block(s): "
                    f"{', '.join(tags_detected) if tags_detected else 'none'}"
                ),
                latency_ms=tag_ms,
            )
        )

        # Check air-gap taint across project, request flags, history, and bundle
        history_tainted = any(
            contains_pii_or_vault_taint(m.content) for m in request.history
        )
        notes_tainted = bool(
            request.project
            and (
                contains_pii_or_vault_taint(request.project.instructions)
                or any(contains_pii_or_vault_taint(n) for n in request.project.pinned_notes)
            )
        )
        air_gap_enforced = bool(
            request.local_only
            or project_air_gapped
            or bundle.contains_personal_vault_data
            or history_tainted
            or notes_tainted
        )

        # Deep Research Mode (SPEC-005 Section 2.1 / 2.2): multi-step cited investigation into Canvas
        if request.deep_research:
            t_dr = time.perf_counter()
            from .agy_bridge import AgyBridgeConfig, AgySdkBridge

            dr_bridge = AgySdkBridge(
                AgyBridgeConfig(
                    backend_mode="local_openai",
                    model_name=self.config.default_local_model,
                    base_url=self.config.ollama_base_url,
                    system_instructions=request.gem_instructions,
                )
            )
            proj_inst = request.project.instructions if request.project is not None else ""
            dr_report = await dr_bridge.run_deep_research(
                request.user_text,
                project_instructions=proj_inst,
                air_gapped=air_gap_enforced,
            )
            dr_ms = (time.perf_counter() - t_dr) * 1000.0
            stages.append(
                PipelineStage(
                    name="deep_research",
                    detail=(
                        f"Compiled {len(dr_report.sections)} sections & "
                        f"{len(dr_report.verified_references)} verified reference(s)"
                    ),
                    latency_ms=dr_ms,
                )
            )
            plan_md = "\n".join(f"- {step}" for step in dr_report.investigation_plan)
            refs_md = "\n".join(f"- {ref}" for ref in dr_report.verified_references)
            summary_md = (
                f"### 🔬 {dr_report.title}\n\n"
                "I have completed a multi-step **Deep Research** investigation and opened the "
                "full interactive report in the **Canvas** panel on the right.\n\n"
                f"#### Investigation Plan Executed\n{plan_md}\n\n"
                f"#### Verified References ({len(dr_report.verified_references)})\n{refs_md}"
            )
            if dr_report.deterministic_findings:
                summary_md += "\n\n#### Deterministic Findings\n\n" + "\n\n".join(
                    dr_report.deterministic_findings
                )
            if on_token is not None:
                on_token(summary_md)

            stages.append(
                PipelineStage(
                    name="compose",
                    detail=(
                        f"Composed Deep Research report ({len(dr_report.markdown_document)} chars)"
                    ),
                    latency_ms=0.1,
                )
            )
            thinking_md = _build_thinking_trace_markdown(
                request=request,
                optimised=optimised,
                bundle=bundle,
                stages=stages,
                air_gap_enforced=dr_report.air_gap_enforced,
            )
            return ChatTurnResult(
                turn_id=request.turn_id,
                answer_markdown=summary_md,
                route="deterministic",
                model_used="agy-deep-research",
                tags_detected=tags_detected,
                stages=stages,
                deterministic_hits=max(1, len(dr_report.deterministic_findings)),
                llm_tokens_used=0,
                air_gap_enforced=dr_report.air_gap_enforced,
                suggested_title=suggested_title,
                error=None,
                thinking_trace_markdown=thinking_md,
                canvas_title=dr_report.title,
                canvas_content=dr_report.markdown_document,
                canvas_kind="report",
                citations=list(dr_report.verified_references),
            )

        # 3. Deterministic execution for eligible slices
        det_slices: list[DataSlice] = [
            s
            for s in bundle.slices
            if s.tag in DETERMINISTIC_TAGS and s.can_execute_in_pure_python
        ]
        det_markdown_sections: list[str] = []
        det_summaries: list[str] = []
        deterministic_hits = 0

        if det_slices:
            t_det = time.perf_counter()
            det_bundle = PreGroupedBundle(
                bundle_id=f"{bundle.bundle_id}-det",
                source_id=bundle.source_id,
                from_personal_vault=bundle.from_personal_vault,
                total_input_chars=sum(len(s.raw_payload) for s in det_slices),
                slices=det_slices,
                untagged_remainder="",
                contains_personal_vault_data=bundle.contains_personal_vault_data,
            )
            orchestrator = NestedModelOrchestrator(
                config=OrchestratorConfig(
                    allow_cloud_synthesis=False,
                    allow_external_research=False,
                    references_json_path=self.config.references_json_path,
                ),
                micro_model=self._micro_model,
            )
            for s_obj in det_bundle.slices:
                t_s = time.perf_counter()
                try:
                    det_out = await orchestrator._execute_deterministic_slice(
                        s_obj, local_references=None
                    )
                    res = SliceExecutionResult(
                        slice_id=s_obj.slice_id,
                        tag=s_obj.tag,
                        execution_tier="deterministic_python",
                        weight_wi=1.0,
                        deterministic_output=det_out,
                        llm_tokens_used=0,
                        latency_ms=(time.perf_counter() - t_s) * 1000.0,
                    )
                    md_sec = format_slice_result_markdown(res)
                    det_markdown_sections.append(md_sec)
                    det_summaries.append(_summarize_deterministic_for_llm(res))
                    deterministic_hits += 1
                    if on_token is not None:
                        on_token(md_sec + "\n\n")
                except Exception as exc:  # noqa: BLE001
                    stages.append(
                        PipelineStage(
                            name="deterministic",
                            detail=f"Slice {s_obj.tag.value} fallback ({exc})",
                            latency_ms=(time.perf_counter() - t_s) * 1000.0,
                        )
                    )

            det_ms = (time.perf_counter() - t_det) * 1000.0
            if deterministic_hits > 0:
                stages.append(
                    PipelineStage(
                        name="deterministic",
                        detail=f"Solved {deterministic_hits} slice(s) in pure Python (0 tokens)",
                        latency_ms=det_ms,
                    )
                )

        # Determine if an LLM conversational call is required
        has_non_det_slice = any(
            s.tag not in DETERMINISTIC_TAGS or not s.can_execute_in_pure_python
            for s in bundle.slices
        )
        has_untagged_rem = bool(bundle.untagged_remainder.strip())
        needs_llm = (deterministic_hits == 0) or has_non_det_slice or has_untagged_rem

        llm_text_chunks: list[str] = []
        llm_tokens_used = 0
        model_used: str | None = None
        route: TurnRoute = "deterministic"
        error_msg: str | None = None

        # 4. Converse (at most ONE LLM call, cloud or local)
        if needs_llm:
            wants_cloud = request.model_choice == "gemini-cloud" or (
                request.model_choice == "auto"
                and self.cloud_available()
                and not air_gap_enforced
            )

            if wants_cloud and air_gap_enforced:
                stages.append(
                    PipelineStage(
                        name="cloud",
                        detail="Blocked cloud dispatch (air-gap / local-only policy enforced)",
                        latency_ms=0.0,
                    )
                )

            can_use_cloud = wants_cloud and not air_gap_enforced and self.cloud_available()

            if can_use_cloud:
                t_cloud = time.perf_counter()
                try:
                    sanitized_ctx: list[str] = []
                    if request.project is not None and not request.project.air_gapped:
                        if request.project.instructions.strip():
                            sanitized_ctx.append(
                                f"Project Instructions: {request.project.instructions.strip()}"
                            )
                        for note in request.project.pinned_notes:
                            if note.strip():
                                sanitized_ctx.append(f"Pinned Note: {note.strip()}")
                    sanitized_ctx.extend(det_summaries)

                    cloud_req = SanitizedCloudRequest(
                        request_id=request.turn_id,
                        prompt=optimised.optimised_text or request.user_text,
                        sanitized_context=sanitized_ctx,
                        contains_personal_vault_data=False,
                        air_gap_cleared_by="studio_chat_pipeline",
                    )
                    leaves = LeavesCloudAgent(model_name=self.config.gemini_model)
                    window = max(0, self.config.history_window)
                    recent_hist = request.history[-window:] if window > 0 else []
                    async for token in leaves.stream_chat(cloud_req, history=recent_hist):
                        llm_text_chunks.append(token)
                        if on_token is not None:
                            on_token(token)

                    cloud_text = "".join(llm_text_chunks).strip()
                    llm_tokens_used = max(
                        1,
                        math.ceil((len(cloud_req.prompt) + len(cloud_text)) / 4),
                    )
                    model_used = self.config.gemini_model
                    route = "mixed" if deterministic_hits > 0 else "cloud"
                    stages.append(
                        PipelineStage(
                            name="cloud",
                            detail=f"Streamed Gemini synthesis ({self.config.gemini_model})",
                            latency_ms=(time.perf_counter() - t_cloud) * 1000.0,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    error_msg = str(exc)
                    stages.append(
                        PipelineStage(
                            name="cloud",
                            detail=f"Cloud stream error ({exc}); falling back to local",
                            latency_ms=(time.perf_counter() - t_cloud) * 1000.0,
                        )
                    )
                    can_use_cloud = False

            if not can_use_cloud:
                t_local = time.perf_counter()
                local_model = (
                    request.model_choice
                    if request.model_choice not in {"auto", "gemini-cloud", ""}
                    else self.config.default_local_model
                )
                messages = self._build_llm_messages(
                    request=request,
                    optimised_text=optimised.optimised_text,
                    det_summaries=det_summaries,
                )
                try:
                    engine = await self._obtain_local_engine(local_model)
                    async for token in engine.stream_chat(messages, model_name=local_model):
                        llm_text_chunks.append(token)
                        if on_token is not None:
                            on_token(token)

                    local_text = "".join(llm_text_chunks).strip()
                    prompt_chars = sum(len(m.get("content", "")) for m in messages)
                    llm_tokens_used = max(1, math.ceil((prompt_chars + len(local_text)) / 4))
                    model_used = local_model
                    route = "mixed" if deterministic_hits > 0 else "local_llm"
                    stages.append(
                        PipelineStage(
                            name="local_llm",
                            detail=f"Streamed local model ({local_model})",
                            latency_ms=(time.perf_counter() - t_local) * 1000.0,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    error_msg = str(exc)
                    stages.append(
                        PipelineStage(
                            name="local_llm",
                            detail=f"Local model unreachable ({local_model}): {exc}",
                            latency_ms=(time.perf_counter() - t_local) * 1000.0,
                        )
                    )
                    if deterministic_hits > 0:
                        route = "deterministic"
                    else:
                        route = "offline_fallback"
                        fallback_md = (
                            "### ⚡ Yggdrasil Offline Mode\n\n"
                            f"The local inference server at `{self.config.ollama_base_url}` "
                            f"(model `{local_model}`) is currently unreachable.\n\n"
                            "**How to enable full conversational synthesis:**\n"
                            "1. Start Ollama in a terminal: `ollama serve`\n"
                            f"2. Pull the default lightweight model: `ollama pull {local_model}`\n\n"
                            "**Available immediately without an LLM (0 tokens):**\n"
                            "- **Calculations & Units:** e.g. `Calculate 12.5 * sqrt(144)` or `#CALC_SOLVE`\n"
                            "- **Table Analytics:** paste CSV/Markdown tables or `#TABLE_DATA`\n"
                            "- **Code Audit:** paste Python code or `#CODE_OPTIMISE`\n"
                            "- **PID Control Tuning:** `#CONTROL_SYSTEM kp=2.0 tau=10.0 theta=1.5`\n"
                            "- **PDF Extraction & Indexing:** attach a `.pdf` file or `#PDF_CONVERT`"
                        )
                        llm_text_chunks.append(fallback_md)
                        if on_token is not None:
                            on_token(fallback_md)

        # 5. Compose final Markdown response
        t_comp = time.perf_counter()
        llm_answer = "".join(llm_text_chunks).strip()
        composed_parts: list[str] = []
        if det_markdown_sections:
            composed_parts.append("\n\n".join(det_markdown_sections))
        if llm_answer:
            composed_parts.append(llm_answer)

        answer_markdown = "\n\n".join(composed_parts).strip()
        if not answer_markdown:
            answer_markdown = "No output generated for this turn."

        stages.append(
            PipelineStage(
                name="compose",
                detail=f"Composed answer ({len(answer_markdown)} chars, route={route})",
                latency_ms=(time.perf_counter() - t_comp) * 1000.0,
            )
        )

        thinking_trace_md = _build_thinking_trace_markdown(
            request=request,
            optimised=optimised,
            bundle=bundle,
            stages=stages,
            air_gap_enforced=air_gap_enforced,
        )
        canvas_title, canvas_content, canvas_kind = _extract_canvas_payload(
            request=request,
            bundle=bundle,
            answer_markdown=answer_markdown,
            det_markdown_sections=det_markdown_sections,
            suggested_title=suggested_title,
        )

        return ChatTurnResult(
            turn_id=request.turn_id,
            answer_markdown=answer_markdown,
            route=route,
            model_used=model_used,
            tags_detected=tags_detected,
            stages=stages,
            deterministic_hits=deterministic_hits,
            llm_tokens_used=llm_tokens_used,
            air_gap_enforced=air_gap_enforced,
            suggested_title=suggested_title,
            error=error_msg,
            thinking_trace_markdown=thinking_trace_md,
            canvas_title=canvas_title,
            canvas_content=canvas_content,
            canvas_kind=canvas_kind,
            citations=[],
        )

    def _run_background_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        self._loop_ready.set()
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()

    def start(self) -> None:
        """Start the single background asyncio event loop thread if not already running."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive() and self._loop is not None:
                return
            self._loop_ready.clear()
            loop = asyncio.new_event_loop()
            self._loop = loop
            thread = threading.Thread(
                target=self._run_background_loop,
                args=(loop,),
                name="YggdrasilStudioChatLoop",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        self._loop_ready.wait(timeout=5.0)

    def submit(
        self,
        request: ChatTurnRequest,
        on_token: Callable[[str], None] | None = None,
    ) -> concurrent.futures.Future[ChatTurnResult]:
        """Submit a turn to the persistent background event loop and return a thread-safe Future."""
        self.start()
        assert self._loop is not None

        async def _tracked_turn() -> ChatTurnResult:
            task = asyncio.current_task()
            with self._state_lock:
                self._current_task = task
            try:
                return await self.run_turn(request, on_token=on_token)
            finally:
                with self._state_lock:
                    if self._current_task is task:
                        self._current_task = None

        future: concurrent.futures.Future[ChatTurnResult] = asyncio.run_coroutine_threadsafe(
            _tracked_turn(),
            self._loop,
        )
        with self._state_lock:
            self._current_future = future
        return future

    def cancel_current(self) -> None:
        """Cancel the currently executing turn on the background loop, if any."""
        with self._state_lock:
            fut = self._current_future
            task = self._current_task
            loop = self._loop

        if fut is not None and not fut.done():
            fut.cancel()
        if loop is not None and task is not None and not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)

    def shutdown(self) -> None:
        """Cancel any active turn and cleanly stop the background asyncio thread."""
        self.cancel_current()
        with self._state_lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
            self._current_future = None
            self._current_task = None

        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
