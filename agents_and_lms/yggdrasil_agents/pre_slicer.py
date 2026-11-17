"""Zero-token deterministic pre-grouped tag slicer and taint propagator (SPEC-001)."""

from __future__ import annotations

import ast
import hashlib
import math
import re
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from .roots import PrivacyTier

if TYPE_CHECKING:
    from .micro_model import ThousandParamMicroModel


class TagType(str, Enum):
    """Supported pre-grouped task classification tags from SPEC-001 Section 3.1."""

    TABLE_DATA = "#TABLE_DATA"
    CALC_SOLVE = "#CALC_SOLVE"
    DATA_COMPARE = "#DATA_COMPARE"
    PDF_CONVERT = "#PDF_CONVERT"
    SMART_PDF_LINK = "#SMART_PDF_LINK"
    CODE_OPTIMISE = "#CODE_OPTIMISE"
    CONTROL_SYSTEM = "#CONTROL_SYSTEM"
    RESEARCH_GAP = "#RESEARCH_GAP"
    SEMANTIC_MICRO = "#SEMANTIC_MICRO"
    GENERAL_SYNTHESIS = "#GENERAL_SYNTHESIS"


DETERMINISTIC_TAGS: frozenset[TagType] = frozenset(
    {
        TagType.TABLE_DATA,
        TagType.CALC_SOLVE,
        TagType.DATA_COMPARE,
        TagType.PDF_CONVERT,
        TagType.SMART_PDF_LINK,
        TagType.CODE_OPTIMISE,
        TagType.CONTROL_SYSTEM,
        TagType.RESEARCH_GAP,
    }
)

StructuredValue = str | float | int | bool | list[str]

# Exact SPEC-001 Section 3.3 header regex.
_TAG_HEADER_RE = re.compile(
    r"^(?:\[)?(#(?:TABLE_DATA|CALC_SOLVE|DATA_COMPARE|PDF_CONVERT|"
    r"SMART_PDF_LINK|CODE_OPTIMISE|CONTROL_SYSTEM|RESEARCH_GAP|"
    r"SEMANTIC_MICRO|GENERAL_SYNTHESIS))(?:\])?(?:\s*[:|-]\s*(.*))?$"
)

_TAG_CLOSE_RE = re.compile(
    r"^\[/(#(?:TABLE_DATA|CALC_SOLVE|DATA_COMPARE|PDF_CONVERT|"
    r"SMART_PDF_LINK|CODE_OPTIMISE|CONTROL_SYSTEM|RESEARCH_GAP|"
    r"SEMANTIC_MICRO|GENERAL_SYNTHESIS|TAG))\]$"
)

_KV_TOKEN_RE = re.compile(
    r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)="
    r'("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|\[[^\]]*\]|\S+)'
)

_MD_HEADING_RE = re.compile(r"^#{2,6}\s+(.+)$")
_FENCE_RE = re.compile(r"^\s*```")
_PIPE_TABLE_ROW_RE = re.compile(r"^\s*\|.+\|\s*$")
_INT_RE = re.compile(r"^[+-]?\d+$")

# Deterministic lexical PII / vault taint patterns (SPEC-001 Section 3.3.3).
_TAINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bpersonal_vault(?:\.db)?\b", re.IGNORECASE),
    re.compile(r"privacy_tier\s*[:=]\s*['\"]?air_gapped['\"]?", re.IGNORECASE),
    re.compile(r"contains_personal_vault_data\s*[:=]\s*true\b", re.IGNORECASE),
    re.compile(r"\bair_gapped\b"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b(?:password|passwd|api_key|apikey|secret_key|access_token|private_key|secret)\b"
        r"\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\bSSN\b\s*[:=#]?\s*\d", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)

_CALC_MODES = frozenset(
    {
        "evaluate_expression",
        "unit_convert",
        "ideal_gas",
        "arrhenius",
        "reynolds_number",
        "antoine_vapor_pressure",
        "newton_root",
        "simpson_integrate",
    }
)


