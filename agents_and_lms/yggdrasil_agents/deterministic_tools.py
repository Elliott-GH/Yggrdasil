"""Pure-Python deterministic engineering, data, PDF, AST, control, and research tools.

Implements all eight zero-token deterministic tool contracts defined in SPEC-001 Section 5:
1. ``data_handling_function`` (#TABLE_DATA)
2. ``calculation_solver_function`` (#CALC_SOLVE)
3. ``data_comparison_function`` (#DATA_COMPARE)
4. ``pdf_converter_function`` (#PDF_CONVERT)
5. ``smart_pdf_handling_function`` (#SMART_PDF_LINK)
6. ``coding_optimiser_function`` (#CODE_OPTIMISE)
7. ``control_system_optimiser_function`` (#CONTROL_SYSTEM)
8. ``research_tool_function`` & ``evaluate_local_research_gaps`` (#RESEARCH_GAP)
"""

from __future__ import annotations

import ast
import asyncio
import csv
import datetime
import hashlib
import importlib
import io
import json
import math
import operator
import re
import statistics
import time
import xml.etree.ElementTree as ET
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, Field, field_validator

from .roots import PrivacyTier
from .trunk import compute_decay_weight

R_GAS_CONSTANT: float = 8.31446261815324

TableCell = str | float | int | bool | None

_DOI_REGEX = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_MD_SEPARATOR_REGEX = re.compile(
    r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$|^\s*\|\s*:?-{2,}:?\s*\|\s*$"
)
_PIPE_SPLIT_REGEX = re.compile(r"(?<!\\)\|")

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"personal_vault", re.IGNORECASE),
    re.compile(r"air_gapped", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\b(?:password|secret|api_key|access_token)\s*[:=]", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
)

_ALLOWED_RESEARCH_HOSTS = frozenset(
    {
        "api.crossref.org",
        "export.arxiv.org",
        "api.openalex.org",
    }
)


def _elapsed_ms(start_perf: float) -> float:
    return max(0.0, (time.perf_counter() - start_perf) * 1000.0)


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_pii_or_vault_markers(text: str) -> bool:
    return any(pattern.search(text) is not None for pattern in _PII_PATTERNS)


# ---------------------------------------------------------------------------
# 5.1 data_handling_function (#TABLE_DATA)
# ---------------------------------------------------------------------------

TableOperation = Literal[
    "clean_whitespace",
    "coerce_numeric",
    "drop_empty_rows",
    "deduplicate",
    "summary_stats",
    "zscore_outliers",
    "sort",
    "filter",
    "to_markdown",
    "to_csv",
]
FilterOperator = Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"]


def _default_table_operations() -> list[TableOperation]:
    return [
        "clean_whitespace",
        "coerce_numeric",
        "summary_stats",
        "to_markdown",
    ]


class TableHandlingInput(BaseModel):
    """Input contract for pure-Python table parsing, cleaning, and statistical summaries."""

    slice_id: str
    raw_table: str = Field(min_length=1)
    input_format: Literal["auto", "csv", "tsv", "markdown", "json_records"] = "auto"
    operations: list[TableOperation] = Field(default_factory=_default_table_operations)
    group_by_column: str | None = None
    sort_by_column: str | None = None
    sort_descending: bool = False
    filter_column: str | None = None
    filter_operator: FilterOperator | None = None
    filter_value: str | float | int | None = None
    zscore_threshold: float = Field(default=3.0, gt=0.0)
    contains_personal_vault_data: bool = True


class ColumnSummaryStats(BaseModel):
    """Descriptive statistics and z-score outlier indices for a single table column."""

    column: str
    inferred_dtype: Literal["numeric", "string", "boolean", "mixed", "empty"]
    non_null_count: int = Field(ge=0)
    null_count: int = Field(ge=0)
    mean: float | None = None
    std_dev: float | None = None
    min_val: float | None = None
    median_val: float | None = None
    max_val: float | None = None
    outlier_row_indices: list[int] = Field(default_factory=list)


class GroupAggregateRow(BaseModel):
    """Group-by aggregation record storing per-group row counts, means, and sums."""

    group_key: str
    row_count: int = Field(ge=0)
    numeric_means: dict[str, float] = Field(default_factory=dict)
    numeric_sums: dict[str, float] = Field(default_factory=dict)


class TableHandlingOutput(BaseModel):
    """Structured output returned by ``data_handling_function``."""

    slice_id: str
    detected_format: Literal["csv", "tsv", "markdown", "json_records"]
    headers: list[str]
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    rows: list[list[TableCell]]
    column_stats: list[ColumnSummaryStats] = Field(default_factory=list)
    grouped_aggregates: list[GroupAggregateRow] = Field(default_factory=list)
    rendered_markdown: str = ""
    rendered_csv: str = ""
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


def _detect_table_format(
    raw_text: str,
    requested_format: Literal["auto", "csv", "tsv", "markdown", "json_records"],
) -> Literal["csv", "tsv", "markdown", "json_records"]:
    if requested_format != "auto":
        return requested_format
    stripped = raw_text.strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return "json_records"

    non_empty_lines = [line for line in stripped.splitlines() if line.strip()]
    if any(_MD_SEPARATOR_REGEX.match(line) for line in non_empty_lines):
        return "markdown"
    pipe_framed = sum(
        1
        for line in non_empty_lines
        if line.strip().startswith("|") and line.strip().endswith("|")
    )
    if non_empty_lines and pipe_framed >= min(2, len(non_empty_lines)) and pipe_framed >= 2:
        return "markdown"

    sample_line = non_empty_lines[0] if non_empty_lines else ""
    tab_count = sample_line.count("\t")
    comma_count = sample_line.count(",")
    if tab_count > 0 and (comma_count == 0 or tab_count >= comma_count):
        return "tsv"
    return "csv"


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip().removeprefix("|")
    if stripped.endswith("|") and not stripped.endswith("\\|"):
        stripped = stripped[:-1]
    parts = _PIPE_SPLIT_REGEX.split(stripped)
    return [part.replace("\\|", "|").strip() for part in parts]


def _normalize_cell_from_json(value: Any) -> TableCell:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(value, ensure_ascii=False)


def _parse_raw_table(
    raw_text: str,
    detected_format: Literal["csv", "tsv", "markdown", "json_records"],
    warnings: list[str],
) -> tuple[list[str], list[list[TableCell]]]:
    stripped = raw_text.strip()
    if not stripped:
        raise ValueError("raw_table must contain non-whitespace tabular data.")

    if detected_format == "json_records":
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid json_records payload: {exc}") from exc
        if not isinstance(parsed, list) or not all(isinstance(rec, dict) for rec in parsed):
            raise ValueError("json_records payload must be a JSON list of objects.")
        if not parsed:
            return [], []
        headers: list[str] = []
        seen_headers: set[str] = set()
        for record in parsed:
            for key in record:
                key_str = str(key).strip()
                if key_str not in seen_headers:
                    seen_headers.add(key_str)
                    headers.append(key_str)
        rows = [
            [_normalize_cell_from_json(record.get(col)) for col in headers]
            for record in parsed
        ]
        return headers, rows

    if detected_format == "markdown":
        non_empty = [line for line in stripped.splitlines() if line.strip()]
        parsed_rows: list[list[str]] = []
        for line in non_empty:
            if _MD_SEPARATOR_REGEX.match(line):
                continue
            parsed_rows.append(_split_markdown_row(line))
        if not parsed_rows:
            raise ValueError("Markdown table contained no header or data rows.")
        headers = [col.strip() for col in parsed_rows[0]]
        raw_rows: list[list[TableCell]] = [list(row) for row in parsed_rows[1:]]
    else:
        delimiter = "\t" if detected_format == "tsv" else ","
        reader = csv.reader(io.StringIO(stripped), delimiter=delimiter)
        all_rows = [row for row in reader if row]
        if not all_rows:
            raise ValueError("Delimited table contained no rows.")
        headers = [col.strip() for col in all_rows[0]]
        raw_rows = [list(row) for row in all_rows[1:]]

    col_count = len(headers)
    normalized_rows: list[list[TableCell]] = []
    padded_or_trimmed = False
    for row in raw_rows:
        if len(row) < col_count:
            padded_or_trimmed = True
            normalized_rows.append([*row, *([None] * (col_count - len(row)))])
        elif len(row) > col_count:
            padded_or_trimmed = True
            normalized_rows.append(row[:col_count])
        else:
            normalized_rows.append(row)
    if padded_or_trimmed:
        warnings.append("One or more rows had inconsistent column counts and were aligned.")
    return headers, normalized_rows


def _coerce_table_cell(value: TableCell) -> TableCell:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value.strip()
    lowered = text.lower()
    if lowered in {"", "null", "none", "na", "n/a"}:
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[+-]?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", text):
        try:
            num = float(text)
        except ValueError:
            return text
        return num if math.isfinite(num) else text
    return text


def _matches_filter(
    cell: TableCell,
    op: FilterOperator,
    target: str | float | None,
) -> bool:
    if op == "contains":
        if cell is None or target is None:
            return False
        return str(target) in str(cell)

    if op in {"eq", "ne"}:
        if cell is None or target is None:
            equal = cell is None and target is None
            return equal if op == "eq" else not equal
        if _is_numeric(cell) and _is_numeric(target):
            equal = float(cast(float | int, cell)) == float(cast(float | int, target))
        elif _is_numeric(target) and isinstance(cell, str):
            coerced = _coerce_table_cell(cell)
            if _is_numeric(coerced):
                equal = float(cast(float | int, coerced)) == float(cast(float | int, target))
            else:
                equal = cell == str(target)
        elif isinstance(cell, bool) or isinstance(target, bool):
            equal = isinstance(cell, bool) and isinstance(target, bool) and cell == target
        else:
            equal = str(cell) == str(target)
        return equal if op == "eq" else not equal

    # Ordering comparisons: gt, gte, lt, lte
    if cell is None or target is None:
        return False
    left_val: float | str
    right_val: float | str
    cell_num = _coerce_table_cell(cell) if isinstance(cell, str) else cell
    if _is_numeric(cell_num) and _is_numeric(target):
        left_val = float(cast(float | int, cell_num))
        right_val = float(cast(float | int, target))
    elif isinstance(cell, str) and isinstance(target, str):
        left_val = cell
        right_val = target
    else:
        return False

    if isinstance(left_val, float) and isinstance(right_val, float):
        if op == "gt":
            return left_val > right_val
        if op == "gte":
            return left_val >= right_val
        if op == "lt":
            return left_val < right_val
        return left_val <= right_val

    left_s, right_s = str(left_val), str(right_val)
    if op == "gt":
        return left_s > right_s
    if op == "gte":
        return left_s >= right_s
    if op == "lt":
        return left_s < right_s
    return left_s <= right_s


def _sort_key_for_cell(cell: TableCell) -> tuple[int, float, str]:
    if _is_numeric(cell):
        return (0, float(cast(float | int, cell)), "")
    if isinstance(cell, bool):
        return (1, 1.0 if cell else 0.0, str(cell))
    return (2, 0.0, str(cell).lower())


def _infer_column_dtype(
    non_null_values: Sequence[TableCell],
) -> Literal["numeric", "string", "boolean", "mixed", "empty"]:
    if not non_null_values:
        return "empty"
    has_num = any(_is_numeric(v) for v in non_null_values)
    has_bool = any(isinstance(v, bool) for v in non_null_values)
    has_str = any(isinstance(v, str) for v in non_null_values)
    type_count = int(has_num) + int(has_bool) + int(has_str)
    if type_count > 1:
        return "mixed"
    if has_num:
        return "numeric"
    if has_bool:
        return "boolean"
    return "string"


def _render_markdown_table(headers: list[str], rows: list[list[TableCell]]) -> str:
    if not headers:
        return ""

    def _fmt(cell: TableCell) -> str:
        if cell is None:
            return ""
        return str(cell).replace("|", "\\|").replace("\n", " ").replace("\r", "")

    header_line = "| " + " | ".join(_fmt(h) for h in headers) + " |"
    sep_line = "| " + " | ".join("---" for _ in headers) + " |"
    data_lines = ["| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows]
    return "\n".join([header_line, sep_line, *data_lines])


def _render_csv_table(headers: list[str], rows: list[list[TableCell]]) -> str:
    if not headers:
        return ""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if cell is None else cell for cell in row])
    return buf.getvalue().rstrip("\n")


