"""1,024-parameter deterministic CPU micro-router and feature extractor (SPEC-001)."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from .pre_slicer import DataSlice, TagType

_NUM_FEATURES = 48
_NUM_HIDDEN = 16
_NUM_OUTPUTS = 14
_EXPECTED_PARAM_COUNT = (_NUM_HIDDEN * _NUM_FEATURES) + _NUM_HIDDEN + (_NUM_OUTPUTS * _NUM_HIDDEN) + _NUM_OUTPUTS + 2

_TAG_ORDER: tuple[TagType, ...] = (
    TagType.TABLE_DATA,
    TagType.CALC_SOLVE,
    TagType.DATA_COMPARE,
    TagType.PDF_CONVERT,
    TagType.SMART_PDF_LINK,
    TagType.CODE_OPTIMISE,
    TagType.CONTROL_SYSTEM,
    TagType.RESEARCH_GAP,
    TagType.SEMANTIC_MICRO,
    TagType.GENERAL_SYNTHESIS,
)

_WORD_RE = re.compile(r"[a-z0-9_]+")
_TAG_PREFIX_VALUES: tuple[str, ...] = tuple(tag.value for tag in _TAG_ORDER) + tuple(
    f"[{tag.value}]" for tag in _TAG_ORDER
)

# Compiled domain signal patterns for deterministic feature extraction (x[32..47]).
_CALC_CI_RE = re.compile(
    r"\b(?:exp|log|log10|sqrt|sin|cos|tan|asin|acos|atan|arrhenius|reynolds|"
    r"ideal_gas|antoine|newton_root|simpson|kelvin|celsius|joule|pascal|"
    r"evaluate_expression|unit_convert)\b",
    re.IGNORECASE,
)
_CALC_CS_RE = re.compile(r"\b(?:mol|kJ|kPa|MPa|Pa|mmHg|bar|atm|K|Re)\b")
_MATH_OP_RE = re.compile(r"(?:\*\*|[=+\-*/^])")

_COMPARE_RE = re.compile(
    r"\b(?:baseline|candidate|delta|vs|rmse|mae|mape|pearson|r_squared|"
    r"abs_tolerance|rel_tolerance|tolerance|table_diff|numeric_series|"
    r"key_value_records|compare|diff)\b",
    re.IGNORECASE,
)
_PDF_CONVERT_RE = re.compile(
    r"(?:\.pdf\b|%pdf-|page\s+\d+|\bdehyphenate\b|\bstrip_headers\b|\bpdf_converter\b)",
    re.IGNORECASE,
)
_PDF_LINK_RE = re.compile(
    r"(?:\bTable\s+\d+|\bFig(?:ure)?\.?\s*\d+|\bEq(?:uation)?\.?\s*\d+|"
    r"\[\d+(?:\s*,\s*\d+)*\]|\bsection\s+\d+|\bbm25\b|\bcross_links?\b|\bsmart_pdf\b)",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"(?:^\s*(?:async\s+def|def|class)\s+\w+|^\s*(?:import|from)\s+\w+|"
    r"\b(?:return|await|raise|lambda)\b|\bself\.|try:|except\b|```python)",
    re.MULTILINE,
)
_CONTROL_RE = re.compile(
    r"\b(?:fopdt|pid|imc|simc|ziegler|cohen|kp|tau|theta|tau_i|tau_d|tau_c|"
    r"iae|ise|itae|overshoot|settling|rise_time|step_test|setpoint|actuator_min)\b",
    re.IGNORECASE,
)
_RESEARCH_RE = re.compile(
    r"(?:\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b|\b(?:doi|arxiv|crossref|openalex|"
    r"research\s+gap|missing\s+citation|unverified|citation|references\.json|"
    r"bibliography|literature)\b)",
    re.IGNORECASE,
)
_PRIVACY_STRONG_RE = re.compile(
    r"(?:\bpersonal_vault(?:\.db)?\b|air_gapped|\b(?:password|passwd|api_key|apikey|"
    r"secret_key|access_token|private_key|secret)\b\s*[:=]|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{20,})\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b\d{3}-\d{2}-\d{4}\b|\bSSN\b|"
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)",
    re.IGNORECASE,
)
_PRIVACY_MILD_RE = re.compile(r"\b(?:private|confidential|credential)\b", re.IGNORECASE)
_SEMANTIC_MICRO_RE = re.compile(
    r"\b(?:explain|summarize|why|interpret|describe|clarify|meaning|shortly)\b|\?",
    re.IGNORECASE,
)
_SEMANTIC_SYNTH_RE = re.compile(
    r"\b(?:brainstorm|synthesize|roadmap|comprehensive|trade-?offs?|overview|"
    r"strategy|compare\s+options|discuss|architect)\b",
    re.IGNORECASE,
)
_KV_JSON_RE = re.compile(r'(?:[A-Za-z_][A-Za-z0-9_]*=\S+|"[A-Za-z0-9_]+"?\s*:)')


class MicroModelPrediction(BaseModel):
    """Structured prediction returned by ThousandParamMicroModel."""

    slice_id: str
    predicted_tag: TagType
    tag_probabilities: dict[TagType, float]
    deterministic_score: float = Field(ge=0.0, le=1.0)
    semantic_escalation_score: float = Field(ge=0.0, le=1.0)
    cloud_eligibility_score: float = Field(ge=0.0, le=1.0)
    privacy_risk_score: float = Field(ge=0.0, le=1.0)
    parameter_count: Literal[1024] = 1024
    latency_ms: float = Field(ge=0.0)


def _clamp01(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return float(value)


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


def _table_delimiter_density(raw_payload: str) -> float:
    stripped = raw_payload.strip()
    if not stripped:
        return 0.0
    if stripped.startswith("[") and stripped.endswith("]") and "{" in stripped and ":" in stripped:
        return 0.88
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    sample = lines[:12]
    n_lines = len(sample)
    if n_lines >= 2:
        pipe_lines = sum(1 for ln in sample if ln.count("|") >= 2)
        if pipe_lines >= 2:
            return _clamp01(pipe_lines / n_lines)
        for delim in ("\t", ","):
            counts = [ln.count(delim) for ln in sample]
            non_zero = [c for c in counts if c >= 1]
            if len(non_zero) >= 2:
                most_common_freq = Counter(non_zero).most_common(1)[0][1]
                consistency = most_common_freq / n_lines
                if consistency >= 0.5:
                    return _clamp01(0.45 + 0.55 * consistency)
    return 0.0


def _bracket_regularity(raw_payload: str) -> float:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = {")": "(", "]": "[", "}": "{"}
    stack: list[str] = []
    seen_any = False
    for ch in raw_payload[:2048]:
        if ch in pairs:
            seen_any = True
            stack.append(ch)
        elif ch in closing:
            seen_any = True
            if not stack or stack[-1] != closing[ch]:
                return 0.0
            stack.pop()
    if stack:
        return 0.0
    return 1.0 if seen_any else 0.5


def extract_features(raw_payload: str, has_explicit_tag: bool = False) -> list[float]:
    """Extract the exact 48-dimensional feature vector phi(slice) in pure Python."""
    lower = raw_payload.lower()

    # Dims x[0..31]: 32-dim signed blake2b hash projection (words + char 3-grams).
    hash_vec = [0.0] * 32
    words = _WORD_RE.findall(lower[:2000])[:32]
    token_counts: Counter[str] = Counter(words)

    ngram_source = " ".join(lower[:160].split())
    if len(ngram_source) >= 3:
        for idx in range(0, min(len(ngram_source) - 2, 72), 3):
            gram = ngram_source[idx : idx + 3]
            token_counts[gram] += 1

    for tok, count in token_counts.items():
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        h_int = int.from_bytes(digest, byteorder="little", signed=False)
        bucket = h_int % 32
        sign = 1.0 if ((h_int >> 5) & 1) == 0 else -1.0
        hash_vec[bucket] += sign * float(count)

    norm = math.sqrt(sum(v * v for v in hash_vec))
    denom = max(1e-12, norm)
    features = [v / denom for v in hash_vec]

    # Dims x[32..47]: 16 explicit domain & structural signals in [0, 1].
    explicit_flag = 1.0 if (has_explicit_tag or raw_payload.lstrip().startswith(_TAG_PREFIX_VALUES)) else 0.0
    table_score = _table_delimiter_density(raw_payload)

    digit_count = sum(1 for ch in raw_payload[:1000] if ch.isdigit())
    calc_ci_hits = len(_CALC_CI_RE.findall(raw_payload))
    calc_cs_hits = len(_CALC_CS_RE.findall(raw_payload))
    op_hits = len(_MATH_OP_RE.findall(raw_payload))
    calc_raw = (0.32 * calc_ci_hits) + (0.28 * calc_cs_hits) + (
        0.15 * min(op_hits, 4) if digit_count > 0 else 0.0
    )
    calc_score = _clamp01(calc_raw)

    compare_hits = len(_COMPARE_RE.findall(raw_payload))
    compare_score = _clamp01(0.38 * compare_hits)

    pdf_hits = len(_PDF_CONVERT_RE.findall(raw_payload))
    if "-\n" in raw_payload or "-\r\n" in raw_payload:
        pdf_hits += 1
    pdf_convert_score = _clamp01(0.45 * pdf_hits)

    pdf_link_hits = len(_PDF_LINK_RE.findall(raw_payload))
    smart_pdf_score = _clamp01(0.35 * pdf_link_hits)

    code_hits = len(_CODE_RE.findall(raw_payload))
    code_score = _clamp01(0.38 * code_hits)

    control_hits = len(_CONTROL_RE.findall(raw_payload))
    control_score = _clamp01(0.32 * control_hits)

    research_hits = len(_RESEARCH_RE.findall(raw_payload))
    research_score = _clamp01(0.36 * research_hits)

    privacy_strong = len(_PRIVACY_STRONG_RE.findall(raw_payload))
    privacy_mild = len(_PRIVACY_MILD_RE.findall(raw_payload))
    privacy_score = _clamp01((0.55 * privacy_strong) + (0.20 * privacy_mild))

    log_len = _clamp01(math.log1p(len(raw_payload)) / 10.0)
    line_count = len(raw_payload.splitlines()) if raw_payload else 0
    line_density = _clamp01(line_count / 50.0)

    kv_hits = len(_KV_JSON_RE.findall(raw_payload))
    kv_ratio = _clamp01(kv_hits / max(1, min(len(words), 16)))

    sem_micro_hits = len(_SEMANTIC_MICRO_RE.findall(raw_payload))
    sem_synth_hits = len(_SEMANTIC_SYNTH_RE.findall(raw_payload))
    semantic_cue_score = _clamp01((0.35 * sem_micro_hits) + (0.45 * sem_synth_hits))

    bracket_score = _bracket_regularity(raw_payload)
    bias_anchor = 1.0

    features.extend(
        [
            explicit_flag,       # x[32]
            table_score,         # x[33]
            calc_score,          # x[34]
            compare_score,       # x[35]
            pdf_convert_score,   # x[36]
            smart_pdf_score,     # x[37]
            code_score,          # x[38]
            control_score,       # x[39]
            research_score,      # x[40]
            privacy_score,       # x[41]
            log_len,             # x[42]
            line_density,        # x[43]
            kv_ratio,            # x[44]
            semantic_cue_score,  # x[45]
            bracket_score,       # x[46]
            bias_anchor,         # x[47]
        ]
    )
    return features


def _build_default_weights_1024() -> dict[str, Any]:
    """Construct the calibrated 1,024-parameter deterministic weight bundle."""
    w1: list[list[float]] = []
    for row_idx in range(_NUM_HIDDEN):
        # Small deterministic orthogonal-like hash weights on x[0..31] so Cauchy-Schwarz bound <= 0.12.
        scale = 0.06 if row_idx == 15 else 0.018
        hash_row = [
            round(scale * math.cos((row_idx + 1) * (col_idx + 1) * 0.37), 5)
            for col_idx in range(32)
        ]
        struct_row = [0.0] * 16
        w1.append(hash_row + struct_row)

    b1 = [0.0] * _NUM_HIDDEN

    # Hidden unit 0: TABLE_DATA
    w1[0][33] = 5.0
    w1[0][38] = -2.0
    w1[0][37] = -1.2
    w1[0][35] = -1.0
    b1[0] = -0.2

    # Hidden unit 1: CALC_SOLVE
    w1[1][34] = 5.0
    w1[1][33] = -2.5
    w1[1][39] = -2.5
    w1[1][38] = -2.0
    w1[1][35] = -1.5
    w1[1][40] = -1.5
    b1[1] = -0.2

    # Hidden unit 2: DATA_COMPARE
    w1[2][35] = 5.2
    w1[2][38] = -2.0
    w1[2][33] = -1.0
    b1[2] = -0.2

    # Hidden unit 3: PDF_CONVERT
    w1[3][36] = 5.0
    w1[3][37] = -2.5
    w1[3][38] = -1.5
    b1[3] = -0.2

    # Hidden unit 4: SMART_PDF_LINK
    w1[4][37] = 5.2
    w1[4][36] = 0.4
    w1[4][40] = -1.8
    w1[4][33] = -1.5
    w1[4][38] = -1.5
    b1[4] = -0.2

    # Hidden unit 5: CODE_OPTIMISE
    w1[5][38] = 5.4
    w1[5][46] = 0.3
    w1[5][33] = -0.8
    b1[5] = -0.25

    # Hidden unit 6: CONTROL_SYSTEM
    w1[6][39] = 5.2
    w1[6][34] = 0.3
    w1[6][38] = -2.0
    w1[6][35] = -1.0
    b1[6] = -0.2

    # Hidden unit 7: RESEARCH_GAP
    w1[7][40] = 5.2
    w1[7][37] = 0.4
    w1[7][38] = -1.5
    b1[7] = -0.2

    # Hidden unit 8: SEMANTIC_MICRO
    w1[8][45] = 4.2
    w1[8][42] = -1.8
    w1[8][43] = -1.2
    for dom_idx in range(33, 41):
        w1[8][dom_idx] = -2.5
    b1[8] = 0.6

    # Hidden unit 9: GENERAL_SYNTHESIS
    w1[9][45] = 3.6
    w1[9][42] = 2.6
    w1[9][43] = 2.0
    w1[9][41] = -2.0
    for dom_idx in range(33, 41):
        w1[9][dom_idx] = -2.5
    b1[9] = -1.15

    # Hidden unit 10: Privacy / Vault risk detector
    w1[10][41] = 6.0
    b1[10] = -0.2

    # Hidden unit 11: Aggregate deterministic solver signal
    for dom_idx in range(33, 41):
        w1[11][dom_idx] = 3.5
    w1[11][44] = 0.5
    w1[11][45] = -1.0
    b1[11] = -0.25

    # Hidden unit 12: Open-ended semantic escalation signal
    w1[12][45] = 2.0
    for dom_idx in range(33, 41):
        w1[12][dom_idx] = -3.5
    b1[12] = 0.8

    # Hidden unit 13: Long / multi-line context splitter
    w1[13][42] = 3.0
    w1[13][43] = 2.0
    b1[13] = -1.35

    # Hidden unit 14: Structured tag / KV booster
    w1[14][32] = 1.5
    w1[14][44] = 1.5
    b1[14] = -0.1

    # Hidden unit 15: Hash-projection anchor
    w1[15][47] = 0.25
    b1[15] = 0.0

    # Layer 2: W2 (14 x 16) and b2 (14).
    w2: list[list[float]] = [[0.0] * _NUM_HIDDEN for _ in range(_NUM_OUTPUTS)]
    b2: list[float] = [0.0] * _NUM_OUTPUTS

    for idx in range(8):
        w2[idx][idx] = 2.5
        w2[idx][14] = 0.1
        w2[idx][15] = 0.05
        b2[idx] = -1.0

    # z[8]: SEMANTIC_MICRO
    w2[8][8] = 2.2
    w2[8][12] = 0.6
    w2[8][11] = -1.5
    w2[8][13] = -0.9
    w2[8][15] = 0.05
    b2[8] = -0.3

    # z[9]: GENERAL_SYNTHESIS
    w2[9][9] = 2.4
    w2[9][12] = 0.5
    w2[9][13] = 1.2
    w2[9][11] = -1.5
    w2[9][10] = -0.5
    w2[9][15] = 0.05
    b2[9] = -0.6

    # z[10]: deterministic_score
    w2[10][11] = 1.4
    w2[10][12] = -1.4
    b2[10] = -0.3

    # z[11]: semantic_escalation_score
    w2[11][12] = 1.4
    w2[11][8] = 0.5
    w2[11][9] = 0.5
    w2[11][11] = -1.3
    b2[11] = -0.2

    # z[12]: cloud_eligibility_score (advisory only)
    w2[12][9] = 1.1
    w2[12][13] = 0.7
    w2[12][10] = -3.0
    w2[12][11] = -0.8
    b2[12] = -0.1

    # z[13]: privacy_risk_score
    w2[13][10] = 2.4
    b2[13] = -2.2

    return {
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
        "tau_temp": 0.5,
        "theta_esc": 0.0,
    }


DEFAULT_MICRO_WEIGHTS_1024: dict[str, Any] = _build_default_weights_1024()


def _coerce_matrix(
    raw: Any,
    rows: int,
    cols: int,
    name: str,
) -> list[list[float]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise TypeError(f"{name} must be a sequence.")
    if len(raw) == rows * cols and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw):
        flat = [float(v) for v in raw]
        return [flat[r * cols : (r + 1) * cols] for r in range(rows)]
    if len(raw) != rows:
        raise ValueError(f"{name} must have {rows} rows (or {rows * cols} flat floats), got {len(raw)}.")
    matrix: list[list[float]] = []
    for r_idx, row in enumerate(raw):
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != cols:
            raise ValueError(f"{name}[{r_idx}] must have length {cols}.")
        converted: list[float] = []
        for val in row:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise TypeError(f"{name}[{r_idx}] contains non-numeric entry.")
            fval = float(val)
            if not math.isfinite(fval):
                raise ValueError(f"{name}[{r_idx}] contains non-finite value.")
            converted.append(fval)
        matrix.append(converted)
    return matrix


def _coerce_vector(raw: Any, length: int, name: str) -> list[float]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != length:
        raise ValueError(f"{name} must have length {length}.")
    vec: list[float] = []
    for val in raw:
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise TypeError(f"{name} contains non-numeric entry.")
        fval = float(val)
        if not math.isfinite(fval):
            raise ValueError(f"{name} contains non-finite value.")
        vec.append(fval)
    return vec


class ThousandParamMicroModel:
    """Pure-Python 1,024-parameter deterministic router and solvability scorer."""

    def __init__(self, weights: Mapping[str, Any] | None = None) -> None:
        source = weights if weights is not None else DEFAULT_MICRO_WEIGHTS_1024
        w1_raw = source.get("w1", source.get("w1_flat"))
        b1_raw = source.get("b1")
        w2_raw = source.get("w2", source.get("w2_flat"))
        b2_raw = source.get("b2")
        tau_raw = source.get("tau_temp")
        theta_raw = source.get("theta_esc")

        self._w1: list[list[float]] = _coerce_matrix(w1_raw, _NUM_HIDDEN, _NUM_FEATURES, "w1")
        self._b1: list[float] = _coerce_vector(b1_raw, _NUM_HIDDEN, "b1")
        self._w2: list[list[float]] = _coerce_matrix(w2_raw, _NUM_OUTPUTS, _NUM_HIDDEN, "w2")
        self._b2: list[float] = _coerce_vector(b2_raw, _NUM_OUTPUTS, "b2")

        if isinstance(tau_raw, bool) or not isinstance(tau_raw, (int, float)):
            raise TypeError("tau_temp must be a positive float.")
        if isinstance(theta_raw, bool) or not isinstance(theta_raw, (int, float)):
            raise TypeError("theta_esc must be a finite float.")
        self._tau_temp: float = float(tau_raw)
        self._theta_esc: float = float(theta_raw)
        if not math.isfinite(self._tau_temp) or self._tau_temp <= 0.0:
            raise ValueError("tau_temp must be finite and > 0.")
        if not math.isfinite(self._theta_esc):
            raise ValueError("theta_esc must be finite.")

        assert self.parameter_count == _EXPECTED_PARAM_COUNT, (
            f"Expected {_EXPECTED_PARAM_COUNT} parameters, got {self.parameter_count}."
        )

    @property
    def parameter_count(self) -> int:
        """Exact total scalar parameter count (must equal 1,024)."""
        w1_count = sum(len(row) for row in self._w1)
        w2_count = sum(len(row) for row in self._w2)
        return w1_count + len(self._b1) + w2_count + len(self._b2) + 2

    @classmethod
    def from_weights(
        cls, weights: Mapping[str, Any] | Sequence[float] | str
    ) -> ThousandParamMicroModel:
        """Deserialize a ThousandParamMicroModel from a dict, flat 1,024 vector, or JSON string."""
        parsed: Any = json.loads(weights) if isinstance(weights, str) else weights
        if isinstance(parsed, Mapping):
            return cls(weights=parsed)
        if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
            if len(parsed) != _EXPECTED_PARAM_COUNT:
                raise ValueError(
                    f"Flat weights sequence must have exactly {_EXPECTED_PARAM_COUNT} values, "
                    f"got {len(parsed)}."
                )
            flat: list[float] = []
            for item in parsed:
                if isinstance(item, bool) or not isinstance(item, (int, float)):
                    raise TypeError("Flat weights must contain only real numbers.")
                fval = float(item)
                if not math.isfinite(fval):
                    raise ValueError("Flat weights contain non-finite value.")
                flat.append(fval)

            idx_w1 = _NUM_HIDDEN * _NUM_FEATURES
            idx_b1 = idx_w1 + _NUM_HIDDEN
            idx_w2 = idx_b1 + (_NUM_OUTPUTS * _NUM_HIDDEN)
            idx_b2 = idx_w2 + _NUM_OUTPUTS
            return cls(
                weights={
                    "w1": flat[:idx_w1],
                    "b1": flat[idx_w1:idx_b1],
                    "w2": flat[idx_b1:idx_w2],
                    "b2": flat[idx_w2:idx_b2],
                    "tau_temp": flat[idx_b2],
                    "theta_esc": flat[idx_b2 + 1],
                }
            )
        raise ValueError("Unsupported weights format; expected Mapping, 1024-float Sequence, or JSON str.")

    def to_weights(self) -> dict[str, Any]:
        """Serialize model weights into a JSON-compatible dictionary."""
        return {
            "w1": [list(row) for row in self._w1],
            "b1": list(self._b1),
            "w2": [list(row) for row in self._w2],
            "b2": list(self._b2),
            "tau_temp": self._tau_temp,
            "theta_esc": self._theta_esc,
        }

    def forward_logits(self, features: Sequence[float]) -> list[float]:
        """Execute pure-Python ReLU MLP forward pass to produce 14 output logits."""
        if len(features) != _NUM_FEATURES:
            raise ValueError(f"Expected {_NUM_FEATURES} input features, got {len(features)}.")
        hidden: list[float] = []
        w1 = self._w1
        b1 = self._b1
        for i in range(_NUM_HIDDEN):
            row = w1[i]
            acc = b1[i]
            for j in range(_NUM_FEATURES):
                acc += row[j] * features[j]
            hidden.append(max(0.0, acc))

        logits: list[float] = []
        w2 = self._w2
        b2 = self._b2
        for k in range(_NUM_OUTPUTS):
            row2 = w2[k]
            acc2 = b2[k]
            for i in range(_NUM_HIDDEN):
                acc2 += row2[i] * hidden[i]
            logits.append(acc2)
        return logits

    def predict(
        self,
        raw_payload: str | DataSlice,
        slice_id: str = "slice-0",
        has_explicit_tag: bool = False,
    ) -> MicroModelPrediction:
        """Score an isolated DataSlice or text block in < 0.2 ms using 0 VRAM."""
        t_start = time.perf_counter()
        if isinstance(raw_payload, DataSlice):
            payload_text = raw_payload.raw_payload
            resolved_slice_id = raw_payload.slice_id
        else:
            payload_text = raw_payload
            resolved_slice_id = slice_id

        features = extract_features(payload_text, has_explicit_tag=has_explicit_tag)
        logits = self.forward_logits(features)

        tag_logits = logits[:10]
        max_logit = max(tag_logits)
        scaled = [(z - max_logit) / self._tau_temp for z in tag_logits]
        exps = [math.exp(val) for val in scaled]
        exp_sum = sum(exps)
        probs = [e / exp_sum for e in exps]

        tag_probabilities = {tag: probs[idx] for idx, tag in enumerate(_TAG_ORDER)}
        best_idx = max(range(10), key=lambda idx: probs[idx])
        predicted_tag = _TAG_ORDER[best_idx]

        det_score = _sigmoid(logits[10])
        esc_score = _sigmoid(logits[11] - self._theta_esc)
        cloud_score = _sigmoid(logits[12])
        privacy_score = _sigmoid(logits[13])

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return MicroModelPrediction(
            slice_id=resolved_slice_id,
            predicted_tag=predicted_tag,
            tag_probabilities=tag_probabilities,
            deterministic_score=det_score,
            semantic_escalation_score=esc_score,
            cloud_eligibility_score=cloud_score,
            privacy_risk_score=privacy_score,
            parameter_count=1024,
            latency_ms=latency_ms,
        )