class DataSlice(BaseModel):
    """Strictly scoped single-topic slice partitioned from raw input."""

    slice_id: str = Field(min_length=1)
    tag: TagType
    title: str = ""
    raw_payload: str = Field(min_length=1)
    structured_kv: dict[str, StructuredValue] = Field(default_factory=dict)
    byte_size: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=1, ge=1)
    can_execute_in_pure_python: bool = False
    contains_personal_vault_data: bool = True
    privacy_tier: PrivacyTier = "air_gapped"
    source_span: tuple[int, int] = (0, 0)
    priority_weight: float = Field(default=1.0, ge=0.0)

    @model_validator(mode="before")
    @classmethod
    def _populate_derived_sizes(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw = data.get("raw_payload")
            if isinstance(raw, str) and raw:
                updated = dict(data)
                if "byte_size" not in updated:
                    updated["byte_size"] = len(raw.encode("utf-8"))
                if "estimated_tokens" not in updated:
                    updated["estimated_tokens"] = max(1, math.ceil(len(raw) / 4))
                return updated
        return data

    @field_validator("source_span")
    @classmethod
    def _validate_source_span(cls, value: tuple[int, int]) -> tuple[int, int]:
        start, end = value
        if start < 0 or end < start:
            raise ValueError(f"source_span must satisfy 0 <= start <= end, got {value}.")
        return value

    @model_validator(mode="after")
    def _enforce_air_gap_invariant(self) -> DataSlice:
        if self.contains_personal_vault_data and self.privacy_tier != "air_gapped":
            raise ValueError("Air-gapped vault data cannot carry privacy_tier='sanitized'.")
        return self


class PreGroupedBundle(BaseModel):
    """Zero-token pre-sliced bundle of isolated DataSlices."""

    bundle_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    from_personal_vault: bool = True
    total_input_chars: int = Field(ge=0)
    slices: list[DataSlice] = Field(default_factory=list)
    untagged_remainder: str = ""
    tag_index: dict[TagType, list[str]] = Field(default_factory=dict)
    contains_personal_vault_data: bool = True
    token_savings_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    slicing_latency_ms: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _finalize_bundle_invariants(self) -> PreGroupedBundle:
        if self.slices and not self.tag_index:
            index: dict[TagType, list[str]] = {}
            for item in self.slices:
                index.setdefault(item.tag, []).append(item.slice_id)
            self.tag_index = index
        if self.from_personal_vault or any(s.contains_personal_vault_data for s in self.slices):
            self.contains_personal_vault_data = True
        return self


def contains_pii_or_vault_taint(text: str) -> bool:
    """Return True if deterministic lexical PII or vault markers appear in text."""
    return any(pattern.search(text) is not None for pattern in _TAINT_PATTERNS)


def _coerce_kv_value(raw_val: str) -> StructuredValue:
    """Coerce an inline header key=value literal deterministically."""
    if (raw_val.startswith('"') and raw_val.endswith('"')) or (
        raw_val.startswith("'") and raw_val.endswith("'")
    ):
        return raw_val[1:-1]
    if raw_val.startswith("[") and raw_val.endswith("]"):
        inner = raw_val[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("\"'") for part in inner.split(",") if part.strip()]
    lowered = raw_val.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if _INT_RE.match(raw_val):
        return int(raw_val)
    try:
        parsed_float = float(raw_val)
        if math.isfinite(parsed_float):
            return parsed_float
    except ValueError:
        pass
    return raw_val


def _parse_header_tail(tail: str | None) -> tuple[str, dict[str, StructuredValue]]:
    """Extract inline key=value directives and remaining clean title from header tail."""
    if not tail:
        return "", {}
    kv: dict[str, StructuredValue] = {}
    title_chunks: list[str] = []
    cursor = 0
    for match in _KV_TOKEN_RE.finditer(tail):
        start, end = match.span()
        if start > cursor:
            title_chunks.append(tail[cursor:start])
        key = match.group(1)
        raw_val = match.group(2)
        kv[key] = _coerce_kv_value(raw_val)
        cursor = end
    if cursor < len(tail):
        title_chunks.append(tail[cursor:])
    title = " ".join(" ".join(title_chunks).split()).strip(" -:|")
    return title, kv


def _strip_code_fences(text: str) -> str:
    """Remove optional outer Markdown code fences for Python AST inspection."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def _check_table_preconditions(raw_payload: str, structured_kv: dict[str, StructuredValue]) -> bool:
    fmt = structured_kv.get("format") or structured_kv.get("input_format")
    if fmt in {"csv", "tsv", "markdown", "json_records"}:
        return True
    stripped = raw_payload.strip()
    if stripped.startswith("[") and stripped.endswith("]") and "{" in stripped:
        return True
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    for delim in ("|", "\t", ","):
        counts = [ln.count(delim) for ln in lines[:6]]
        min_needed = 2 if delim == "|" else 1
        if all(c >= min_needed for c in counts) and len(set(counts[:3])) <= 2:
            return True
    return False


def _check_calc_preconditions(raw_payload: str, structured_kv: dict[str, StructuredValue]) -> bool:
    mode = structured_kv.get("mode")
    if isinstance(mode, str) and mode in _CALC_MODES:
        return True
    has_digit = any(ch.isdigit() for ch in raw_payload)
    if not has_digit and not any(isinstance(v, (int, float)) for v in structured_kv.values()):
        return False
    return bool(
        re.search(
            r"(?:[=+\-*/^]|\*\*|\b(?:exp|log|log10|sqrt|sin|cos|tan|convert|to|"
            r"mol|kJ|Pa|kPa|bar|atm|mmHg|kelvin|celsius|arrhenius|reynolds|ideal_gas|"
            r"antoine|newton|simpson)\b)",
            raw_payload,
            re.IGNORECASE,
        )
    )


def _check_compare_preconditions(
    raw_payload: str, structured_kv: dict[str, StructuredValue]
) -> bool:
    if "comparison_mode" in structured_kv:
        return True
    nums = re.findall(r"[-+]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", raw_payload)
    has_pair_cue = bool(
        re.search(
            r"\b(?:baseline|candidate|vs|delta|rmse|mae|mape|compare|diff)\b|=",
            raw_payload,
            re.IGNORECASE,
        )
    )
    return len(nums) >= 2 or (has_pair_cue and len(raw_payload.splitlines()) >= 2)


def _check_pdf_convert_preconditions(
    raw_payload: str, structured_kv: dict[str, StructuredValue]
) -> bool:
    if "source_path" in structured_kv:
        src = str(structured_kv["source_path"])
        return not src.lower().startswith(("http://", "https://"))
    lower = raw_payload.lower()
    if (
        ("http://" in lower or "https://" in lower)
        and ".pdf" in lower
        and "page " not in lower
        and "\n" not in raw_payload.strip()
    ):
        return False
    return bool(
        ".pdf" in lower
        or "page " in lower
        or "%pdf" in lower
        or "-\n" in raw_payload
        or "-\r\n" in raw_payload
        or "\n" in raw_payload.strip()
    )


def _check_code_preconditions(raw_payload: str) -> bool:
    code = _strip_code_fences(raw_payload)
    try:
        tree = ast.parse(code, mode="exec")
        if not tree.body:
            return False
        # Require at least one genuine Python statement structure beyond bare word prose.
        return any(
            isinstance(
                node,
                (
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                    ast.Import,
                    ast.ImportFrom,
                    ast.Assign,
                    ast.AugAssign,
                    ast.AnnAssign,
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                    ast.If,
                    ast.With,
                    ast.AsyncWith,
                    ast.Return,
                    ast.Try,
                ),
            )
            for node in tree.body
        )
    except SyntaxError:
        # Allow syntactically broken Python code to reach coding_optimiser_function so it
        # deterministically reports syntax_valid=False and syntax_error without an LLM call.
        return bool(
            re.search(r"\b(?:def|async\s+def|class|import|from|return)\b", code)
        )


def _check_control_preconditions(
    raw_payload: str, structured_kv: dict[str, StructuredValue]
) -> bool:
    if any(k in structured_kv for k in ("kp", "tau", "theta", "step_test_times")):
        return True
    has_digit = any(ch.isdigit() for ch in raw_payload)
    has_ctrl_kw = bool(
        re.search(
            r"\b(?:fopdt|pid|pi|imc|simc|ziegler|cohen|kp|tau|theta|iae|ise|itae|"
            r"step_test|setpoint|overshoot)\b",
            raw_payload,
            re.IGNORECASE,
        )
    )
    return has_digit and has_ctrl_kw


def _check_pure_python_preconditions(
    tag: TagType,
    raw_payload: str,
    structured_kv: dict[str, StructuredValue],
) -> bool:
    """Return True iff tag is deterministic and payload satisfies structural preconditions."""
    if tag not in DETERMINISTIC_TAGS or not raw_payload.strip():
        return False
    if tag == TagType.TABLE_DATA:
        return _check_table_preconditions(raw_payload, structured_kv)
    if tag == TagType.CALC_SOLVE:
        return _check_calc_preconditions(raw_payload, structured_kv)
    if tag == TagType.DATA_COMPARE:
        return _check_compare_preconditions(raw_payload, structured_kv)
    if tag == TagType.PDF_CONVERT:
        return _check_pdf_convert_preconditions(raw_payload, structured_kv)
    if tag == TagType.SMART_PDF_LINK:
        return len(raw_payload.strip()) >= 12
    if tag == TagType.CODE_OPTIMISE:
        return _check_code_preconditions(raw_payload)
    if tag == TagType.CONTROL_SYSTEM:
        return _check_control_preconditions(raw_payload, structured_kv)
    if tag == TagType.RESEARCH_GAP:
        return len(raw_payload.strip()) >= 10
    return False


def _split_untagged_blocks(raw_text: str) -> list[tuple[str, str, int, int]]:
    """Split untagged text into (title, block_text, start, end) candidate blocks in O(N)."""
    blocks: list[tuple[str, str, int, int]] = []
    cur_lines: list[str] = []
    cur_title = ""
    cur_start: int | None = None
    cur_end = 0
    in_fence = False
    in_pipe_table = False

    def flush() -> None:
        nonlocal cur_lines, cur_title, cur_start, cur_end
        if cur_lines and cur_start is not None:
            joined = "".join(cur_lines).strip("\r\n")
            if joined.strip():
                blocks.append((cur_title, joined, cur_start, cur_end))
        cur_lines = []
        cur_title = ""
        cur_start = None

    offset = 0
    for line in raw_text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        line_end = offset
        stripped = line.rstrip("\r\n")

        if in_fence:
            cur_lines.append(line)
            cur_end = line_end
            if _FENCE_RE.match(stripped):
                in_fence = False
                flush()
            continue

        if _FENCE_RE.match(stripped):
            in_pipe_table = False
            flush()
            in_fence = True
            cur_start = line_start
            cur_end = line_end
            cur_lines.append(line)
            continue

        heading_match = _MD_HEADING_RE.match(stripped.strip())
        if heading_match:
            in_pipe_table = False
            flush()
            cur_title = heading_match.group(1).strip()
            cur_start = line_start
            cur_end = line_end
            cur_lines.append(line)
            continue

        is_pipe = bool(_PIPE_TABLE_ROW_RE.match(stripped))
        if is_pipe and not in_pipe_table:
            if cur_lines and any(ln.strip() for ln in cur_lines):
                # Flush preceding narrative before table block unless only a heading precedes it.
                non_heading = [
                    ln for ln in cur_lines if not _MD_HEADING_RE.match(ln.strip()) and ln.strip()
                ]
                if non_heading:
                    flush()
            in_pipe_table = True
        elif in_pipe_table and not is_pipe and stripped.strip():
            flush()
            in_pipe_table = False

        if cur_start is None:
            cur_start = line_start
        cur_lines.append(line)
        cur_end = line_end

    flush()
    return blocks


def _build_slice(
    *,
    bundle_id: str,
    index: int,
    tag: TagType,
    title: str,
    raw_payload: str,
    structured_kv: dict[str, StructuredValue],
    source_span: tuple[int, int],
    tainted: bool,
) -> DataSlice:
    privacy_tier: PrivacyTier = "air_gapped" if tainted else "sanitized"
    can_pure_python = _check_pure_python_preconditions(tag, raw_payload, structured_kv)
    return DataSlice(
        slice_id=f"{bundle_id}-s{index}",
        tag=tag,
        title=title,
        raw_payload=raw_payload,
        structured_kv=structured_kv,
        byte_size=len(raw_payload.encode("utf-8")),
        estimated_tokens=max(1, math.ceil(len(raw_payload) / 4)),
        can_execute_in_pure_python=can_pure_python,
        contains_personal_vault_data=tainted,
        privacy_tier=privacy_tier,
        source_span=source_span,
    )


def pre_group_prompt(
    raw_text: str,
    source_id: str = "prompt",
    bundle_id: str | None = None,
    from_personal_vault: bool = True,
    micro_model: ThousandParamMicroModel | None = None,
) -> PreGroupedBundle:
    """Partition raw text into isolated DataSlices using zero-LLM delimiter scanning."""
    t_start = time.perf_counter()
    total_chars = len(raw_text)
    resolved_bundle_id = bundle_id or (
        f"bundle-{hashlib.blake2b(f'{source_id}:{raw_text}'.encode(), digest_size=6).hexdigest()}"
    )
    tainted = bool(
        from_personal_vault
        or contains_pii_or_vault_taint(source_id)
        or contains_pii_or_vault_taint(raw_text)
    )

    if not raw_text.strip():
        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return PreGroupedBundle(
            bundle_id=resolved_bundle_id,
            source_id=source_id,
            from_personal_vault=from_personal_vault,
            total_input_chars=total_chars,
            slices=[],
            untagged_remainder=raw_text,
            tag_index={},
            contains_personal_vault_data=tainted,
            token_savings_ratio=0.0,
            slicing_latency_ms=latency_ms,
        )

    # Single-pass O(N) delimiter scanner for explicit #TAG headers and closing markers.
    explicit_records: list[
        tuple[TagType, str, dict[str, StructuredValue], list[str], int, int, str]
    ] = []
    untagged_chunks: list[str] = []

    active_tag: TagType | None = None
    active_title = ""
    active_kv: dict[str, StructuredValue] = {}
    active_lines: list[str] = []
    active_start = 0
    active_end = 0
    active_tail = ""

    def finalize_explicit() -> None:
        nonlocal active_tag, active_title, active_kv, active_lines, active_start, active_end, active_tail
        if active_tag is None:
            return
        explicit_records.append(
            (active_tag, active_title, active_kv, active_lines, active_start, active_end, active_tail)
        )
        active_tag = None
        active_title = ""
        active_kv = {}
        active_lines = []
        active_start = 0
        active_end = 0
        active_tail = ""

    offset = 0
    for line in raw_text.splitlines(keepends=True):
        line_start = offset
        offset += len(line)
        line_end = offset
        line_no_eol = line.rstrip("\r\n")

        header_match = _TAG_HEADER_RE.match(line_no_eol.rstrip())
        if header_match:
            finalize_explicit()
            active_tag = TagType(header_match.group(1))
            active_tail = (header_match.group(2) or "").strip()
            active_title, active_kv = _parse_header_tail(active_tail)
            active_start = line_start
            active_end = line_end
            active_lines = []
            continue

        if active_tag is not None:
            close_match = _TAG_CLOSE_RE.match(line_no_eol.strip())
            if line_no_eol.strip() == "---END_SLICE---" or (
                close_match
                and close_match.group(1) in {active_tag.value, "#TAG"}
            ):
                finalize_explicit()
                continue
            active_lines.append(line)
            active_end = line_end
        else:
            untagged_chunks.append(line)

    finalize_explicit()

    slices: list[DataSlice] = []
    untagged_remainder = ""

    if explicit_records:
        untagged_remainder = "".join(untagged_chunks).strip("\r\n")
        for tag, title, kv, body_lines, span_start, span_end, raw_tail in explicit_records:
            body_text = "".join(body_lines).strip("\r\n")
            payload = body_text if body_text.strip() else (title or raw_tail)
            if not payload or not payload.strip():
                continue
            slice_tainted = tainted or (
                str(kv.get("privacy_tier", "")).lower() == "air_gapped"
                or kv.get("contains_personal_vault_data") is True
            )
            slices.append(
                _build_slice(
                    bundle_id=resolved_bundle_id,
                    index=len(slices) + 1,
                    tag=tag,
                    title=title,
                    raw_payload=payload,
                    structured_kv=kv,
                    source_span=(span_start, max(span_start, span_end)),
                    tainted=slice_tainted,
                )
            )
    else:
        # Untagged fallback classification via ThousandParamMicroModel (<0.2 ms / block).
        if micro_model is None:
            from .micro_model import ThousandParamMicroModel as _MicroModel

            classifier = _MicroModel()
        else:
            classifier = micro_model

        candidate_blocks = _split_untagged_blocks(raw_text)
        for block_title, block_text, span_start, span_end in candidate_blocks:
            idx = len(slices) + 1
            prediction = classifier.predict(
                block_text,
                slice_id=f"{resolved_bundle_id}-s{idx}",
                has_explicit_tag=False,
            )
            slices.append(
                _build_slice(
                    bundle_id=resolved_bundle_id,
                    index=idx,
                    tag=prediction.predicted_tag,
                    title=block_title,
                    raw_payload=block_text,
                    structured_kv={},
                    source_span=(span_start, max(span_start, span_end)),
                    tainted=tainted,
                )
            )

    tag_index: dict[TagType, list[str]] = {}
    for item in slices:
        tag_index.setdefault(item.tag, []).append(item.slice_id)

    if not slices or total_chars == 0:
        savings_ratio = 0.0
    else:
        max_slice_chars = max(len(item.raw_payload) for item in slices)
        savings_ratio = max(0.0, min(1.0, 1.0 - (max_slice_chars / total_chars)))

    bundle_tainted = tainted or any(item.contains_personal_vault_data for item in slices)
    latency_ms = (time.perf_counter() - t_start) * 1000.0

    return PreGroupedBundle(
        bundle_id=resolved_bundle_id,
        source_id=source_id,
        from_personal_vault=from_personal_vault,
        total_input_chars=total_chars,
        slices=slices,
        untagged_remainder=untagged_remainder,
        tag_index=tag_index,
        contains_personal_vault_data=bundle_tainted,
        token_savings_ratio=savings_ratio,
        slicing_latency_ms=latency_ms,
    )