def data_handling_function(payload: TableHandlingInput) -> TableHandlingOutput:
    """Deterministically parse, clean, filter, sort, summarize, and render tabular data."""
    t0 = time.perf_counter()
    warnings: list[str] = []
    detected_format = _detect_table_format(payload.raw_table, payload.input_format)
    headers, rows = _parse_raw_table(payload.raw_table, detected_format, warnings)

    ops_set = set(payload.operations)

    if "clean_whitespace" in ops_set:
        headers = [" ".join(h.split()) for h in headers]
        rows = [
            [" ".join(cell.split()) if isinstance(cell, str) else cell for cell in row]
            for row in rows
        ]

    # Validate explicit column references strictly before executing filters/sorts/grouping.
    if payload.filter_column is not None and payload.filter_column not in headers:
        raise ValueError(f"Unknown filter_column: {payload.filter_column!r}")
    if payload.sort_by_column is not None and payload.sort_by_column not in headers:
        raise ValueError(f"Unknown sort_by_column: {payload.sort_by_column!r}")
    if payload.group_by_column is not None and payload.group_by_column not in headers:
        raise ValueError(f"Unknown group_by_column: {payload.group_by_column!r}")

    if "drop_empty_rows" in ops_set:
        rows = [
            row
            for row in rows
            if any(
                cell is not None and (not isinstance(cell, str) or cell.strip() != "")
                for cell in row
            )
        ]

    if "coerce_numeric" in ops_set:
        rows = [[_coerce_table_cell(cell) for cell in row] for row in rows]

    if "deduplicate" in ops_set:
        deduped: list[list[TableCell]] = []
        seen_rows: set[tuple[tuple[str, TableCell], ...]] = set()
        for row in rows:
            signature = tuple((type(cell).__name__, cell) for cell in row)
            if signature not in seen_rows:
                seen_rows.add(signature)
                deduped.append(row)
        rows = deduped

    if "filter" in ops_set or payload.filter_column is not None:
        if payload.filter_column is None:
            warnings.append("Operation 'filter' requested without filter_column; skipped.")
        else:
            filter_idx = headers.index(payload.filter_column)
            op = payload.filter_operator
            if op is None:
                op = "eq"
                warnings.append("filter_operator omitted; defaulted to 'eq'.")
            rows = [
                row
                for row in rows
                if _matches_filter(row[filter_idx], op, payload.filter_value)
            ]

    if "sort" in ops_set or payload.sort_by_column is not None:
        if payload.sort_by_column is None:
            warnings.append("Operation 'sort' requested without sort_by_column; skipped.")
        else:
            sort_idx = headers.index(payload.sort_by_column)
            non_null_rows = [row for row in rows if row[sort_idx] is not None]
            null_rows = [row for row in rows if row[sort_idx] is None]
            non_null_rows.sort(
                key=lambda row: _sort_key_for_cell(row[sort_idx]),
                reverse=payload.sort_descending,
            )
            rows = [*non_null_rows, *null_rows]

    column_stats: list[ColumnSummaryStats] = []
    if "summary_stats" in ops_set or "zscore_outliers" in ops_set:
        for col_idx, col_name in enumerate(headers):
            col_cells = [row[col_idx] for row in rows]
            non_null = [cell for cell in col_cells if cell is not None]
            null_count = len(col_cells) - len(non_null)
            inferred_dtype = _infer_column_dtype(non_null)
            numeric_pairs = [
                (row_idx, float(cast(float | int, cell)))
                for row_idx, cell in enumerate(col_cells)
                if _is_numeric(cell) and math.isfinite(float(cast(float | int, cell)))
            ]
            if numeric_pairs:
                nums = [val for _, val in numeric_pairs]
                mean_val = statistics.fmean(nums)
                std_val = statistics.stdev(nums) if len(nums) >= 2 else 0.0
                min_val = min(nums)
                max_val = max(nums)
                median_val = float(statistics.median(nums))
                outliers = (
                    [
                        row_idx
                        for row_idx, val in numeric_pairs
                        if abs(val - mean_val) / std_val > payload.zscore_threshold
                    ]
                    if std_val > 0.0
                    else []
                )
            else:
                mean_val = None
                std_val = None
                min_val = None
                max_val = None
                median_val = None
                outliers = []
            column_stats.append(
                ColumnSummaryStats(
                    column=col_name,
                    inferred_dtype=inferred_dtype,
                    non_null_count=len(non_null),
                    null_count=null_count,
                    mean=mean_val,
                    std_dev=std_val,
                    min_val=min_val,
                    median_val=median_val,
                    max_val=max_val,
                    outlier_row_indices=outliers,
                )
            )

    grouped_aggregates: list[GroupAggregateRow] = []
    if payload.group_by_column is not None:
        group_idx = headers.index(payload.group_by_column)
        grouped_rows: dict[str, list[list[TableCell]]] = {}
        for row in rows:
            raw_key = row[group_idx]
            key = "null" if raw_key is None else str(raw_key)
            grouped_rows.setdefault(key, []).append(row)
        for key, group_items in grouped_rows.items():
            means: dict[str, float] = {}
            sums: dict[str, float] = {}
            for col_idx, col_name in enumerate(headers):
                if col_idx == group_idx:
                    continue
                vals = [
                    float(cast(float | int, r[col_idx]))
                    for r in group_items
                    if _is_numeric(r[col_idx])
                    and math.isfinite(float(cast(float | int, r[col_idx])))
                ]
                if vals:
                    means[col_name] = statistics.fmean(vals)
                    sums[col_name] = math.fsum(vals)
            grouped_aggregates.append(
                GroupAggregateRow(
                    group_key=key,
                    row_count=len(group_items),
                    numeric_means=means,
                    numeric_sums=sums,
                )
            )

    rendered_markdown = _render_markdown_table(headers, rows) if "to_markdown" in ops_set else ""
    rendered_csv = _render_csv_table(headers, rows) if "to_csv" in ops_set else ""

    return TableHandlingOutput(
        slice_id=payload.slice_id,
        detected_format=detected_format,
        headers=headers,
        row_count=len(rows),
        column_count=len(headers),
        rows=rows,
        column_stats=column_stats,
        grouped_aggregates=grouped_aggregates,
        rendered_markdown=rendered_markdown,
        rendered_csv=rendered_csv,
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.2 calculation_solver_function (#CALC_SOLVE)
# ---------------------------------------------------------------------------


class UnitQuantity(BaseModel):
    """Scalar value paired with a physical or dimensionless unit string."""

    value: float
    unit: str = Field(min_length=1)


class CalculationSolverInput(BaseModel):
    """Input schema for safe AST arithmetic, SI conversions, and ChemEng solvers."""

    slice_id: str
    mode: Literal[
        "evaluate_expression",
        "unit_convert",
        "ideal_gas",
        "arrhenius",
        "reynolds_number",
        "antoine_vapor_pressure",
        "newton_root",
        "simpson_integrate",
    ]
    expression: str | None = None
    variables: dict[str, float] = Field(default_factory=dict)
    quantity: UnitQuantity | None = None
    target_unit: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    solve_for: str | None = None
    significant_figures: int = Field(default=6, ge=1, le=15)
    contains_personal_vault_data: bool = True


class CalculationSolverOutput(BaseModel):
    """Output schema returned by ``calculation_solver_function``."""

    slice_id: str
    mode: str
    result_value: float
    result_unit: str = "dimensionless"
    formatted_result: str
    residual_error: float = Field(default=0.0, ge=0.0)
    iterations_used: int = Field(default=0, ge=0)
    formula_applied: str
    unit_conversion_factor: float | None = None
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


_AST_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_AST_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_SAFE_CONSTANTS: dict[str, float] = {
    "pi": math.pi,
    "e": math.e,
    "R_gas": R_GAS_CONSTANT,
}


def _safe_pow_func(base: float, exp_val: float) -> float:
    if abs(exp_val) > 1000.0:
        raise ValueError("Exponent magnitude exceeds safe bound (1000).")
    res = pow(base, exp_val)
    if isinstance(res, complex) or not math.isfinite(float(res)):
        raise ValueError("Power evaluation produced complex or non-finite result.")
    return float(res)


def _is_finite_real_number(val: object) -> bool:
    return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(float(val))


def _safe_eval_ast_tree(tree: ast.Expression, variables: Mapping[str, float]) -> float:
    env: dict[str, float] = dict(_SAFE_CONSTANTS)
    for k, v in variables.items():
        if not _is_finite_real_number(v):
            raise ValueError(f"Variable {k!r} must be a finite real number.")
        env[k] = float(v)

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if not _is_finite_real_number(node.value):
                raise ValueError(
                    f"Unsupported or non-finite constant: {type(node.value).__name__}"
                )
            return float(cast(int | float, node.value))
        if isinstance(node, ast.Name):
            if type(node.ctx) is not ast.Load:
                raise ValueError("Only load context is permitted for variable references.")
            if node.id not in env:
                raise ValueError(f"Unknown variable or constant: {node.id!r}")
            return env[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _AST_UNARY_OPS:
            res = _AST_UNARY_OPS[type(node.op)](_eval(node.operand))
            if not math.isfinite(res):
                raise ValueError("Non-finite unary arithmetic result.")
            return res
        if isinstance(node, ast.BinOp) and type(node.op) in _AST_BIN_OPS:
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000.0:
                raise ValueError("Exponent magnitude exceeds safe bound (1000).")
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0.0:
                raise ValueError("Division or modulo by zero is undefined.")
            try:
                raw_res = _AST_BIN_OPS[type(node.op)](left, right)
            except OverflowError as exc:
                raise ValueError("Arithmetic overflow.") from exc
            if not _is_finite_real_number(raw_res):
                raise ValueError("Arithmetic result is complex or non-finite.")
            return float(raw_res)
        if isinstance(node, ast.Call):
            if type(node.func) is not ast.Name:
                raise ValueError("Attribute or dynamic function calls are disallowed.")
            if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
                raise ValueError("Keyword and starred arguments are disallowed in safe AST calls.")
            func_name = node.func.id
            args = [_eval(arg) for arg in node.args]
            res = _dispatch_safe_math_call(func_name, args)
            if not math.isfinite(res):
                raise ValueError(f"Function {func_name!r} returned non-finite result.")
            return res
        raise ValueError(f"Disallowed AST node: {type(node).__name__}")

    return _eval(tree)


def _dispatch_safe_math_call(func_name: str, args: list[float]) -> float:
    single_arg_funcs: dict[str, Callable[[float], float]] = {
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "exp": math.exp,
        "log10": math.log10,
        "sqrt": math.sqrt,
        "abs": abs,
    }
    if func_name in single_arg_funcs:
        if len(args) != 1:
            raise ValueError(f"{func_name}() expects exactly 1 argument, got {len(args)}.")
        try:
            return float(single_arg_funcs[func_name](args[0]))
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Math domain/range error in {func_name}(): {exc}") from exc
    if func_name == "log":
        if len(args) not in (1, 2):
            raise ValueError(f"log() expects 1 or 2 arguments, got {len(args)}.")
        try:
            return float(math.log(args[0]) if len(args) == 1 else math.log(args[0], args[1]))
        except ValueError as exc:
            raise ValueError(f"Math domain error in log(): {exc}") from exc
    if func_name == "pow":
        if len(args) != 2:
            raise ValueError(f"pow() expects exactly 2 arguments, got {len(args)}.")
        return _safe_pow_func(args[0], args[1])
    if func_name in {"min", "max"}:
        if not args:
            raise ValueError(f"{func_name}() expects at least 1 argument.")
        return float(min(args) if func_name == "min" else max(args))
    raise ValueError(f"Disallowed function call: {func_name!r}")


def _parse_safe_expression(expression: str | None) -> ast.Expression:
    if expression is None or not expression.strip():
        raise ValueError("expression must be a non-empty arithmetic expression.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {exc.msg}") from exc
    if type(tree) is not ast.Expression:
        raise ValueError("Expression must parse to an ast.Expression.")
    return tree


class _UnitDef(NamedTuple):
    """SI dimensional vector (M, L, T, Theta, N) with linear scale & affine offset."""

    dims: tuple[int, int, int, int, int]
    scale: float
    offset: float = 0.0


_UNIT_REGISTRY: dict[str, _UnitDef] = {
    # Dimensionless (0, 0, 0, 0, 0)
    "dimensionless": _UnitDef((0, 0, 0, 0, 0), 1.0),
    "unitless": _UnitDef((0, 0, 0, 0, 0), 1.0),
    "1": _UnitDef((0, 0, 0, 0, 0), 1.0),
    "%": _UnitDef((0, 0, 0, 0, 0), 0.01),
    "percent": _UnitDef((0, 0, 0, 0, 0), 0.01),
    "ppm": _UnitDef((0, 0, 0, 0, 0), 1e-6),
    "ppb": _UnitDef((0, 0, 0, 0, 0), 1e-9),
    # Mass (1, 0, 0, 0, 0)
    "kg": _UnitDef((1, 0, 0, 0, 0), 1.0),
    "g": _UnitDef((1, 0, 0, 0, 0), 1e-3),
    "mg": _UnitDef((1, 0, 0, 0, 0), 1e-6),
    "ug": _UnitDef((1, 0, 0, 0, 0), 1e-9),
    "tonne": _UnitDef((1, 0, 0, 0, 0), 1000.0),
    "t": _UnitDef((1, 0, 0, 0, 0), 1000.0),
    "lb": _UnitDef((1, 0, 0, 0, 0), 0.45359237),
    "lbm": _UnitDef((1, 0, 0, 0, 0), 0.45359237),
    "oz": _UnitDef((1, 0, 0, 0, 0), 0.45359237 / 16.0),
    # Length (0, 1, 0, 0, 0)
    "m": _UnitDef((0, 1, 0, 0, 0), 1.0),
    "cm": _UnitDef((0, 1, 0, 0, 0), 1e-2),
    "mm": _UnitDef((0, 1, 0, 0, 0), 1e-3),
    "um": _UnitDef((0, 1, 0, 0, 0), 1e-6),
    "nm": _UnitDef((0, 1, 0, 0, 0), 1e-9),
    "km": _UnitDef((0, 1, 0, 0, 0), 1000.0),
    "in": _UnitDef((0, 1, 0, 0, 0), 0.0254),
    "inch": _UnitDef((0, 1, 0, 0, 0), 0.0254),
    "ft": _UnitDef((0, 1, 0, 0, 0), 0.3048),
    "yd": _UnitDef((0, 1, 0, 0, 0), 0.9144),
    "mi": _UnitDef((0, 1, 0, 0, 0), 1609.344),
    # Area (0, 2, 0, 0, 0)
    "m2": _UnitDef((0, 2, 0, 0, 0), 1.0),
    "m^2": _UnitDef((0, 2, 0, 0, 0), 1.0),
    "cm2": _UnitDef((0, 2, 0, 0, 0), 1e-4),
    "cm^2": _UnitDef((0, 2, 0, 0, 0), 1e-4),
    "mm2": _UnitDef((0, 2, 0, 0, 0), 1e-6),
    "mm^2": _UnitDef((0, 2, 0, 0, 0), 1e-6),
    "ft2": _UnitDef((0, 2, 0, 0, 0), 0.3048**2),
    "ft^2": _UnitDef((0, 2, 0, 0, 0), 0.3048**2),
    # Volume (0, 3, 0, 0, 0)
    "m3": _UnitDef((0, 3, 0, 0, 0), 1.0),
    "m^3": _UnitDef((0, 3, 0, 0, 0), 1.0),
    "L": _UnitDef((0, 3, 0, 0, 0), 1e-3),
    "l": _UnitDef((0, 3, 0, 0, 0), 1e-3),
    "liter": _UnitDef((0, 3, 0, 0, 0), 1e-3),
    "litre": _UnitDef((0, 3, 0, 0, 0), 1e-3),
    "mL": _UnitDef((0, 3, 0, 0, 0), 1e-6),
    "ml": _UnitDef((0, 3, 0, 0, 0), 1e-6),
    "cm3": _UnitDef((0, 3, 0, 0, 0), 1e-6),
    "cm^3": _UnitDef((0, 3, 0, 0, 0), 1e-6),
    "ft3": _UnitDef((0, 3, 0, 0, 0), 0.3048**3),
    "ft^3": _UnitDef((0, 3, 0, 0, 0), 0.3048**3),
    "gal": _UnitDef((0, 3, 0, 0, 0), 0.003785411784),
    # Time (0, 0, 1, 0, 0)
    "s": _UnitDef((0, 0, 1, 0, 0), 1.0),
    "sec": _UnitDef((0, 0, 1, 0, 0), 1.0),
    "ms": _UnitDef((0, 0, 1, 0, 0), 1e-3),
    "us": _UnitDef((0, 0, 1, 0, 0), 1e-6),
    "min": _UnitDef((0, 0, 1, 0, 0), 60.0),
    "h": _UnitDef((0, 0, 1, 0, 0), 3600.0),
    "hr": _UnitDef((0, 0, 1, 0, 0), 3600.0),
    "day": _UnitDef((0, 0, 1, 0, 0), 86400.0),
    "d": _UnitDef((0, 0, 1, 0, 0), 86400.0),
    # Temperature (0, 0, 0, 1, 0) — affine SI conversion to Kelvin
    "K": _UnitDef((0, 0, 0, 1, 0), 1.0, 0.0),
    "kelvin": _UnitDef((0, 0, 0, 1, 0), 1.0, 0.0),
    "C": _UnitDef((0, 0, 0, 1, 0), 1.0, 273.15),
    "degC": _UnitDef((0, 0, 0, 1, 0), 1.0, 273.15),
    "°C": _UnitDef((0, 0, 0, 1, 0), 1.0, 273.15),
    "celsius": _UnitDef((0, 0, 0, 1, 0), 1.0, 273.15),
    "F": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 273.15 - (32.0 * 5.0 / 9.0)),
    "degF": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 273.15 - (32.0 * 5.0 / 9.0)),
    "°F": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 273.15 - (32.0 * 5.0 / 9.0)),
    "fahrenheit": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 273.15 - (32.0 * 5.0 / 9.0)),
    "R": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 0.0),
    "degR": _UnitDef((0, 0, 0, 1, 0), 5.0 / 9.0, 0.0),
    # Amount of substance (0, 0, 0, 0, 1)
    "mol": _UnitDef((0, 0, 0, 0, 1), 1.0),
    "kmol": _UnitDef((0, 0, 0, 0, 1), 1000.0),
    "mmol": _UnitDef((0, 0, 0, 0, 1), 1e-3),
    "lbmol": _UnitDef((0, 0, 0, 0, 1), 453.59237),
    # Velocity (0, 1, -1, 0, 0)
    "m/s": _UnitDef((0, 1, -1, 0, 0), 1.0),
    "cm/s": _UnitDef((0, 1, -1, 0, 0), 0.01),
    "mm/s": _UnitDef((0, 1, -1, 0, 0), 0.001),
    "km/h": _UnitDef((0, 1, -1, 0, 0), 1000.0 / 3600.0),
    "km/hr": _UnitDef((0, 1, -1, 0, 0), 1000.0 / 3600.0),
    "ft/s": _UnitDef((0, 1, -1, 0, 0), 0.3048),
    "mph": _UnitDef((0, 1, -1, 0, 0), 1609.344 / 3600.0),
    # Volumetric flow (0, 3, -1, 0, 0)
    "m3/s": _UnitDef((0, 3, -1, 0, 0), 1.0),
    "m^3/s": _UnitDef((0, 3, -1, 0, 0), 1.0),
    "m3/h": _UnitDef((0, 3, -1, 0, 0), 1.0 / 3600.0),
    "m^3/h": _UnitDef((0, 3, -1, 0, 0), 1.0 / 3600.0),
    "L/s": _UnitDef((0, 3, -1, 0, 0), 1e-3),
    "L/min": _UnitDef((0, 3, -1, 0, 0), 1e-3 / 60.0),
    "L/h": _UnitDef((0, 3, -1, 0, 0), 1e-3 / 3600.0),
    "gpm": _UnitDef((0, 3, -1, 0, 0), 0.003785411784 / 60.0),
    # Mass flow (1, 0, -1, 0, 0)
    "kg/s": _UnitDef((1, 0, -1, 0, 0), 1.0),
    "kg/h": _UnitDef((1, 0, -1, 0, 0), 1.0 / 3600.0),
    "g/s": _UnitDef((1, 0, -1, 0, 0), 1e-3),
    "lb/s": _UnitDef((1, 0, -1, 0, 0), 0.45359237),
    "lb/h": _UnitDef((1, 0, -1, 0, 0), 0.45359237 / 3600.0),
    # Molar flow (0, 0, -1, 0, 1)
    "mol/s": _UnitDef((0, 0, -1, 0, 1), 1.0),
    "mol/min": _UnitDef((0, 0, -1, 0, 1), 1.0 / 60.0),
    "kmol/s": _UnitDef((0, 0, -1, 0, 1), 1000.0),
    "kmol/h": _UnitDef((0, 0, -1, 0, 1), 1000.0 / 3600.0),
    # Density (1, -3, 0, 0, 0)
    "kg/m3": _UnitDef((1, -3, 0, 0, 0), 1.0),
    "kg/m^3": _UnitDef((1, -3, 0, 0, 0), 1.0),
    "g/cm3": _UnitDef((1, -3, 0, 0, 0), 1000.0),
    "g/cm^3": _UnitDef((1, -3, 0, 0, 0), 1000.0),
    "g/mL": _UnitDef((1, -3, 0, 0, 0), 1000.0),
    "g/ml": _UnitDef((1, -3, 0, 0, 0), 1000.0),
    "g/L": _UnitDef((1, -3, 0, 0, 0), 1.0),
    "kg/L": _UnitDef((1, -3, 0, 0, 0), 1000.0),
    "lb/ft3": _UnitDef((1, -3, 0, 0, 0), 0.45359237 / (0.3048**3)),
    "lb/ft^3": _UnitDef((1, -3, 0, 0, 0), 0.45359237 / (0.3048**3)),
    # Force (1, 1, -2, 0, 0)
    "N": _UnitDef((1, 1, -2, 0, 0), 1.0),
    "kN": _UnitDef((1, 1, -2, 0, 0), 1000.0),
    "lbf": _UnitDef((1, 1, -2, 0, 0), 4.4482216152605),
    # Pressure (1, -1, -2, 0, 0)
    "Pa": _UnitDef((1, -1, -2, 0, 0), 1.0),
    "kPa": _UnitDef((1, -1, -2, 0, 0), 1e3),
    "MPa": _UnitDef((1, -1, -2, 0, 0), 1e6),
    "GPa": _UnitDef((1, -1, -2, 0, 0), 1e9),
    "bar": _UnitDef((1, -1, -2, 0, 0), 1e5),
    "mbar": _UnitDef((1, -1, -2, 0, 0), 100.0),
    "atm": _UnitDef((1, -1, -2, 0, 0), 101325.0),
    "psi": _UnitDef((1, -1, -2, 0, 0), 6894.757293168361),
    "mmHg": _UnitDef((1, -1, -2, 0, 0), 101325.0 / 760.0),
    "torr": _UnitDef((1, -1, -2, 0, 0), 101325.0 / 760.0),
    # Energy (1, 2, -2, 0, 0)
    "J": _UnitDef((1, 2, -2, 0, 0), 1.0),
    "kJ": _UnitDef((1, 2, -2, 0, 0), 1e3),
    "MJ": _UnitDef((1, 2, -2, 0, 0), 1e6),
    "cal": _UnitDef((1, 2, -2, 0, 0), 4.184),
    "kcal": _UnitDef((1, 2, -2, 0, 0), 4184.0),
    "Wh": _UnitDef((1, 2, -2, 0, 0), 3600.0),
    "kWh": _UnitDef((1, 2, -2, 0, 0), 3.6e6),
    "BTU": _UnitDef((1, 2, -2, 0, 0), 1055.05585262),
    "btu": _UnitDef((1, 2, -2, 0, 0), 1055.05585262),
    # Power (1, 2, -3, 0, 0)
    "W": _UnitDef((1, 2, -3, 0, 0), 1.0),
    "kW": _UnitDef((1, 2, -3, 0, 0), 1e3),
    "MW": _UnitDef((1, 2, -3, 0, 0), 1e6),
    "hp": _UnitDef((1, 2, -3, 0, 0), 745.6998715822702),
    # Molar energy (1, 2, -2, 0, -1)
    "J/mol": _UnitDef((1, 2, -2, 0, -1), 1.0),
    "kJ/mol": _UnitDef((1, 2, -2, 0, -1), 1e3),
    "cal/mol": _UnitDef((1, 2, -2, 0, -1), 4.184),
    "kcal/mol": _UnitDef((1, 2, -2, 0, -1), 4184.0),
    # Specific energy (0, 2, -2, 0, 0)
    "J/kg": _UnitDef((0, 2, -2, 0, 0), 1.0),
    "kJ/kg": _UnitDef((0, 2, -2, 0, 0), 1e3),
    # Dynamic viscosity (1, -1, -1, 0, 0)
    "Pa*s": _UnitDef((1, -1, -1, 0, 0), 1.0),
    "Pa.s": _UnitDef((1, -1, -1, 0, 0), 1.0),
    "Pa·s": _UnitDef((1, -1, -1, 0, 0), 1.0),
    "kg/(m*s)": _UnitDef((1, -1, -1, 0, 0), 1.0),
    "cP": _UnitDef((1, -1, -1, 0, 0), 1e-3),
    "mPa*s": _UnitDef((1, -1, -1, 0, 0), 1e-3),
    "mPa.s": _UnitDef((1, -1, -1, 0, 0), 1e-3),
    "P": _UnitDef((1, -1, -1, 0, 0), 0.1),
    # Kinematic viscosity (0, 2, -1, 0, 0)
    "m2/s": _UnitDef((0, 2, -1, 0, 0), 1.0),
    "m^2/s": _UnitDef((0, 2, -1, 0, 0), 1.0),
    "cSt": _UnitDef((0, 2, -1, 0, 0), 1e-6),
    "St": _UnitDef((0, 2, -1, 0, 0), 1e-4),
    # Frequency / 1st-order rate (0, 0, -1, 0, 0)
    "1/s": _UnitDef((0, 0, -1, 0, 0), 1.0),
    "s^-1": _UnitDef((0, 0, -1, 0, 0), 1.0),
    "Hz": _UnitDef((0, 0, -1, 0, 0), 1.0),
    "1/min": _UnitDef((0, 0, -1, 0, 0), 1.0 / 60.0),
    "min^-1": _UnitDef((0, 0, -1, 0, 0), 1.0 / 60.0),
    "1/h": _UnitDef((0, 0, -1, 0, 0), 1.0 / 3600.0),
    "h^-1": _UnitDef((0, 0, -1, 0, 0), 1.0 / 3600.0),
    # Molar concentration (0, -3, 0, 0, 1)
    "mol/m3": _UnitDef((0, -3, 0, 0, 1), 1.0),
    "mol/m^3": _UnitDef((0, -3, 0, 0, 1), 1.0),
    "mol/L": _UnitDef((0, -3, 0, 0, 1), 1000.0),
    "M": _UnitDef((0, -3, 0, 0, 1), 1000.0),
    "mmol/L": _UnitDef((0, -3, 0, 0, 1), 1.0),
    "mM": _UnitDef((0, -3, 0, 0, 1), 1.0),
    # Molar heat capacity / gas constant (1, 2, -2, -1, -1)
    "J/(mol*K)": _UnitDef((1, 2, -2, -1, -1), 1.0),
    "J/mol/K": _UnitDef((1, 2, -2, -1, -1), 1.0),
    "kJ/(mol*K)": _UnitDef((1, 2, -2, -1, -1), 1e3),
    "kJ/mol/K": _UnitDef((1, 2, -2, -1, -1), 1e3),
    "cal/(mol*K)": _UnitDef((1, 2, -2, -1, -1), 4.184),
    # Specific heat capacity (0, 2, -2, -1, 0)
    "J/(kg*K)": _UnitDef((0, 2, -2, -1, 0), 1.0),
    "J/kg/K": _UnitDef((0, 2, -2, -1, 0), 1.0),
    "kJ/(kg*K)": _UnitDef((0, 2, -2, -1, 0), 1e3),
    "kJ/kg/K": _UnitDef((0, 2, -2, -1, 0), 1e3),
}


def _lookup_unit(unit: str) -> _UnitDef:
    cleaned = unit.strip()
    if cleaned in _UNIT_REGISTRY:
        return _UNIT_REGISTRY[cleaned]
    lower_aliases = {
        "celsius": "C",
        "fahrenheit": "F",
        "kelvin": "K",
        "dimensionless": "dimensionless",
        "unitless": "unitless",
        "percent": "percent",
        "liter": "L",
        "litre": "L",
    }
    alias = lower_aliases.get(cleaned.lower())
    if alias is not None:
        return _UNIT_REGISTRY[alias]
    raise ValueError(f"Unsupported unit: {unit!r}")


def _format_sig_figs(value: float, sig_figs: int, unit: str) -> str:
    num_str = f"{value:.{sig_figs}g}"
    if unit == "dimensionless":
        return num_str
    return f"{num_str} {unit}"


def _require_param(params: Mapping[str, float], key: str, aliases: tuple[str, ...] = ()) -> float:
    for candidate in (key, *aliases):
        if candidate in params:
            val = float(params[candidate])
            if not math.isfinite(val):
                raise ValueError(f"Parameter {candidate!r} must be finite.")
            return val
    raise ValueError(f"Missing required parameter: {key!r}")


def calculation_solver_function(payload: CalculationSolverInput) -> CalculationSolverOutput:
    """Execute deterministic AST arithmetic, unit conversions, and ChemEng/numerical solvers."""
    t0 = time.perf_counter()
    warnings: list[str] = []
    residual_error = 0.0
    iterations_used = 0
    unit_conversion_factor: float | None = None

    if payload.mode == "evaluate_expression":
        tree = _parse_safe_expression(payload.expression)
        result_value = _safe_eval_ast_tree(tree, payload.variables)
        result_unit = "dimensionless"
        formula_applied = f"AST_EVAL({payload.expression})"

    elif payload.mode == "unit_convert":
        if payload.quantity is None or not payload.target_unit or not payload.target_unit.strip():
            raise ValueError("unit_convert requires both 'quantity' and 'target_unit'.")
        if not math.isfinite(payload.quantity.value):
            raise ValueError("quantity.value must be finite.")
        src = _lookup_unit(payload.quantity.unit)
        dst = _lookup_unit(payload.target_unit)
        if src.dims != dst.dims:
            raise ValueError(
                f"Dimension mismatch: cannot convert {payload.quantity.unit!r} "
                f"to {payload.target_unit!r}."
            )
        si_val = src.scale * payload.quantity.value + src.offset
        result_value = (si_val - dst.offset) / dst.scale
        result_unit = payload.target_unit.strip()
        if src.offset == 0.0 and dst.offset == 0.0:
            unit_conversion_factor = src.scale / dst.scale
        formula_applied = (
            f"unit_convert({payload.quantity.unit} -> {result_unit})"
        )

    elif payload.mode == "ideal_gas":
        params = payload.parameters
        solve_for = payload.solve_for
        all_vars = ("P", "V", "n", "T")
        if solve_for is None:
            missing = [k for k in all_vars if k not in params]
            if len(missing) != 1:
                raise ValueError(
                    "ideal_gas requires 'solve_for' in {'P','V','n','T'} or exactly 3 of {P,V,n,T}."
                )
            solve_for = missing[0]
        if solve_for not in all_vars:
            raise ValueError(f"ideal_gas solve_for must be one of {all_vars}, got {solve_for!r}.")

        if solve_for == "P":
            vol = _require_param(params, "V")
            mol = _require_param(params, "n")
            temp = _require_param(params, "T")
            if vol <= 0.0 or temp <= 0.0 or mol < 0.0:
                raise ValueError("ideal_gas requires V > 0, T > 0 K, and n >= 0.")
            result_value = (mol * R_GAS_CONSTANT * temp) / vol
            result_unit = "Pa"
            residual_error = abs(result_value * vol - mol * R_GAS_CONSTANT * temp)
            formula_applied = "P = n * R * T / V"
        elif solve_for == "V":
            pres = _require_param(params, "P")
            mol = _require_param(params, "n")
            temp = _require_param(params, "T")
            if pres <= 0.0 or temp <= 0.0 or mol < 0.0:
                raise ValueError("ideal_gas requires P > 0, T > 0 K, and n >= 0.")
            result_value = (mol * R_GAS_CONSTANT * temp) / pres
            result_unit = "m3"
            residual_error = abs(pres * result_value - mol * R_GAS_CONSTANT * temp)
            formula_applied = "V = n * R * T / P"
        elif solve_for == "n":
            pres = _require_param(params, "P")
            vol = _require_param(params, "V")
            temp = _require_param(params, "T")
            if pres < 0.0 or vol <= 0.0 or temp <= 0.0:
                raise ValueError("ideal_gas requires P >= 0, V > 0, and T > 0 K.")
            result_value = (pres * vol) / (R_GAS_CONSTANT * temp)
            result_unit = "mol"
            residual_error = abs(pres * vol - result_value * R_GAS_CONSTANT * temp)
            formula_applied = "n = P * V / (R * T)"
        else:
            pres = _require_param(params, "P")
            vol = _require_param(params, "V")
            mol = _require_param(params, "n")
            if pres <= 0.0 or vol <= 0.0 or mol <= 0.0:
                raise ValueError("ideal_gas requires P > 0, V > 0, and n > 0 to solve for T.")
            result_value = (pres * vol) / (mol * R_GAS_CONSTANT)
            result_unit = "K"
            residual_error = abs(pres * vol - mol * R_GAS_CONSTANT * result_value)
            formula_applied = "T = P * V / (n * R)"

    elif payload.mode == "arrhenius":
        pre_exp = _require_param(payload.parameters, "A")
        ea = _require_param(payload.parameters, "Ea", aliases=("ea",))
        temp_k = _require_param(payload.parameters, "T", aliases=("T_K",))
        if pre_exp <= 0.0 or ea < 0.0 or temp_k <= 0.0:
            raise ValueError("Arrhenius requires A > 0, Ea >= 0 J/mol, and T > 0 K.")
        try:
            result_value = pre_exp * math.exp(-ea / (R_GAS_CONSTANT * temp_k))
        except OverflowError as exc:
            raise ValueError("Arrhenius evaluation overflowed float precision.") from exc
        if not math.isfinite(result_value):
            raise ValueError("Arrhenius evaluation produced non-finite result.")
        result_unit = "1/s"
        formula_applied = "k(T) = A * exp(-Ea / (R * T))"

    elif payload.mode == "reynolds_number":
        rho = _require_param(payload.parameters, "rho", aliases=("density",))
        vel = _require_param(payload.parameters, "v", aliases=("velocity",))
        diam = _require_param(payload.parameters, "D", aliases=("diameter",))
        mu = _require_param(payload.parameters, "mu", aliases=("viscosity",))
        if rho <= 0.0 or vel < 0.0 or diam <= 0.0 or mu <= 0.0:
            raise ValueError(
                "Reynolds number requires rho > 0, v >= 0, D > 0, and mu > 0."
            )
        result_value = (rho * vel * diam) / mu
        if result_value < 2100.0:
            regime = "laminar"
        elif result_value <= 4000.0:
            regime = "transitional"
        else:
            regime = "turbulent"
        warnings.append(f"Flow regime: {regime}")
        result_unit = "dimensionless"
        formula_applied = f"Re = rho * v * D / mu ({regime})"

    elif payload.mode == "antoine_vapor_pressure":
        a_coef = _require_param(payload.parameters, "A")
        b_coef = _require_param(payload.parameters, "B")
        c_coef = _require_param(payload.parameters, "C")
        temp_c = _require_param(payload.parameters, "T_C", aliases=("T",))
        denom = c_coef + temp_c
        if abs(denom) < 1e-12:
            raise ValueError("Antoine equation singularity: C + T_C cannot be zero.")
        exponent = a_coef - (b_coef / denom)
        try:
            result_value = math.pow(10.0, exponent)
        except OverflowError as exc:
            raise ValueError("Antoine vapor pressure overflowed float precision.") from exc
        if not math.isfinite(result_value):
            raise ValueError("Antoine vapor pressure produced non-finite result.")
        result_unit = "mmHg"
        formula_applied = "P_mmHg = 10^(A - B / (C + T_C))"

    elif payload.mode == "newton_root":
        tree = _parse_safe_expression(payload.expression)
        var_name = payload.solve_for or "x"
        if "x0" in payload.parameters:
            x = float(payload.parameters["x0"])
        elif "x0" in payload.variables:
            x = float(payload.variables["x0"])
        else:
            raise ValueError("newton_root requires initial guess 'x0' in parameters.")
        if not math.isfinite(x):
            raise ValueError("Initial guess 'x0' must be finite.")
        max_iter = int(payload.parameters.get("max_iter", 100))
        tol = float(payload.parameters.get("tol", 1e-10))
        if max_iter < 1 or tol <= 0.0:
            raise ValueError("newton_root requires max_iter >= 1 and tol > 0.")

        base_vars = dict(payload.variables)

        def _eval_at(x_val: float) -> float:
            local_env = dict(base_vars)
            local_env[var_name] = x_val
            return _safe_eval_ast_tree(tree, local_env)

        fx = _eval_at(x)
        converged = abs(fx) < tol
        for step in range(1, max_iter + 1):
            if converged:
                break
            h = 1e-7 * max(1.0, abs(x))
            dfx = (_eval_at(x + h) - _eval_at(x - h)) / (2.0 * h)
            if abs(dfx) < 1e-14:
                raise ValueError("Newton-Raphson derivative |f'(x)| fell below 1e-14.")
            x_next = x - (fx / dfx)
            if not math.isfinite(x_next):
                raise ValueError("Newton-Raphson iterate became non-finite.")
            x = x_next
            fx = _eval_at(x)
            iterations_used = step
            if abs(fx) < tol:
                converged = True
                break
        if not converged:
            raise ValueError(f"Newton-Raphson did not converge within {max_iter} iterations.")
        result_value = x
        residual_error = abs(fx)
        result_unit = "dimensionless"
        formula_applied = f"Newton-Raphson root of {payload.expression} = 0"

    else:  # simpson_integrate
        tree = _parse_safe_expression(payload.expression)
        var_name = payload.solve_for or "x"
        a_bound = _require_param(payload.parameters, "a")
        b_bound = _require_param(payload.parameters, "b")
        raw_n = int(payload.parameters.get("n_steps", payload.parameters.get("n", 100)))
        if raw_n < 2:
            raw_n = 2
            warnings.append("simpson_integrate n_steps raised to minimum 2.")
        if raw_n % 2 != 0:
            raw_n += 1
            warnings.append(f"simpson_integrate requires even steps; adjusted n_steps to {raw_n}.")

        base_vars = dict(payload.variables)

        def _f(x_val: float) -> float:
            local_env = dict(base_vars)
            local_env[var_name] = x_val
            return _safe_eval_ast_tree(tree, local_env)

        if a_bound == b_bound:
            result_value = 0.0
        else:
            step_h = (b_bound - a_bound) / raw_n
            terms: list[float] = [_f(a_bound), _f(b_bound)]
            for idx in range(1, raw_n):
                weight = 4.0 if idx % 2 == 1 else 2.0
                terms.append(weight * _f(a_bound + idx * step_h))
            result_value = (step_h / 3.0) * math.fsum(terms)
        iterations_used = raw_n
        result_unit = "dimensionless"
        formula_applied = f"Composite Simpson 1/3 over [{a_bound}, {b_bound}] (n={raw_n})"

    return CalculationSolverOutput(
        slice_id=payload.slice_id,
        mode=payload.mode,
        result_value=result_value,
        result_unit=result_unit,
        formatted_result=_format_sig_figs(result_value, payload.significant_figures, result_unit),
        residual_error=residual_error,
        iterations_used=iterations_used,
        formula_applied=formula_applied,
        unit_conversion_factor=unit_conversion_factor,
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.3 data_comparison_function (#DATA_COMPARE)
# ---------------------------------------------------------------------------


class DataComparisonInput(BaseModel):
    """Input schema for deterministic series and key-value/table comparison."""

    slice_id: str
    comparison_mode: Literal["numeric_series", "key_value_records", "table_diff"]
    baseline_label: str = "baseline"
    candidate_label: str = "candidate"
    baseline_series: list[float] = Field(default_factory=list)
    candidate_series: list[float] = Field(default_factory=list)
    baseline_record: dict[str, TableCell] = Field(default_factory=dict)
    candidate_record: dict[str, TableCell] = Field(default_factory=dict)
    abs_tolerance: float = Field(default=1e-6, ge=0.0)
    rel_tolerance: float = Field(default=0.01, ge=0.0)
    contains_personal_vault_data: bool = True


class FieldDelta(BaseModel):
    """Per-key or per-index comparison delta record."""

    key: str
    status: Literal["matched", "modified", "added", "removed", "tolerance_exceeded"]
    baseline_value: TableCell = None
    candidate_value: TableCell = None
    abs_delta: float | None = None
    rel_delta: float | None = None


class NumericErrorMetrics(BaseModel):
    """Regression and error metrics computed across paired baseline/candidate vectors."""

    sample_count: int = Field(ge=0)
    mae: float = Field(ge=0.0)
    rmse: float = Field(ge=0.0)
    max_abs_error: float = Field(ge=0.0)
    mape_percent: float | None = Field(default=None, ge=0.0)
    pearson_r: float | None = Field(default=None, ge=-1.0, le=1.0)
    r_squared: float | None = None
    within_tolerance_count: int = Field(ge=0)
    total_compared: int = Field(ge=0)


class DataComparisonOutput(BaseModel):
    """Output schema returned by ``data_comparison_function``."""

    slice_id: str
    comparison_mode: str
    all_within_tolerance: bool
    numeric_metrics: NumericErrorMetrics | None = None
    field_deltas: list[FieldDelta] = Field(default_factory=list)
    summary: str
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


def _compute_numeric_series_metrics(
    baseline: Sequence[float],
    candidate: Sequence[float],
    abs_tol: float,
    rel_tol: float,
) -> tuple[NumericErrorMetrics, list[FieldDelta]]:
    if not baseline or len(baseline) != len(candidate):
        raise ValueError(
            "baseline_series and candidate_series must be non-empty sequences of equal length."
        )
    if any(not math.isfinite(v) for v in baseline) or any(not math.isfinite(v) for v in candidate):
        raise ValueError("Series values must all be finite floats.")

    n = len(baseline)
    errors = [cand - base for base, cand in zip(baseline, candidate)]
    abs_errors = [abs(err) for err in errors]
    mae = statistics.fmean(abs_errors)
    rmse = math.sqrt(statistics.fmean(err * err for err in errors))
    max_abs_error = max(abs_errors)

    nonzero_rel = [
        abs_err / abs(base)
        for base, abs_err in zip(baseline, abs_errors)
        if base != 0.0
    ]
    mape_percent = (100.0 * statistics.fmean(nonzero_rel)) if nonzero_rel else None

    mean_base = statistics.fmean(baseline)
    mean_cand = statistics.fmean(candidate)
    ss_tot = math.fsum((base - mean_base) ** 2 for base in baseline)
    ss_cand = math.fsum((cand - mean_cand) ** 2 for cand in candidate)
    ss_res = math.fsum(err * err for err in errors)

    r_squared = (1.0 - (ss_res / ss_tot)) if ss_tot > 0.0 else None
    if ss_tot > 0.0 and ss_cand > 0.0:
        cov = math.fsum(
            (base - mean_base) * (cand - mean_cand)
            for base, cand in zip(baseline, candidate)
        )
        raw_r = cov / math.sqrt(ss_tot * ss_cand)
        pearson_r: float | None = max(-1.0, min(1.0, raw_r))
    else:
        pearson_r = None

    within_count = 0
    exceeded_deltas: list[FieldDelta] = []
    for idx, (base, cand, abs_err) in enumerate(zip(baseline, candidate, abs_errors)):
        tol_bound = abs_tol + rel_tol * abs(base)
        if abs_err <= tol_bound:
            within_count += 1
        else:
            rel_err = (abs_err / abs(base)) if base != 0.0 else None
            exceeded_deltas.append(
                FieldDelta(
                    key=f"[{idx}]",
                    status="tolerance_exceeded",
                    baseline_value=base,
                    candidate_value=cand,
                    abs_delta=abs_err,
                    rel_delta=rel_err,
                )
            )

    metrics = NumericErrorMetrics(
        sample_count=n,
        mae=mae,
        rmse=rmse,
        max_abs_error=max_abs_error,
        mape_percent=mape_percent,
        pearson_r=pearson_r,
        r_squared=r_squared,
        within_tolerance_count=within_count,
        total_compared=n,
    )
    return metrics, exceeded_deltas


def data_comparison_function(payload: DataComparisonInput) -> DataComparisonOutput:
    """Compare numeric series, key-value records, or table diffs deterministically."""
    t0 = time.perf_counter()

    if payload.comparison_mode == "numeric_series":
        metrics, exceeded = _compute_numeric_series_metrics(
            payload.baseline_series,
            payload.candidate_series,
            payload.abs_tolerance,
            payload.rel_tolerance,
        )
        all_ok = metrics.within_tolerance_count == metrics.total_compared
        summary = (
            f"{payload.baseline_label} vs {payload.candidate_label}: "
            f"n={metrics.sample_count}, MAE={metrics.mae:.6g}, RMSE={metrics.rmse:.6g}, "
            f"within_tol={metrics.within_tolerance_count}/{metrics.total_compared}."
        )
        return DataComparisonOutput(
            slice_id=payload.slice_id,
            comparison_mode=payload.comparison_mode,
            all_within_tolerance=all_ok,
            numeric_metrics=metrics,
            field_deltas=exceeded,
            summary=summary,
            execution_time_ms=_elapsed_ms(t0),
        )

    # key_value_records or table_diff
    has_records = bool(payload.baseline_record or payload.candidate_record)
    has_series = bool(payload.baseline_series or payload.candidate_series)
    if not has_records and not has_series:
        raise ValueError(
            f"{payload.comparison_mode} requires non-empty records or paired numeric series."
        )

    field_deltas: list[FieldDelta] = []
    all_within_tolerance = True
    paired_base_nums: list[float] = []
    paired_cand_nums: list[float] = []

    if has_records:
        ordered_keys: list[str] = list(payload.baseline_record.keys())
        seen_keys = set(ordered_keys)
        for key in payload.candidate_record:
            if key not in seen_keys:
                ordered_keys.append(key)
                seen_keys.add(key)

        for key in ordered_keys:
            in_base = key in payload.baseline_record
            in_cand = key in payload.candidate_record
            if not in_base:
                all_within_tolerance = False
                field_deltas.append(
                    FieldDelta(
                        key=key,
                        status="added",
                        baseline_value=None,
                        candidate_value=payload.candidate_record[key],
                    )
                )
                continue
            if not in_cand:
                all_within_tolerance = False
                field_deltas.append(
                    FieldDelta(
                        key=key,
                        status="removed",
                        baseline_value=payload.baseline_record[key],
                        candidate_value=None,
                    )
                )
                continue

            base_val = payload.baseline_record[key]
            cand_val = payload.candidate_record[key]
            if _is_numeric(base_val) and _is_numeric(cand_val):
                b_num = float(cast(float | int, base_val))
                c_num = float(cast(float | int, cand_val))
                paired_base_nums.append(b_num)
                paired_cand_nums.append(c_num)
                abs_d = abs(c_num - b_num)
                rel_d = (abs_d / abs(b_num)) if b_num != 0.0 else (0.0 if abs_d == 0.0 else None)
                tol_bound = payload.abs_tolerance + payload.rel_tolerance * abs(b_num)
                if abs_d == 0.0:
                    status: Literal[
                        "matched", "modified", "added", "removed", "tolerance_exceeded"
                    ] = "matched"
                elif abs_d <= tol_bound:
                    status = "modified"
                else:
                    status = "tolerance_exceeded"
                    all_within_tolerance = False
                field_deltas.append(
                    FieldDelta(
                        key=key,
                        status=status,
                        baseline_value=base_val,
                        candidate_value=cand_val,
                        abs_delta=abs_d,
                        rel_delta=rel_d,
                    )
                )
            else:
                same_bool = isinstance(base_val, bool) == isinstance(cand_val, bool)
                is_equal = same_bool and base_val == cand_val
                if not is_equal:
                    all_within_tolerance = False
                field_deltas.append(
                    FieldDelta(
                        key=key,
                        status="matched" if is_equal else "modified",
                        baseline_value=base_val,
                        candidate_value=cand_val,
                    )
                )

    numeric_metrics: NumericErrorMetrics | None = None
    if has_series:
        numeric_metrics, series_exceeded = _compute_numeric_series_metrics(
            payload.baseline_series,
            payload.candidate_series,
            payload.abs_tolerance,
            payload.rel_tolerance,
        )
        field_deltas.extend(series_exceeded)
        if numeric_metrics.within_tolerance_count < numeric_metrics.total_compared:
            all_within_tolerance = False
    elif paired_base_nums:
        numeric_metrics, _ = _compute_numeric_series_metrics(
            paired_base_nums,
            paired_cand_nums,
            payload.abs_tolerance,
            payload.rel_tolerance,
        )

    matched_count = sum(1 for d in field_deltas if d.status == "matched")
    summary = (
        f"{payload.baseline_label} vs {payload.candidate_label} ({payload.comparison_mode}): "
        f"{matched_count}/{len(field_deltas)} deltas matched, "
        f"all_within_tolerance={all_within_tolerance}."
    )
    return DataComparisonOutput(
        slice_id=payload.slice_id,
        comparison_mode=payload.comparison_mode,
        all_within_tolerance=all_within_tolerance,
        numeric_metrics=numeric_metrics,
        field_deltas=field_deltas,
        summary=summary,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.4 pdf_converter_function (#PDF_CONVERT)
# ---------------------------------------------------------------------------


class PdfPageArtifact(BaseModel):
    """Structured per-page text and structural telemetry extracted from a local PDF."""

    page_number: int = Field(ge=1)
    char_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    extracted_text: str
    detected_headings: list[str] = Field(default_factory=list)
    detected_tables_count: int = Field(default=0, ge=0)


class PdfConverterInput(BaseModel):
    """Input schema for strictly local, zero-LLM PDF parsing and Markdown cleaning."""

    slice_id: str
    source_path: str | None = None
    raw_extracted_pages: list[str] | None = None
    page_range: tuple[int, int] | None = None
    output_format: Literal["markdown", "plain_text", "page_chunks"] = "markdown"
    normalize_whitespace: bool = True
    dehyphenate_linebreaks: bool = True
    strip_headers_footers: bool = True
    contains_personal_vault_data: bool = True

    @field_validator("page_range")
    @classmethod
    def _validate_page_range(
        cls,
        value: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        if value is not None:
            start, end = value
            if start < 1 or start > end:
                raise ValueError("page_range must satisfy 1 <= start <= end.")
        return value


class PdfConverterOutput(BaseModel):
    """Output schema returned by ``pdf_converter_function``."""

    slice_id: str
    source_sha256: str
    total_pages: int = Field(ge=0)
    converted_pages: list[PdfPageArtifact] = Field(default_factory=list)
    combined_markdown: str
    detected_dois: list[str] = Field(default_factory=list)
    detected_equations_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


def _reject_remote_source_path(source_path: str) -> None:
    stripped = source_path.strip()
    parsed = urlparse(stripped)
    if parsed.scheme.lower() in {"http", "https", "ftp"} or stripped.lower().startswith(
        ("http://", "https://")
    ):
        raise ValueError(
            f"Remote URL source_path is prohibited in offline PDF tools: {source_path!r}"
        )


def _extract_pages_from_pdf_bytes(raw_bytes: bytes) -> list[str]:
    try:
        from pypdf import PasswordType, PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        pypdf_available = False
    else:
        pypdf_available = True

    if pypdf_available:
        try:
            reader = PdfReader(io.BytesIO(raw_bytes), strict=True)
            if reader.is_encrypted:
                decrypt_status = reader.decrypt("")
                if decrypt_status == PasswordType.NOT_DECRYPTED:
                    raise PermissionError("PDF document is encrypted and requires a password.")
            return [page.extract_text() or "" for page in reader.pages]
        except PyPdfError as exc:
            raise ValueError(f"Failed to parse PDF with pypdf strict mode: {exc}") from exc

    try:
        fitz_mod = importlib.import_module("fitz")
    except ImportError as exc:
        raise RuntimeError(
            "Neither pypdf nor pymupdf is installed to parse binary PDF files."
        ) from exc

    doc = fitz_mod.open(stream=raw_bytes, filetype="pdf")
    try:
        if getattr(doc, "needs_pass", False):
            raise PermissionError("PDF document is encrypted and requires a password.")
        return [str(page.get_text("text") or "") for page in doc]
    finally:
        doc.close()


def _strip_repeated_headers_footers(pages_text: list[str]) -> list[str]:
    total = len(pages_text)
    if total < 3:
        return pages_text

    threshold = math.ceil(0.6 * total)
    top_counts: Counter[str] = Counter()
    bottom_counts: Counter[str] = Counter()
    split_pages: list[list[str]] = []

    for text in pages_text:
        lines = text.replace("\r\n", "\n").splitlines()
        split_pages.append(lines)
        non_empty = [ln.strip() for ln in lines if ln.strip()]
        if not non_empty:
            continue
        top_counts[non_empty[0]] += 1
        if len(non_empty) >= 2:
            bottom_counts[non_empty[-1]] += 1

    header_candidates = {line for line, count in top_counts.items() if count >= threshold}
    footer_candidates = {line for line, count in bottom_counts.items() if count >= threshold}
    if not header_candidates and not footer_candidates:
        return pages_text

    cleaned_pages: list[str] = []
    for lines in split_pages:
        non_empty_indices = [idx for idx, ln in enumerate(lines) if ln.strip()]
        drop_indices: set[int] = set()
        if non_empty_indices:
            first_idx = non_empty_indices[0]
            if lines[first_idx].strip() in header_candidates:
                drop_indices.add(first_idx)
        if len(non_empty_indices) >= 2:
            last_idx = non_empty_indices[-1]
            if lines[last_idx].strip() in footer_candidates:
                drop_indices.add(last_idx)
        kept = [ln for idx, ln in enumerate(lines) if idx not in drop_indices]
        cleaned_pages.append("\n".join(kept))
    return cleaned_pages


def _detect_page_headings(text: str) -> list[str]:
    headings: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 100:
            continue
        candidate: str | None = None
        md_match = re.match(r"^#{1,6}\s+(.+)$", line)
        if md_match:
            candidate = md_match.group(1).strip()
        elif re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9 ,:\-()/]{2,80}$", line) or (
            re.match(r"^[A-Z][A-Z0-9\s\-:]{3,60}$", line) and any(c.isalpha() for c in line)
        ):
            candidate = line
        if candidate and candidate not in seen:
            seen.add(candidate)
            headings.append(candidate)
    return headings


def _count_page_tables(text: str) -> int:
    table_blocks = 0
    in_pipe_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if "|" in stripped and (stripped.startswith("|") or stripped.count("|") >= 2):
            if not in_pipe_block:
                table_blocks += 1
                in_pipe_block = True
        else:
            in_pipe_block = False
            if re.match(r"^Table\s+\d+(?:\.\d+)?[:.\s]", stripped, re.IGNORECASE):
                table_blocks += 1
    return table_blocks


def _count_page_equations(text: str) -> int:
    display_blocks = len(re.findall(r"\$\$.+?\$\$|\\\[.+?\\\]", text, re.DOTALL))
    numbered_eqs = len(
        re.findall(r"(?:^|\s)(?:Eq\.?|Equation)\s*\(?\d+(?:\.\d+)?\)?", text)
    )
    tagged_lines = len(re.findall(r"^.*=.*\(\d+(?:\.\d+)?\)\s*$", text, re.MULTILINE))
    return display_blocks + numbered_eqs + tagged_lines


def pdf_converter_function(payload: PdfConverterInput) -> PdfConverterOutput:
    """Convert local PDF files or raw extracted pages into cleaned Markdown and page artifacts."""
    t0 = time.perf_counter()
    warnings: list[str] = []

    if payload.source_path is not None:
        _reject_remote_source_path(payload.source_path)

    if payload.source_path is None and payload.raw_extracted_pages is None:
        raise ValueError("Either source_path or raw_extracted_pages must be provided.")

    if payload.raw_extracted_pages is not None:
        raw_pages = list(payload.raw_extracted_pages)
        source_sha256 = hashlib.sha256("\n".join(raw_pages).encode("utf-8")).hexdigest()
    else:
        assert payload.source_path is not None
        pdf_path = Path(payload.source_path)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Local PDF file not found: {pdf_path}")
        raw_bytes = pdf_path.read_bytes()
        source_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        raw_pages = _extract_pages_from_pdf_bytes(raw_bytes)

    total_pages = len(raw_pages)
    processed_pages = list(raw_pages)
    if payload.strip_headers_footers:
        processed_pages = _strip_repeated_headers_footers(processed_pages)

    selected_indices: list[int]
    if payload.page_range is not None:
        start_p, end_p = payload.page_range
        selected_indices = [
            idx for idx in range(total_pages) if start_p <= (idx + 1) <= end_p
        ]
        if start_p > total_pages:
            warnings.append(
                f"Requested page_range {payload.page_range} exceeds total_pages={total_pages}."
            )
    else:
        selected_indices = list(range(total_pages))

    converted_pages: list[PdfPageArtifact] = []
    dois_seen: set[str] = set()
    detected_dois: list[str] = []
    total_equations = 0

    for idx in selected_indices:
        text = processed_pages[idx].replace("\r\n", "\n")
        if payload.dehyphenate_linebreaks:
            text = re.sub(r"([A-Za-z])-\r?\n([a-z])", r"\1\2", text)
        if payload.normalize_whitespace:
            lines = [re.sub(r"[ \t]{2,}", " ", ln.rstrip()) for ln in text.splitlines()]
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        headings = _detect_page_headings(text)
        tables_count = _count_page_tables(text)
        total_equations += _count_page_equations(text)
        for match in _DOI_REGEX.findall(text):
            cleaned_doi = match.rstrip(".,;:")
            if cleaned_doi not in dois_seen:
                dois_seen.add(cleaned_doi)
                detected_dois.append(cleaned_doi)
        converted_pages.append(
            PdfPageArtifact(
                page_number=idx + 1,
                char_count=len(text),
                word_count=len(text.split()),
                extracted_text=text,
                detected_headings=headings,
                detected_tables_count=tables_count,
            )
        )

    if payload.output_format == "markdown":
        combined = "\n\n---\n\n".join(
            f"## Page {page.page_number}\n\n{page.extracted_text}"
            for page in converted_pages
        )
    elif payload.output_format == "plain_text":
        combined = "\n\n".join(page.extracted_text for page in converted_pages)
    else:
        combined = "\n\n".join(
            f"<!-- page:{page.page_number} -->\n{page.extracted_text}"
            for page in converted_pages
        )

    return PdfConverterOutput(
        slice_id=payload.slice_id,
        source_sha256=source_sha256,
        total_pages=total_pages,
        converted_pages=converted_pages,
        combined_markdown=combined,
        detected_dois=detected_dois,
        detected_equations_count=total_equations,
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.5 smart_pdf_handling_function (#SMART_PDF_LINK)
# ---------------------------------------------------------------------------


class PdfSectionNode(BaseModel):
    """Indexed PDF section node with Okapi BM25 score and W_i decay priority."""

    section_id: str
    heading: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text_excerpt: str
    relevance_score: float = Field(default=0.0, ge=0.0)
    decay_weight_wi: float = Field(default=1.0, ge=0.0)
    linked_citations: list[str] = Field(default_factory=list)
    linked_equations: list[str] = Field(default_factory=list)
    linked_tables: list[str] = Field(default_factory=list)


class SmartPdfEdge(BaseModel):
    """Typed cross-reference edge discovered within or across PDF pages."""

    source_section_id: str
    target_ref: str
    relation: Literal[
        "cites",
        "references_table",
        "references_figure",
        "references_equation",
        "continues_topic",
    ]
    page_number: int = Field(ge=1)


class SmartPdfInput(BaseModel):
    """Input schema for Okapi BM25 ranking, cross-link extraction, and W_i weighting."""

    slice_id: str
    pages: list[PdfPageArtifact] = Field(min_length=1)
    source_path: str | None = None
    query: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    decay_rate: float = Field(default=0.05, ge=0.0)
    alpha: float = Field(default=0.15, ge=0.0)
    contains_personal_vault_data: bool = True


class SmartPdfOutput(BaseModel):
    """Output schema returned by ``smart_pdf_handling_function``."""

    slice_id: str
    sections: list[PdfSectionNode]
    top_matching_sections: list[PdfSectionNode] = Field(default_factory=list)
    cross_links: list[SmartPdfEdge] = Field(default_factory=list)
    citation_keys_found: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


_CITATION_BRACKET_RE = re.compile(r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]")
_TABLE_REF_RE = re.compile(r"\bTable\s+(\d+(?:\.\d+|[A-Za-z])?)(?!\w)", re.IGNORECASE)
_FIG_REF_RE = re.compile(r"\b(?:Fig\.?|Figure)\s+(\d+(?:\.\d+|[A-Za-z])?)(?!\w)", re.IGNORECASE)
_EQ_REF_RE = re.compile(
    r"\b(?:Eq\.?|Equation)\s*\(?(\d+(?:\.\d+|[A-Za-z])?)\)?(?!\w)",
    re.IGNORECASE,
)


def _tokenize_bm25(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _expand_bracket_citation(inner: str) -> list[str]:
    keys: list[str] = []
    for part in inner.split(","):
        cleaned = part.strip()
        range_match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", cleaned)
        if range_match:
            start_n = int(range_match.group(1))
            end_n = int(range_match.group(2))
            if 0 < end_n - start_n <= 20:
                keys.extend(f"[{num}]" for num in range(start_n, end_n + 1))
            else:
                keys.append(f"[{cleaned}]")
        elif cleaned:
            keys.append(f"[{cleaned}]")
    return keys


def _split_page_into_raw_sections(
    page: PdfPageArtifact,
    prev_heading: str | None,
) -> list[tuple[str, str]]:
    heading_set = {h.strip() for h in page.detected_headings if h.strip()}
    lines = page.extracted_text.splitlines()
    chunks: list[tuple[str, list[str]]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        md_match = re.match(r"^#{1,6}\s+(.+)$", stripped)
        matched_heading: str | None = None
        if md_match and (not heading_set or md_match.group(1).strip() in heading_set):
            matched_heading = md_match.group(1).strip()
        elif stripped in heading_set or (
            not heading_set
            and re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9 ,:\-()/]{2,80}$", stripped)
        ):
            matched_heading = stripped

        if matched_heading is not None:
            if current_lines or current_heading is not None:
                fallback = (
                    f"{prev_heading} (p. {page.page_number})"
                    if prev_heading
                    else f"Page {page.page_number}"
                )
                chunks.append((current_heading or fallback, current_lines))
            current_heading = matched_heading
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines or current_heading is not None:
        fallback = (
            f"{prev_heading} (p. {page.page_number})"
            if prev_heading
            else f"Page {page.page_number}"
        )
        chunks.append((current_heading or fallback, current_lines))

    if not chunks:
        fallback = (
            f"{prev_heading} (p. {page.page_number})"
            if prev_heading
            else f"Page {page.page_number}"
        )
        return [(fallback, page.extracted_text)]

    return [(heading, "\n".join(body).strip()) for heading, body in chunks]


def _extract_native_pdf_links(
    source_path: str,
    page_numbers: Sequence[int],
    page_to_section_id: Mapping[int, str],
) -> list[SmartPdfEdge]:
    _reject_remote_source_path(source_path)
    path = Path(source_path)
    if not path.is_file():
        return []
    try:
        from pypdf import PageObject, PasswordType, PdfReader
        from pypdf.errors import PyPdfError
        from pypdf.generic import ArrayObject, Destination, DictionaryObject
    except ImportError:
        return []

    edges: list[SmartPdfEdge] = []
    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            return []
        num_pages = len(reader.pages)
        named_dests = reader.named_destinations

        for page_num in page_numbers:
            page_idx = page_num - 1
            if not (0 <= page_idx < num_pages):
                continue
            annots = reader.pages[page_idx].annotations
            if not annots:
                continue
            source_sec = page_to_section_id.get(page_num, f"sec-{page_num}")
            for raw_annot in annots:
                annot = raw_annot.get_object()
                if not isinstance(annot, DictionaryObject) or annot.get("/Subtype") != "/Link":
                    continue
                dest: Any = annot.get("/Dest")
                if dest is None and "/A" in annot:
                    action = annot["/A"].get_object()
                    if isinstance(action, DictionaryObject):
                        subtype = action.get("/S")
                        if subtype == "/URI":
                            uri = str(action.get("/URI", "")).strip()
                            if uri:
                                edges.append(
                                    SmartPdfEdge(
                                        source_section_id=source_sec,
                                        target_ref=uri,
                                        relation="cites",
                                        page_number=page_num,
                                    )
                                )
                            continue
                        if subtype == "/GoTo":
                            dest = action.get("/D")
                if dest is not None and hasattr(dest, "get_object"):
                    dest = dest.get_object()
                target_page_idx: int | None = None
                if isinstance(dest, bytes):
                    dest = dest.decode("utf-8", errors="replace")
                if isinstance(dest, str):
                    named = named_dests.get(dest)
                    if named is not None:
                        target_page_idx = reader.get_destination_page_number(named)
                elif isinstance(dest, Destination):
                    target_page_idx = reader.get_destination_page_number(dest)
                elif isinstance(dest, ArrayObject) and len(dest) > 0:
                    page_obj = dest[0].get_object()
                    if isinstance(page_obj, PageObject) or (
                        isinstance(page_obj, DictionaryObject)
                        and page_obj.get("/Type") == "/Page"
                    ):
                        target_page_idx = reader.get_page_number(
                            cast(PageObject, page_obj)
                        )
                if target_page_idx is not None:
                    edges.append(
                        SmartPdfEdge(
                            source_section_id=source_sec,
                            target_ref=f"page:{target_page_idx + 1}",
                            relation="continues_topic",
                            page_number=page_num,
                        )
                    )
    except (PyPdfError, OSError, ValueError):
        return edges
    return edges


def smart_pdf_handling_function(payload: SmartPdfInput) -> SmartPdfOutput:
    """Segment PDF pages into sections, extract cross-links, and rank with BM25 + W_i."""
    t0 = time.perf_counter()
    if payload.source_path is not None:
        _reject_remote_source_path(payload.source_path)

    raw_sections: list[tuple[str, str, int, str]] = []
    prev_heading: str | None = None
    page_to_first_section: dict[int, str] = {}

    for page in payload.pages:
        page_chunks = _split_page_into_raw_sections(page, prev_heading)
        for heading, text in page_chunks:
            sec_id = f"sec-{len(raw_sections) + 1}"
            raw_sections.append((sec_id, heading, page.page_number, text))
            page_to_first_section.setdefault(page.page_number, sec_id)
            prev_heading = heading

    cross_links: list[SmartPdfEdge] = []
    citation_keys_found: list[str] = []
    seen_citation_keys: set[str] = set()
    section_nodes: list[PdfSectionNode] = []
    section_tokens: list[list[str]] = []
    edges_per_section: Counter[str] = Counter()

    for idx, (sec_id, heading, page_num, text) in enumerate(raw_sections):
        linked_citations: list[str] = []
        linked_equations: list[str] = []
        linked_tables: list[str] = []
        seen_cites: set[str] = set()
        seen_eqs: set[str] = set()
        seen_tabs: set[str] = set()

        for match in _CITATION_BRACKET_RE.finditer(text):
            for cite_key in _expand_bracket_citation(match.group(1)):
                if cite_key not in seen_cites:
                    seen_cites.add(cite_key)
                    linked_citations.append(cite_key)
                if cite_key not in seen_citation_keys:
                    seen_citation_keys.add(cite_key)
                    citation_keys_found.append(cite_key)
                cross_links.append(
                    SmartPdfEdge(
                        source_section_id=sec_id,
                        target_ref=cite_key,
                        relation="cites",
                        page_number=page_num,
                    )
                )
                edges_per_section[sec_id] += 1

        for match in _TABLE_REF_RE.finditer(text):
            ref = f"Table {match.group(1)}"
            if ref not in seen_tabs:
                seen_tabs.add(ref)
                linked_tables.append(ref)
            cross_links.append(
                SmartPdfEdge(
                    source_section_id=sec_id,
                    target_ref=ref,
                    relation="references_table",
                    page_number=page_num,
                )
            )
            edges_per_section[sec_id] += 1

        for match in _FIG_REF_RE.finditer(text):
            ref = f"Fig. {match.group(1)}"
            cross_links.append(
                SmartPdfEdge(
                    source_section_id=sec_id,
                    target_ref=ref,
                    relation="references_figure",
                    page_number=page_num,
                )
            )
            edges_per_section[sec_id] += 1

        for match in _EQ_REF_RE.finditer(text):
            ref = f"Eq. {match.group(1)}"
            if ref not in seen_eqs:
                seen_eqs.add(ref)
                linked_equations.append(ref)
            cross_links.append(
                SmartPdfEdge(
                    source_section_id=sec_id,
                    target_ref=ref,
                    relation="references_equation",
                    page_number=page_num,
                )
            )
            edges_per_section[sec_id] += 1

        if idx > 0 and f"(p. {page_num})" in heading:
            prev_sec_id = raw_sections[idx - 1][0]
            cross_links.append(
                SmartPdfEdge(
                    source_section_id=sec_id,
                    target_ref=prev_sec_id,
                    relation="continues_topic",
                    page_number=page_num,
                )
            )
            edges_per_section[sec_id] += 1

        full_text_for_index = f"{heading}\n{text}".strip()
        section_tokens.append(_tokenize_bm25(full_text_for_index))
        section_nodes.append(
            PdfSectionNode(
                section_id=sec_id,
                heading=heading,
                page_start=page_num,
                page_end=page_num,
                text_excerpt=text[:600],
                linked_citations=linked_citations,
                linked_equations=linked_equations,
                linked_tables=linked_tables,
            )
        )

    if payload.source_path is not None:
        native_edges = _extract_native_pdf_links(
            payload.source_path,
            [p.page_number for p in payload.pages],
            page_to_first_section,
        )
        for edge in native_edges:
            cross_links.append(edge)
            edges_per_section[edge.source_section_id] += 1

    # Okapi BM25 (k1 = 1.5, b = 0.75)
    query_tokens = list(dict.fromkeys(_tokenize_bm25(payload.query or "")))
    n_sec = len(section_nodes)
    if query_tokens and n_sec > 0:
        k1 = 1.5
        b_norm = 0.75
        avg_len = max(1.0, statistics.fmean(len(toks) for toks in section_tokens))
        df_counts: dict[str, int] = {
            term: sum(1 for toks in section_tokens if term in toks)
            for term in query_tokens
        }
        tf_maps = [Counter(toks) for toks in section_tokens]
        for idx, node in enumerate(section_nodes):
            doc_len = len(section_tokens[idx])
            if doc_len == 0:
                node.relevance_score = 0.0
                continue
            tf_counter = tf_maps[idx]
            score = 0.0
            for term in query_tokens:
                tf = tf_counter[term]
                if tf == 0:
                    continue
                df = df_counts[term]
                idf = math.log(((n_sec - df + 0.5) / (df + 0.5)) + 1.0)
                denom = tf + k1 * (1.0 - b_norm + b_norm * (doc_len / avg_len))
                score += idf * ((tf * (k1 + 1.0)) / denom)
            node.relevance_score = max(0.0, score)

    for node in section_nodes:
        r_i = edges_per_section[node.section_id]
        node.decay_weight_wi = compute_decay_weight(
            initial_weight=1.0 + node.relevance_score,
            decay_rate=payload.decay_rate,
            elapsed_hours=0.0,
            alpha=payload.alpha,
            resonance_count=r_i,
        )

    ranked = sorted(
        section_nodes,
        key=lambda n: (-n.relevance_score, -n.decay_weight_wi, n.page_start),
    )

    return SmartPdfOutput(
        slice_id=payload.slice_id,
        sections=section_nodes,
        top_matching_sections=ranked[: payload.top_k],
        cross_links=cross_links,
        citation_keys_found=citation_keys_found,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.6 coding_optimiser_function (#CODE_OPTIMISE)
# ---------------------------------------------------------------------------


class CodeFinding(BaseModel):
    """Static AST / Yggdrasil QA finding emitted by ``coding_optimiser_function``."""

    rule_id: str
    severity: Literal["info", "warning", "error", "critical"]
    line_number: int = Field(ge=1)
    symbol_name: str = ""
    message: str
    deterministic_fix_hint: str = ""


class FunctionMetric(BaseModel):
    """Per-function McCabe complexity, nesting depth, and annotation completeness."""

    name: str
    is_async: bool
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    cyclomatic_complexity: int = Field(ge=1)
    max_nesting_depth: int = Field(ge=0)
    has_complete_type_annotations: bool


class CodingOptimiserInput(BaseModel):
    """Input schema for pure-Python AST complexity & Yggdrasil QA static checks."""

    slice_id: str
    source_code: str = Field(min_length=1)
    language: Literal["python"] = "python"
    max_cyclomatic_complexity: int = Field(default=10, ge=1)
    max_nesting_depth: int = Field(default=4, ge=1)
    enforce_yggdrasil_qa_rules: bool = True
    contains_personal_vault_data: bool = True


class CodingOptimiserOutput(BaseModel):
    """Output schema returned by ``coding_optimiser_function``."""

    slice_id: str
    syntax_valid: bool
    syntax_error: str | None = None
    loc: int = Field(ge=0)
    function_metrics: list[FunctionMetric] = Field(default_factory=list)
    findings: list[CodeFinding] = Field(default_factory=list)
    maintainability_score: float = Field(default=100.0, ge=0.0, le=100.0)
    passes_qa_static_gate: bool
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


_SYNC_HTTPX_METHODS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "request"}
)
_SUBPROCESS_BLOCKING = frozenset({"run", "call", "check_call", "check_output", "Popen"})


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _is_mutable_default(node: ast.expr | None) -> bool:
    if node is None:
        return False
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "dict", "set"}
    return False


def _has_complete_annotations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    in_class: bool,
) -> bool:
    if node.returns is None:
        return False
    all_args = [*node.args.posonlyargs, *node.args.args]
    for idx, arg in enumerate(all_args):
        if in_class and idx == 0 and arg.arg in {"self", "cls"}:
            continue
        if arg.annotation is None:
            return False
    for arg in node.args.kwonlyargs:
        if arg.annotation is None:
            return False
    if node.args.vararg is not None and node.args.vararg.annotation is None:
        return False
    return not (node.args.kwarg is not None and node.args.kwarg.annotation is None)


def _is_blocking_call_name(call_name: str) -> bool:
    if call_name in {"time.sleep", "urllib.request.urlopen", "urlopen"}:
        return True
    if call_name.startswith("requests."):
        return True
    if call_name.startswith("subprocess.") and call_name.split(".", 1)[1] in _SUBPROCESS_BLOCKING:
        return True
    return (
        call_name.startswith("httpx.")
        and call_name.split(".", 1)[1] in _SYNC_HTTPX_METHODS
    )


class _ScopeState:
    def __init__(self, name: str, is_async: bool, line_start: int) -> None:
        self.name = name
        self.is_async = is_async
        self.line_start = line_start
        self.complexity = 1
        self.loop_depth = 0
        self.max_nesting = 0
        self.personal_vault_line: int | None = None
        self.cloud_llm_line: int | None = None


class _YggdrasilAstAuditor(ast.NodeVisitor):
    """Scope-isolated Python AST auditor for McCabe complexity, nesting, and QA rules."""

    def __init__(self, max_mccabe: int, max_nesting: int, enforce_ygg: bool) -> None:
        self.max_mccabe = max_mccabe
        self.max_nesting = max_nesting
        self.enforce_ygg = enforce_ygg
        self.function_metrics: list[FunctionMetric] = []
        self.findings: list[CodeFinding] = []
        self._scopes: list[_ScopeState] = [_ScopeState("<module>", is_async=False, line_start=1)]
        self._class_stack: list[str] = []
        self._offloaded_depth = 0

    @property
    def _current(self) -> _ScopeState:
        return self._scopes[-1]

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_async = isinstance(node, ast.AsyncFunctionDef)
        in_class = bool(self._class_stack)

        # Check defaults in outer scope before entering body.
        for default_expr in [*node.args.defaults, *node.args.kw_defaults]:
            if _is_mutable_default(default_expr):
                self.findings.append(
                    CodeFinding(
                        rule_id="PY-MUTABLE-005",
                        severity="error",
                        line_number=node.lineno,
                        symbol_name=node.name,
                        message=f"Mutable default argument in function {node.name!r}.",
                        deterministic_fix_hint=(
                            "Use None as default and initialize inside the function body, "
                            "or Field(default_factory=...) on Pydantic models."
                        ),
                    )
                )

        complete_types = _has_complete_annotations(node, in_class=in_class)
        if self.enforce_ygg and not node.name.startswith("_") and not complete_types:
            self.findings.append(
                CodeFinding(
                    rule_id="YGG-TYPE-004",
                    severity="warning",
                    line_number=node.lineno,
                    symbol_name=node.name,
                    message=(
                        f"Public function {node.name!r} is missing parameter or return type hints."
                    ),
                    deterministic_fix_hint=(
                        "Add explicit Python >= 3.11 parameter and return annotations."
                    ),
                )
            )

        scope = _ScopeState(name=node.name, is_async=is_async, line_start=node.lineno)
        self._scopes.append(scope)
        try:
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._scopes.pop()

        line_end = max(node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno)
        self.function_metrics.append(
            FunctionMetric(
                name=node.name,
                is_async=is_async,
                line_start=node.lineno,
                line_end=line_end,
                cyclomatic_complexity=scope.complexity,
                max_nesting_depth=scope.max_nesting,
                has_complete_type_annotations=complete_types,
            )
        )

        if scope.complexity > self.max_mccabe or scope.max_nesting > self.max_nesting:
            self.findings.append(
                CodeFinding(
                    rule_id="PY-COMPLEXITY-006",
                    severity="warning",
                    line_number=node.lineno,
                    symbol_name=node.name,
                    message=(
                        f"Function {node.name!r} has cyclomatic complexity={scope.complexity} "
                        f"(max {self.max_mccabe}) and nesting={scope.max_nesting} "
                        f"(max {self.max_nesting})."
                    ),
                    deterministic_fix_hint=(
                        "Extract cohesive helper functions or flatten nested loops."
                    ),
                )
            )

        if (
            self.enforce_ygg
            and scope.personal_vault_line is not None
            and scope.cloud_llm_line is not None
        ):
            self.findings.append(
                CodeFinding(
                    rule_id="YGG-AIRGAP-003",
                    severity="critical",
                    line_number=min(scope.personal_vault_line, scope.cloud_llm_line),
                    symbol_name=node.name,
                    message=(
                        f"Function {node.name!r} references personal_vault alongside "
                        "cloud Gemini/Leaves client."
                    ),
                    deterministic_fix_hint=(
                        "Isolate personal_vault data strictly to local Twigs/Roots "
                        "and block cloud dispatch."
                    ),
                )
            )

    def finalize_module_scope(self) -> None:
        mod_scope = self._scopes[0]
        if (
            self.enforce_ygg
            and mod_scope.personal_vault_line is not None
            and mod_scope.cloud_llm_line is not None
        ):
            self.findings.append(
                CodeFinding(
                    rule_id="YGG-AIRGAP-003",
                    severity="critical",
                    line_number=min(mod_scope.personal_vault_line, mod_scope.cloud_llm_line),
                    symbol_name="<module>",
                    message=(
                        "Module scope references personal_vault alongside "
                        "cloud Gemini/Leaves client."
                    ),
                    deterministic_fix_hint=(
                        "Enforce strict air-gap separation before cloud dispatch."
                    ),
                )
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        self._visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for dec in node.decorator_list:
            self.visit(dec)
        for base in node.bases:
            self.visit(base)
        for kw in node.keywords:
            self.visit(kw)
        self._class_stack.append(node.name)
        saved_depth = self._current.loop_depth
        self._current.loop_depth = 0
        try:
            for stmt in node.body:
                self.visit(stmt)
        finally:
            self._current.loop_depth = saved_depth
            self._class_stack.pop()

    def _visit_loop_stmt(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self._current.complexity += 1
        self._current.loop_depth += 1
        self._current.max_nesting = max(self._current.max_nesting, self._current.loop_depth)
        try:
            self.generic_visit(node)
        finally:
            self._current.loop_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop_stmt(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop_stmt(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop_stmt(node)

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
    ) -> None:
        gen_count = len(node.generators)
        for comp in node.generators:
            self._current.complexity += len(comp.ifs)
        self._current.loop_depth += gen_count
        self._current.max_nesting = max(self._current.max_nesting, self._current.loop_depth)
        try:
            self.generic_visit(node)
        finally:
            self._current.loop_depth -= gen_count

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)

    def visit_If(self, node: ast.If) -> None:
        self._current.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._current.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self._current.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._current.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self._current.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self._current.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def _record_airgap_token(self, token: str, lineno: int) -> None:
        lower = token.lower()
        if "personal_vault" in lower and self._current.personal_vault_line is None:
            self._current.personal_vault_line = lineno
        if (
            token in {"LeavesCloudAgent", "genai.Client", "google.genai"}
            or token.endswith(".LeavesCloudAgent")
            or token.endswith(".Client") and "genai" in lower
        ) and self._current.cloud_llm_line is None:
            self._current.cloud_llm_line = lineno

    def visit_Name(self, node: ast.Name) -> None:
        self._record_airgap_token(node.id, node.lineno)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._record_airgap_token(_dotted_name(node), node.lineno)
        self._record_airgap_token(node.attr, node.lineno)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self._record_airgap_token(node.value, node.lineno)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _dotted_name(node.func)
        self._record_airgap_token(call_name, node.lineno)

        if self.enforce_ygg:
            leaf_name = call_name.rsplit(".", 1)[-1]
            if (
                leaf_name in {"AsyncOpenAI", "OllamaModel"}
                and "LocalEngine" not in self._class_stack
            ):
                self.findings.append(
                    CodeFinding(
                        rule_id="YGG-VRAM-002",
                        severity="error",
                        line_number=node.lineno,
                        symbol_name=self._current.name,
                        message=(
                            f"Direct {leaf_name}() instantiation outside LocalEngine "
                            "risks VRAM contention."
                        ),
                        deterministic_fix_hint=(
                            "Obtain the shared agent via LocalEngine.get_shared()."
                        ),
                    )
                )

            if (
                self._current.is_async
                and self._offloaded_depth == 0
                and _is_blocking_call_name(call_name)
            ):
                self.findings.append(
                    CodeFinding(
                        rule_id="YGG-ASYNC-001",
                        severity="error",
                        line_number=node.lineno,
                        symbol_name=self._current.name,
                        message=(
                            f"Blocking call {call_name}() inside async function "
                            f"{self._current.name!r}."
                        ),
                        deterministic_fix_hint=(
                            "Use httpx.AsyncClient / asyncio.sleep, "
                            "or offload via asyncio.to_thread()."
                        ),
                    )
                )

        if call_name == "asyncio.to_thread" or call_name.endswith(".run_in_executor"):
            self.visit(node.func)
            self._offloaded_depth += 1
            try:
                for arg in node.args:
                    self.visit(arg)
                for kw in node.keywords:
                    self.visit(kw)
            finally:
                self._offloaded_depth -= 1
            return

        self.generic_visit(node)


def coding_optimiser_function(payload: CodingOptimiserInput) -> CodingOptimiserOutput:
    """Analyze Python source code with scope-isolated AST complexity and Yggdrasil QA rules."""
    t0 = time.perf_counter()
    loc = sum(1 for line in payload.source_code.splitlines() if line.strip())

    try:
        tree = ast.parse(payload.source_code, mode="exec")
    except SyntaxError as exc:
        err_msg = f"Line {exc.lineno or 1}: {exc.msg}"
        return CodingOptimiserOutput(
            slice_id=payload.slice_id,
            syntax_valid=False,
            syntax_error=err_msg,
            loc=loc,
            maintainability_score=0.0,
            passes_qa_static_gate=False,
            execution_time_ms=_elapsed_ms(t0),
        )

    auditor = _YggdrasilAstAuditor(
        max_mccabe=payload.max_cyclomatic_complexity,
        max_nesting=payload.max_nesting_depth,
        enforce_ygg=payload.enforce_yggdrasil_qa_rules,
    )
    auditor.visit(tree)
    auditor.finalize_module_scope()

    mean_mccabe = (
        statistics.fmean(m.cyclomatic_complexity for m in auditor.function_metrics)
        if auditor.function_metrics
        else 1.0
    )
    n_err_crit = sum(1 for f in auditor.findings if f.severity in {"error", "critical"})
    n_warn = sum(1 for f in auditor.findings if f.severity == "warning")
    raw_maint = 100.0 - 2.0 * max(0.0, mean_mccabe - 3.0) - 8.0 * n_err_crit - 2.0 * n_warn
    maintainability_score = max(0.0, min(100.0, raw_maint))

    return CodingOptimiserOutput(
        slice_id=payload.slice_id,
        syntax_valid=True,
        syntax_error=None,
        loc=loc,
        function_metrics=auditor.function_metrics,
        findings=auditor.findings,
        maintainability_score=maintainability_score,
        passes_qa_static_gate=(n_err_crit == 0),
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.7 control_system_optimiser_function (#CONTROL_SYSTEM)
# ---------------------------------------------------------------------------

TuningMethodLiteral = Literal["imc", "simc", "ziegler_nichols", "cohen_coon"]


class FopdtModelParams(BaseModel):
    """First-order-plus-dead-time (FOPDT) linear process model parameters."""

    kp: float
    tau: float = Field(gt=0.0)
    theta: float = Field(ge=0.0)
    time_unit: str = "s"

    @field_validator("kp")
    @classmethod
    def _validate_kp_nonzero(cls, value: float) -> float:
        if not math.isfinite(value) or value == 0.0:
            raise ValueError("FOPDT process gain kp must be finite and non-zero.")
        return value


class PidGains(BaseModel):
    """Standard non-interacting PID controller parameters."""

    kc: float
    tau_i: float = Field(ge=0.0)
    tau_d: float = Field(ge=0.0)
    ki: float
    kd: float
    controller_type: Literal["P", "PI", "PID"]
    tuning_method: TuningMethodLiteral


class StepPerformanceMetrics(BaseModel):
    """Closed-loop step response error integrals and transient performance metrics."""

    iae: float = Field(ge=0.0)
    ise: float = Field(ge=0.0)
    itae: float = Field(ge=0.0)
    overshoot_percent: float = Field(ge=0.0)
    rise_time: float | None = Field(default=None, ge=0.0)
    settling_time: float | None = Field(default=None, ge=0.0)
    steady_state_error: float = Field(ge=0.0)
    is_stable: bool


class TuningCandidateResult(BaseModel):
    """Candidate tuning rule gains paired with exact-ZOH closed-loop simulation metrics."""

    gains: PidGains
    performance: StepPerformanceMetrics


class ControlSystemInput(BaseModel):
    """Input schema for FOPDT two-point identification, PID tuning, and ZOH simulation."""

    slice_id: str
    fopdt: FopdtModelParams | None = None
    step_test_times: list[float] | None = None
    step_test_pv: list[float] | None = None
    step_test_delta_u: float | None = None
    controller_type: Literal["P", "PI", "PID"] = "PID"
    tuning_method: Literal[
        "imc",
        "simc",
        "ziegler_nichols",
        "cohen_coon",
        "auto_best_itae",
    ] = "imc"
    imc_tau_c: float | None = Field(default=None, gt=0.0)
    setpoint_step: float = 1.0
    simulation_horizon: float | None = Field(default=None, gt=0.0)
    dt: float | None = Field(default=None, gt=0.0)
    actuator_min: float | None = None
    actuator_max: float | None = None
    max_overshoot_percent: float = Field(default=25.0, ge=0.0)
    include_trajectory: bool = False
    contains_personal_vault_data: bool = True


class ControlSystemOutput(BaseModel):
    """Output schema returned by ``control_system_optimiser_function``."""

    slice_id: str
    identified_fopdt: FopdtModelParams
    theta_over_tau: float = Field(ge=0.0)
    recommended_gains: PidGains
    performance: StepPerformanceMetrics
    candidate_comparisons: list[TuningCandidateResult] = Field(default_factory=list)
    time_points: list[float] = Field(default_factory=list)
    pv_trajectory: list[float] = Field(default_factory=list)
    mv_trajectory: list[float] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: Literal[True] = True


def _interpolate_crossing_time(
    times: Sequence[float],
    norm_pv: Sequence[float],
    target: float,
) -> float:
    t0 = times[0]
    for idx in range(len(times) - 1):
        y_a = norm_pv[idx]
        y_b = norm_pv[idx + 1]
        if y_a == target:
            return times[idx] - t0
        if (y_a < target <= y_b) or (y_a > target >= y_b):
            denom = y_b - y_a
            frac = 0.0 if denom == 0.0 else (target - y_a) / denom
            return (times[idx] + frac * (times[idx + 1] - times[idx])) - t0
    raise ValueError(f"Step response did not reach normalized level {target:.3f}.")


def _identify_fopdt_smith(
    times: Sequence[float],
    pv: Sequence[float],
    delta_u: float,
) -> FopdtModelParams:
    if len(times) < 3 or len(times) != len(pv):
        raise ValueError("step_test_times and step_test_pv must have equal length >= 3.")
    if delta_u == 0.0 or not math.isfinite(delta_u):
        raise ValueError("step_test_delta_u must be finite and non-zero.")
    for idx in range(len(times) - 1):
        if times[idx + 1] <= times[idx]:
            raise ValueError("step_test_times must be strictly increasing.")

    y0 = pv[0]
    y_inf = pv[-1]
    delta_y = y_inf - y0
    if delta_y == 0.0:
        raise ValueError("Step response shows zero net process change (y_inf == y0).")

    kp = delta_y / delta_u
    norm_pv = [(y - y0) / delta_y for y in pv]
    t_283 = _interpolate_crossing_time(times, norm_pv, 0.283)
    t_632 = _interpolate_crossing_time(times, norm_pv, 0.632)
    tau = 1.5 * (t_632 - t_283)
    if tau <= 0.0:
        raise ValueError("Identified FOPDT time constant tau must be positive.")
    theta = max(0.0, t_632 - tau)
    return FopdtModelParams(kp=kp, tau=tau, theta=theta)


def _compute_pid_gains(
    fopdt: FopdtModelParams,
    controller_type: Literal["P", "PI", "PID"],
    method: TuningMethodLiteral,
    imc_tau_c: float | None,
    warnings: list[str],
) -> PidGains:
    kp, tau, theta = fopdt.kp, fopdt.tau, fopdt.theta
    tau_c = imc_tau_c if imc_tau_c is not None else max(0.25 * tau, 0.8 * theta)

    if method == "imc":
        if controller_type == "P":
            kc = tau / (kp * (tau_c + theta))
            tau_i, tau_d = 0.0, 0.0
        elif controller_type == "PI":
            kc = tau / (kp * (tau_c + theta))
            tau_i, tau_d = tau, 0.0
        else:
            kc = (tau + 0.5 * theta) / (kp * (tau_c + 0.5 * theta))
            tau_i = tau + 0.5 * theta
            tau_d = (tau * theta) / (2.0 * tau + theta)

    elif method == "simc":
        kc = tau / (kp * (tau_c + theta))
        if controller_type == "P":
            tau_i, tau_d = 0.0, 0.0
        else:
            tau_i = min(tau, 4.0 * (tau_c + theta))
            tau_d = 0.0
            if controller_type == "PID":
                warnings.append(
                    "SIMC for FOPDT models is natively PI; tau_d set to 0.0."
                )

    elif method == "ziegler_nichols":
        theta_eff = theta if theta > 0.0 else 1e-3 * tau
        if theta == 0.0:
            warnings.append("Ziegler-Nichols with theta=0 used fallback theta_eff=1e-3*tau.")
        if controller_type == "P":
            kc = tau / (kp * theta_eff)
            tau_i, tau_d = 0.0, 0.0
        elif controller_type == "PI":
            kc = (0.9 * tau) / (kp * theta_eff)
            tau_i, tau_d = (10.0 / 3.0) * theta_eff, 0.0
        else:
            kc = (1.2 * tau) / (kp * theta_eff)
            tau_i, tau_d = 2.0 * theta_eff, 0.5 * theta_eff

    else:  # cohen_coon
        theta_eff = theta if theta > 0.0 else 1e-3 * tau
        if theta == 0.0:
            warnings.append("Cohen-Coon with theta=0 used fallback theta_eff=1e-3*tau.")
        r = theta_eff / tau
        if controller_type == "P":
            kc = (tau / (kp * theta_eff)) * (1.0 + r / 3.0)
            tau_i, tau_d = 0.0, 0.0
        elif controller_type == "PI":
            kc = (tau / (kp * theta_eff)) * (0.9 + r / 12.0)
            tau_i = theta_eff * ((30.0 + 3.0 * r) / (9.0 + 20.0 * r))
            tau_d = 0.0
        else:
            kc = (tau / (kp * theta_eff)) * (4.0 / 3.0 + r / 4.0)
            tau_i = theta_eff * ((32.0 + 6.0 * r) / (13.0 + 8.0 * r))
            tau_d = theta_eff * (4.0 / (11.0 + 2.0 * r))

    ki = (kc / tau_i) if tau_i > 0.0 else 0.0
    kd = kc * tau_d
    return PidGains(
        kc=kc,
        tau_i=tau_i,
        tau_d=tau_d,
        ki=ki,
        kd=kd,
        controller_type=controller_type,
        tuning_method=method,
    )


def _clamp_actuator(
    value: float,
    actuator_min: float | None,
    actuator_max: float | None,
) -> float:
    if actuator_min is not None and value < actuator_min:
        value = actuator_min
    if actuator_max is not None and value > actuator_max:
        value = actuator_max
    return value


def _simulate_closed_loop_zoh(
    fopdt: FopdtModelParams,
    gains: PidGains,
    setpoint_step: float,
    horizon: float | None,
    dt_override: float | None,
    actuator_min: float | None,
    actuator_max: float | None,
) -> tuple[StepPerformanceMetrics, list[float], list[float], list[float]]:
    tau = fopdt.tau
    theta = fopdt.theta
    t_sim = horizon if horizon is not None else max(10.0 * tau, 12.0 * (tau + theta))
    if dt_override is not None:
        dt = dt_override
    else:
        dt = min(0.02 * tau, 0.1 * theta if theta > 0.0 else 0.02 * tau, t_sim / 400.0)
    dt = max(dt, 1e-6)
    n_steps = max(2, round(t_sim / dt))
    delay_steps = max(0, round(theta / dt))

    a_plant = math.exp(-dt / tau)
    b_plant = fopdt.kp * (1.0 - a_plant)
    delay_buf: deque[float] = deque([0.0] * delay_steps, maxlen=max(1, delay_steps))

    y = 0.0
    y_prev = 0.0
    integral_state = 0.0
    d_filt = 0.0
    t_f = 0.1 * gains.tau_d

    times: list[float] = []
    pv_vals: list[float] = []
    mv_vals: list[float] = []
    errors: list[float] = []
    diverged = False

    for step in range(n_steps + 1):
        t_cur = step * dt
        err = setpoint_step - y

        if gains.tau_d > 0.0 and step > 0:
            dy = (y - y_prev) / dt
            alpha_f = dt / (t_f + dt)
            d_filt = (1.0 - alpha_f) * d_filt + alpha_f * (-gains.kd * dy)
        else:
            d_filt = 0.0

        p_term = gains.kc * err
        if gains.tau_i > 0.0:
            i_cand = integral_state + gains.ki * err * dt
            u_raw = p_term + i_cand + d_filt
            u_sat = _clamp_actuator(u_raw, actuator_min, actuator_max)
            pushing_high = (
                actuator_max is not None and u_raw > actuator_max and (gains.ki * err > 0.0)
            )
            pushing_low = (
                actuator_min is not None and u_raw < actuator_min and (gains.ki * err < 0.0)
            )
            if not (pushing_high or pushing_low):
                integral_state = i_cand
                u_raw = p_term + integral_state + d_filt
                u_sat = _clamp_actuator(u_raw, actuator_min, actuator_max)
        else:
            u_sat = _clamp_actuator(p_term + d_filt, actuator_min, actuator_max)

        times.append(t_cur)
        pv_vals.append(y)
        mv_vals.append(u_sat)
        errors.append(err)

        if step == n_steps:
            break

        if delay_steps == 0:
            u_delayed = u_sat
        else:
            u_delayed = delay_buf[0]
            delay_buf.append(u_sat)

        y_next = a_plant * y + b_plant * u_delayed
        if not math.isfinite(y_next) or abs(y_next) > 1e12:
            diverged = True
            break
        y_prev = y
        y = y_next

    if diverged or len(times) < 2:
        metrics = StepPerformanceMetrics(
            iae=1e12,
            ise=1e12,
            itae=1e12,
            overshoot_percent=1e6,
            rise_time=None,
            settling_time=None,
            steady_state_error=abs(setpoint_step - pv_vals[-1]) if pv_vals else abs(setpoint_step),
            is_stable=False,
        )
        return metrics, times, pv_vals, mv_vals

    iae = math.fsum(
        0.5 * (abs(errors[k]) + abs(errors[k + 1])) * dt
        for k in range(len(errors) - 1)
    )
    ise = math.fsum(
        0.5 * (errors[k] ** 2 + errors[k + 1] ** 2) * dt
        for k in range(len(errors) - 1)
    )
    itae = math.fsum(
        0.5 * (times[k] * abs(errors[k]) + times[k + 1] * abs(errors[k + 1])) * dt
        for k in range(len(errors) - 1)
    )

    abs_step = abs(setpoint_step)
    if setpoint_step > 0.0:
        overshoot = max(0.0, ((max(pv_vals) - setpoint_step) / abs_step) * 100.0)
    elif setpoint_step < 0.0:
        overshoot = max(0.0, ((setpoint_step - min(pv_vals)) / abs_step) * 100.0)
    else:
        overshoot = 0.0

    rise_time: float | None = None
    settling_time: float | None = None
    if abs_step > 0.0:
        norm_pv = [v / setpoint_step for v in pv_vals]
        try:
            t_10 = _interpolate_crossing_time(times, norm_pv, 0.1)
            t_90 = _interpolate_crossing_time(times, norm_pv, 0.9)
            rise_time = max(0.0, t_90 - t_10)
        except ValueError:
            rise_time = None

        band = 0.02 * abs_step
        last_outside = -1
        for idx, err in enumerate(errors):
            if abs(err) > band:
                last_outside = idx
        if last_outside < len(errors) - 1:
            settling_time = times[last_outside + 1] if last_outside >= 0 else times[0]

    steady_state_error = abs(errors[-1])
    late_start = int(0.8 * len(errors))
    late_max_err = max(abs(e) for e in errors[late_start:])
    peak_err = max(abs(e) for e in errors)
    bound = max(0.15 * abs_step, 1e-6)
    max_pv = max(abs(v) for v in pv_vals)
    is_stable = (
        all(math.isfinite(v) for v in pv_vals)
        and (abs_step == 0.0 or max_pv < 10.0 * abs_step)
        and late_max_err <= bound
        and (peak_err == 0.0 or late_max_err < peak_err)
    )

    metrics = StepPerformanceMetrics(
        iae=max(0.0, iae),
        ise=max(0.0, ise),
        itae=max(0.0, itae),
        overshoot_percent=max(0.0, overshoot),
        rise_time=rise_time,
        settling_time=settling_time,
        steady_state_error=steady_state_error,
        is_stable=is_stable,
    )
    return metrics, times, pv_vals, mv_vals


def control_system_optimiser_function(payload: ControlSystemInput) -> ControlSystemOutput:
    """Identify FOPDT dynamics, compute PID gains, and validate via exact-ZOH simulation."""
    t0 = time.perf_counter()
    warnings: list[str] = []

    if (
        payload.actuator_min is not None
        and payload.actuator_max is not None
        and payload.actuator_min > payload.actuator_max
    ):
        raise ValueError("actuator_min cannot exceed actuator_max.")

    if payload.fopdt is not None:
        fopdt = payload.fopdt
    else:
        if (
            payload.step_test_times is None
            or payload.step_test_pv is None
            or payload.step_test_delta_u is None
        ):
            raise ValueError(
                "Must supply either 'fopdt' or step test arrays "
                "('step_test_times', 'step_test_pv', 'step_test_delta_u')."
            )
        fopdt = _identify_fopdt_smith(
            payload.step_test_times,
            payload.step_test_pv,
            payload.step_test_delta_u,
        )

    candidate_comparisons: list[TuningCandidateResult] = []

    if payload.tuning_method == "auto_best_itae":
        methods: tuple[TuningMethodLiteral, ...] = (
            "imc",
            "simc",
            "ziegler_nichols",
            "cohen_coon",
        )
        best_choice: tuple[
            TuningCandidateResult,
            list[float],
            list[float],
            list[float],
            list[str],
        ] | None = None

        all_runs: list[
            tuple[TuningCandidateResult, list[float], list[float], list[float], list[str]]
        ] = []
        for method in methods:
            local_warn: list[str] = []
            gains = _compute_pid_gains(
                fopdt,
                payload.controller_type,
                method,
                payload.imc_tau_c,
                local_warn,
            )
            perf, ts, pvs, mvs = _simulate_closed_loop_zoh(
                fopdt,
                gains,
                payload.setpoint_step,
                payload.simulation_horizon,
                payload.dt,
                payload.actuator_min,
                payload.actuator_max,
            )
            cand = TuningCandidateResult(gains=gains, performance=perf)
            candidate_comparisons.append(cand)
            all_runs.append((cand, ts, pvs, mvs, local_warn))

        within_cap = [
            item
            for item in all_runs
            if item[0].performance.is_stable
            and item[0].performance.overshoot_percent <= payload.max_overshoot_percent
        ]
        if within_cap:
            best_choice = min(within_cap, key=lambda item: item[0].performance.itae)
        else:
            stable_runs = [item for item in all_runs if item[0].performance.is_stable]
            pool = stable_runs if stable_runs else all_runs
            best_choice = min(
                pool,
                key=lambda item: (
                    item[0].performance.overshoot_percent,
                    item[0].performance.itae,
                ),
            )
            warnings.append(
                "No tuning candidate satisfied max_overshoot_percent; selected lowest overshoot."
            )

        selected_cand, times, pv_vals, mv_vals, cand_warnings = best_choice
        recommended_gains = selected_cand.gains
        performance = selected_cand.performance
        warnings.extend(cand_warnings)
    else:
        recommended_gains = _compute_pid_gains(
            fopdt,
            payload.controller_type,
            payload.tuning_method,
            payload.imc_tau_c,
            warnings,
        )
        performance, times, pv_vals, mv_vals = _simulate_closed_loop_zoh(
            fopdt,
            recommended_gains,
            payload.setpoint_step,
            payload.simulation_horizon,
            payload.dt,
            payload.actuator_min,
            payload.actuator_max,
        )
        candidate_comparisons.append(
            TuningCandidateResult(gains=recommended_gains, performance=performance)
        )

    return ControlSystemOutput(
        slice_id=payload.slice_id,
        identified_fopdt=fopdt,
        theta_over_tau=fopdt.theta / fopdt.tau,
        recommended_gains=recommended_gains,
        performance=performance,
        candidate_comparisons=candidate_comparisons,
        time_points=times if payload.include_trajectory else [],
        pv_trajectory=pv_vals if payload.include_trajectory else [],
        mv_trajectory=mv_vals if payload.include_trajectory else [],
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
    )


# ---------------------------------------------------------------------------
# 5.8 research_tool_function & evaluate_local_research_gaps (#RESEARCH_GAP)
# ---------------------------------------------------------------------------


class ReferenceEntry(BaseModel):
    """Non-sensitive local bibliographic entry loaded from references.json."""

    ref_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    abstract_or_notes: str = ""


class ReferenceMatch(BaseModel):
    """Scored bibliographic match from local vault references or sanitized external APIs."""

    ref_id: str
    source: Literal["local_references_json", "crossref", "arxiv", "openalex"]
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    relevance_score: float = Field(ge=0.0)


class ResearchGapItem(BaseModel):
    """Detected citation, evidence, DOI, or methodological gap in research prose."""

    gap_id: str
    gap_type: Literal[
        "missing_citation",
        "unverified_claim",
        "outdated_evidence",
        "methodological_gap",
        "missing_doi",
    ]
    severity: Literal["low", "medium", "high"]
    excerpt: str
    suggested_queries: list[str] = Field(default_factory=list)


ExternalResearchProvider = Literal["crossref", "arxiv", "openalex"]


def _default_external_providers() -> list[ExternalResearchProvider]:
    return ["crossref", "openalex"]


class ResearchToolInput(BaseModel):
    """Input schema for air-gap-enforced local-first research gap & citation checking."""

    slice_id: str
    research_text: str = Field(min_length=1)
    query_terms: list[str] = Field(default_factory=list)
    dois_to_verify: list[str] = Field(default_factory=list)
    local_references: list[ReferenceEntry] = Field(default_factory=list)
    references_json_path: str | None = None
    allow_external_lookup: bool = False
    external_providers: list[ExternalResearchProvider] = Field(
        default_factory=_default_external_providers
    )
    min_local_matches_before_external: int = Field(default=1, ge=0)
    max_results_per_provider: int = Field(default=5, ge=1, le=20)
    contains_personal_vault_data: bool = True
    privacy_tier: PrivacyTier = "air_gapped"
    crossref_mailto: str | None = None


class ResearchToolOutput(BaseModel):
    """Output schema returned by ``research_tool_function`` & local gap evaluator."""

    slice_id: str
    air_gap_status: Literal[
        "local_only",
        "external_blocked_tainted",
        "external_sanitized_executed",
    ]
    local_matches: list[ReferenceMatch] = Field(default_factory=list)
    external_matches: list[ReferenceMatch] = Field(default_factory=list)
    identified_gaps: list[ResearchGapItem] = Field(default_factory=list)
    providers_queried: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    execution_time_ms: float = Field(ge=0.0)
    llm_tokens_used: Literal[0] = 0
    executed_locally: bool = True


_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "with",
        "this",
        "from",
        "are",
        "was",
        "were",
        "have",
        "has",
        "been",
        "into",
        "over",
        "than",
        "such",
        "using",
        "used",
        "when",
        "where",
        "which",
        "while",
        "these",
        "those",
        "about",
        "between",
    }
)


def _normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        cleaned = cleaned.removeprefix(prefix)
    return cleaned.strip()


def _enforce_research_air_gap(payload: ResearchToolInput) -> None:
    """Hard air-gap gate executed before any HTTP client setup or external query."""
    if not payload.allow_external_lookup:
        return
    if payload.contains_personal_vault_data or payload.privacy_tier != "sanitized":
        raise PermissionError(
            "Air-gap violation: external research queries are prohibited on "
            "personal_vault/tainted data."
        )
    for term in payload.query_terms:
        if _has_pii_or_vault_markers(term):
            raise PermissionError(
                "Air-gap violation: PII or vault marker detected in query_terms."
            )
    for doi in payload.dois_to_verify:
        if _has_pii_or_vault_markers(doi):
            raise PermissionError(
                "Air-gap violation: PII or vault marker detected in dois_to_verify."
            )


def _load_references_json_sync(path_str: str) -> list[ReferenceEntry]:
    path = Path(path_str)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        items = raw.get("references", [])
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    if not isinstance(items, list):
        return []
    return [ReferenceEntry.model_validate(item) for item in items if isinstance(item, dict)]


def _extract_keywords(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower())
    return list(dict.fromkeys(tok for tok in tokens if tok not in _STOPWORDS))


def _match_local_references(
    payload: ResearchToolInput,
    entries: Sequence[ReferenceEntry],
) -> list[ReferenceMatch]:
    target_dois = {_normalize_doi(d) for d in payload.dois_to_verify if _normalize_doi(d)}
    target_dois.update(_normalize_doi(d) for d in _DOI_REGEX.findall(payload.research_text))
    lowered_terms = [t.strip().lower() for t in payload.query_terms if t.strip()]
    text_keywords = _extract_keywords(payload.research_text)

    matches: list[ReferenceMatch] = []
    for entry in entries:
        score = 0.0
        entry_doi = _normalize_doi(entry.doi)
        if entry_doi and entry_doi in target_dois:
            score += 5.0

        searchable = " ".join(
            [
                entry.title,
                " ".join(entry.authors),
                " ".join(entry.tags),
                entry.abstract_or_notes,
            ]
        ).lower()
        searchable_tokens = set(_extract_keywords(searchable))

        for term in lowered_terms:
            if term in searchable:
                score += 2.0
            else:
                term_toks = _extract_keywords(term)
                if term_toks:
                    overlap = sum(1 for tok in term_toks if tok in searchable_tokens)
                    score += overlap / len(term_toks)

        if text_keywords:
            kw_overlap = sum(1 for kw in text_keywords if kw in searchable_tokens)
            if kw_overlap > 0:
                score += min(2.0, 0.35 * kw_overlap)

        if score > 0.0:
            matches.append(
                ReferenceMatch(
                    ref_id=entry.ref_id,
                    source="local_references_json",
                    title=entry.title,
                    authors=list(entry.authors),
                    year=entry.year,
                    doi=entry.doi,
                    url=entry.url,
                    relevance_score=round(score, 6),
                )
            )

    matches.sort(key=lambda m: -m.relevance_score)
    return matches


_CITATION_PRESENT_RE = re.compile(
    r"\[\d+(?:\s*[-–,]\s*\d+)*\]"
    r"|\([A-Z][A-Za-z.\s,&-]*?\b(?:19|20)\d{2}[a-z]?\)"
    r"|10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"
    r"|doi:\s*10\."
    r"|arXiv:\s*\d{4}\.\d{4,5}",
    re.IGNORECASE,
)
_QUANT_CLAIM_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?x\b"
    r"|\b(?:achieves?|outperforms?|demonstrates?|proven|shows?\s+that|"
    r"results?\s+indicate|significant(?:ly)?|better\s+than|faster\s+than|"
    r"lower\s+than|higher\s+than|reduces?|increases?|improves?|established|"
    r"studies\s+show|reported)\b)",
    re.IGNORECASE,
)
_STRONG_CLAIM_RE = re.compile(
    r"\b(?:always|never|proves|guarantees|optimal|exact\s+solution|universally)\b",
    re.IGNORECASE,
)
_METHOD_GAP_RE = re.compile(
    r"\b(?:assumption|limitation|untested|approximat\w*|lineariz\w*|"
    r"steady-state|idealized|without\s+validation|future\s+work)\b",
    re.IGNORECASE,
)
_AUTHOR_YEAR_RE = re.compile(
    r"\b[A-Z][a-z]+(?:\s+et\s+al\.?)?\s*\((19\d{2}|20\d{2})[a-z]?\)"
)
_RECENT_CUE_RE = re.compile(
    r"\b(?:recent(?:ly)?|modern|state-of-the-art|current(?:ly)?|latest)\b",
    re.IGNORECASE,
)


def _detect_research_gaps(
    payload: ResearchToolInput,
    known_matches: Sequence[ReferenceMatch],
) -> list[ResearchGapItem]:
    gaps: list[ResearchGapItem] = []
    sentences = [
        seg.strip()
        for seg in re.split(r"(?<=[.!?])\s+|\n+", payload.research_text)
        if seg.strip()
    ]
    current_year = datetime.datetime.now(tz=datetime.UTC).year
    matched_dois = {_normalize_doi(m.doi) for m in known_matches if _normalize_doi(m.doi)}

    def _suggest(sentence: str) -> list[str]:
        if payload.query_terms:
            return list(payload.query_terms[:3])
        kws = _extract_keywords(sentence)[:4]
        return [" ".join(kws)] if kws else []

    for sentence in sentences:
        has_citation = _CITATION_PRESENT_RE.search(sentence) is not None
        has_doi = _DOI_REGEX.search(sentence) is not None

        if _QUANT_CLAIM_RE.search(sentence) and not has_citation:
            gaps.append(
                ResearchGapItem(
                    gap_id=f"gap-{len(gaps) + 1}",
                    gap_type="missing_citation",
                    severity="high",
                    excerpt=sentence[:240],
                    suggested_queries=_suggest(sentence),
                )
            )
        elif _STRONG_CLAIM_RE.search(sentence) and not has_citation:
            gaps.append(
                ResearchGapItem(
                    gap_id=f"gap-{len(gaps) + 1}",
                    gap_type="unverified_claim",
                    severity="medium",
                    excerpt=sentence[:240],
                    suggested_queries=_suggest(sentence),
                )
            )

        author_year_match = _AUTHOR_YEAR_RE.search(sentence)
        if author_year_match:
            cited_year = int(author_year_match.group(1))
            if not has_doi and not matched_dois:
                gaps.append(
                    ResearchGapItem(
                        gap_id=f"gap-{len(gaps) + 1}",
                        gap_type="missing_doi",
                        severity="medium",
                        excerpt=sentence[:240],
                        suggested_queries=_suggest(sentence),
                    )
                )
            if _RECENT_CUE_RE.search(sentence) and (current_year - cited_year) > 10:
                gaps.append(
                    ResearchGapItem(
                        gap_id=f"gap-{len(gaps) + 1}",
                        gap_type="outdated_evidence",
                        severity="medium",
                        excerpt=sentence[:240],
                        suggested_queries=_suggest(sentence),
                    )
                )

        if _METHOD_GAP_RE.search(sentence):
            gaps.append(
                ResearchGapItem(
                    gap_id=f"gap-{len(gaps) + 1}",
                    gap_type="methodological_gap",
                    severity="low",
                    excerpt=sentence[:240],
                    suggested_queries=_suggest(sentence),
                )
            )

    for doi in payload.dois_to_verify:
        norm = _normalize_doi(doi)
        if norm and norm not in matched_dois:
            gaps.append(
                ResearchGapItem(
                    gap_id=f"gap-{len(gaps) + 1}",
                    gap_type="missing_doi",
                    severity="high",
                    excerpt=f"Unverified DOI reference: {doi}",
                    suggested_queries=[norm],
                )
            )

    return gaps


def _validate_external_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_RESEARCH_HOSTS:
        raise PermissionError(f"Disallowed external research host: {url!r}")


def _extract_year_from_crossref(item: Mapping[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        block = item.get(field)
        if isinstance(block, dict):
            date_parts = block.get("date-parts")
            if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
                first = date_parts[0]
                if first and isinstance(first[0], int):
                    return first[0]
    return None


def _parse_crossref_work(item: Mapping[str, Any], score: float) -> ReferenceMatch:
    doi = str(item.get("DOI", "")).strip() or None
    titles = item.get("title")
    title = (
        str(titles[0]).strip()
        if isinstance(titles, list) and titles
        else (str(titles).strip() if isinstance(titles, str) else "Untitled Crossref Work")
    )
    authors: list[str] = []
    raw_authors = item.get("author")
    if isinstance(raw_authors, list):
        for author in raw_authors:
            if isinstance(author, dict):
                given = str(author.get("given", "")).strip()
                family = str(author.get("family", "")).strip()
                full = f"{given} {family}".strip()
                if full:
                    authors.append(full)
    return ReferenceMatch(
        ref_id=f"crossref:{doi or title[:32]}",
        source="crossref",
        title=title,
        authors=authors,
        year=_extract_year_from_crossref(item),
        doi=doi,
        url=str(item.get("URL", "")).strip() or (f"https://doi.org/{doi}" if doi else None),
        relevance_score=max(0.0, score),
    )


def _parse_arxiv_atom(xml_text: str) -> list[ReferenceMatch]:
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        raise ValueError("Unsafe XML DOCTYPE/ENTITY declaration rejected.")
    root = ET.fromstring(xml_text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    matches: list[ReferenceMatch] = []
    for idx, entry in enumerate(root.findall("atom:entry", ns)):
        entry_id = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        title_raw = entry.findtext("atom:title", default="Untitled arXiv Preprint", namespaces=ns)
        title = " ".join((title_raw or "").split())
        authors = [
            " ".join((a.findtext("atom:name", default="", namespaces=ns) or "").split())
            for a in entry.findall("atom:author", ns)
        ]
        authors = [a for a in authors if a]
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
        doi_text = (entry.findtext("arxiv:doi", default="", namespaces=ns) or "").strip() or None
        matches.append(
            ReferenceMatch(
                ref_id=f"arxiv:{entry_id.rsplit('/', 1)[-1] or idx}",
                source="arxiv",
                title=title,
                authors=authors,
                year=year,
                doi=doi_text,
                url=entry_id or None,
                relevance_score=max(0.5, 3.0 - 0.2 * idx),
            )
        )
    return matches


def _parse_openalex_work(item: Mapping[str, Any], score: float) -> ReferenceMatch:
    raw_id = str(item.get("id", "")).strip()
    title = str(item.get("display_name") or item.get("title") or "Untitled OpenAlex Work").strip()
    raw_doi = str(item.get("doi") or "").strip()
    doi = _normalize_doi(raw_doi) or None
    year_val = item.get("publication_year")
    year = int(year_val) if isinstance(year_val, int) else None
    authors: list[str] = []
    authorships = item.get("authorships")
    if isinstance(authorships, list):
        for auth in authorships:
            if isinstance(auth, dict):
                author_obj = auth.get("author")
                if isinstance(author_obj, dict) and author_obj.get("display_name"):
                    authors.append(str(author_obj["display_name"]).strip())
    return ReferenceMatch(
        ref_id=f"openalex:{raw_id.rsplit('/', 1)[-1] or doi or title[:32]}",
        source="openalex",
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        url=raw_id or (f"https://doi.org/{doi}" if doi else None),
        relevance_score=max(0.0, score),
    )


async def _query_external_providers(
    payload: ResearchToolInput,
    client: httpx.AsyncClient,
    warnings: list[str],
) -> tuple[list[ReferenceMatch], list[str]]:
    sanitized_terms = [term.strip() for term in payload.query_terms if term.strip()]
    sanitized_dois = [_normalize_doi(d) for d in payload.dois_to_verify if _normalize_doi(d)]
    if not sanitized_terms and not sanitized_dois:
        warnings.append(
            "No sanitized query_terms or dois_to_verify supplied; skipped external lookup."
        )
        return [], []

    matches: list[ReferenceMatch] = []
    providers_queried: list[str] = []

    for provider in payload.external_providers:
        if provider == "crossref":
            providers_queried.append("crossref")
            for doi in sanitized_dois:
                url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
                _validate_external_url(url)
                params: dict[str, str | int] = {}
                if payload.crossref_mailto:
                    params["mailto"] = payload.crossref_mailto.strip()
                try:
                    resp = await client.get(url, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data.get("message") if isinstance(data, dict) else None
                    if isinstance(msg, dict):
                        matches.append(_parse_crossref_work(msg, score=5.0))
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f"Crossref DOI lookup failed for {doi}: {exc}")

            if sanitized_terms:
                url = "https://api.crossref.org/works"
                _validate_external_url(url)
                query_params: dict[str, str | int] = {
                    "query": " ".join(sanitized_terms),
                    "rows": payload.max_results_per_provider,
                    "select": "DOI,title,author,published,URL",
                }
                if payload.crossref_mailto:
                    query_params["mailto"] = payload.crossref_mailto.strip()
                try:
                    resp = await client.get(url, params=query_params)
                    resp.raise_for_status()
                    data = resp.json()
                    msg = data.get("message") if isinstance(data, dict) else None
                    items = msg.get("items", []) if isinstance(msg, dict) else []
                    if isinstance(items, list):
                        for idx, item in enumerate(items):
                            if isinstance(item, dict):
                                matches.append(
                                    _parse_crossref_work(item, score=max(0.5, 3.0 - 0.2 * idx))
                                )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f"Crossref query failed: {exc}")

        elif provider == "arxiv":
            providers_queried.append("arxiv")
            query_parts = [f"all:{term}" for term in sanitized_terms]
            if not query_parts:
                query_parts = [f"all:{doi}" for doi in sanitized_dois]
            search_query = " AND ".join(query_parts)
            url = "https://export.arxiv.org/api/query"
            _validate_external_url(url)
            try:
                resp = await client.get(
                    url,
                    params={
                        "search_query": search_query,
                        "max_results": payload.max_results_per_provider,
                    },
                )
                resp.raise_for_status()
                matches.extend(_parse_arxiv_atom(resp.text))
            except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                warnings.append(f"arXiv query failed: {exc}")

        elif provider == "openalex":
            providers_queried.append("openalex")
            for doi in sanitized_dois:
                url = f"https://api.openalex.org/works/https://doi.org/{quote(doi, safe='')}"
                _validate_external_url(url)
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                    if isinstance(data, dict):
                        matches.append(_parse_openalex_work(data, score=5.0))
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f"OpenAlex DOI lookup failed for {doi}: {exc}")

            if sanitized_terms:
                url = "https://api.openalex.org/works"
                _validate_external_url(url)
                try:
                    resp = await client.get(
                        url,
                        params={
                            "search": " ".join(sanitized_terms),
                            "per-page": payload.max_results_per_provider,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results", []) if isinstance(data, dict) else []
                    if isinstance(results, list):
                        for idx, item in enumerate(results):
                            if isinstance(item, dict):
                                matches.append(
                                    _parse_openalex_work(item, score=max(0.5, 3.0 - 0.2 * idx))
                                )
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    warnings.append(f"OpenAlex query failed: {exc}")

    return matches, providers_queried


def _build_local_research_output(
    payload: ResearchToolInput,
    local_matches: list[ReferenceMatch],
    t0: float,
    warnings: list[str],
) -> ResearchToolOutput:
    gaps = _detect_research_gaps(payload, local_matches)
    return ResearchToolOutput(
        slice_id=payload.slice_id,
        air_gap_status="local_only",
        local_matches=local_matches,
        external_matches=[],
        identified_gaps=gaps,
        providers_queried=[],
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
        executed_locally=True,
    )


def evaluate_local_research_gaps(payload: ResearchToolInput) -> ResearchToolOutput:
    """Synchronous offline-only local reference matcher and research gap detector."""
    t0 = time.perf_counter()
    _enforce_research_air_gap(payload)
    warnings: list[str] = []
    entries = list(payload.local_references)
    if not entries and payload.references_json_path:
        entries = _load_references_json_sync(payload.references_json_path)
    local_matches = _match_local_references(payload, entries)
    return _build_local_research_output(payload, local_matches, t0, warnings)


async def research_tool_function(
    payload: ResearchToolInput,
    http_client: httpx.AsyncClient | None = None,
) -> ResearchToolOutput:
    """Evaluate local references and gaps first; query sanitized external APIs only if cleared."""
    t0 = time.perf_counter()
    _enforce_research_air_gap(payload)
    warnings: list[str] = []

    entries = list(payload.local_references)
    if not entries and payload.references_json_path:
        entries = await asyncio.to_thread(
            _load_references_json_sync,
            payload.references_json_path,
        )

    local_matches = _match_local_references(payload, entries)
    if (
        len(local_matches) >= payload.min_local_matches_before_external
        or not payload.allow_external_lookup
    ):
        return _build_local_research_output(payload, local_matches, t0, warnings)

    if http_client is not None:
        ext_matches, providers_queried = await _query_external_providers(
            payload, http_client, warnings
        )
    else:
        async with httpx.AsyncClient(timeout=15.0) as managed_client:
            ext_matches, providers_queried = await _query_external_providers(
                payload, managed_client, warnings
            )

    all_matches = [*local_matches, *ext_matches]
    gaps = _detect_research_gaps(payload, all_matches)
    executed_externally = bool(providers_queried)

    return ResearchToolOutput(
        slice_id=payload.slice_id,
        air_gap_status=(
            "external_sanitized_executed" if executed_externally else "local_only"
        ),
        local_matches=local_matches,
        external_matches=ext_matches,
        identified_gaps=gaps,
        providers_queried=providers_queried,
        warnings=warnings,
        execution_time_ms=_elapsed_ms(t0),
        executed_locally=not executed_externally,
    )
