# Spec 001: Nested Nano-Models, Pre-Grouped Tag Slicing & Deterministic Tool Contracts

- **Spec ID:** `SPEC-001`
- **Status:** `Approved`
- **Authoring Domain:** `/02-yggdrasil-lab/`
- **Governs Downstream Targets:** `/03-agent-foundry/yggdrasil_agents/` (primary runtime package) & `/04-yggdrasil-app/` (vault/reference injection & workflow orchestration)
- **Depends On:** [`000-foundational-architecture-spec.md`](000-foundational-architecture-spec.md) (`SPEC-000`)
- **Verified SDK Grounding Reference:** [`01-code-oracle/001-nano-routing-and-deterministic-tools-grounding.md`](../../01-code-oracle/001-nano-routing-and-deterministic-tools-grounding.md)

---

## 1. Purpose & Architectural Rationale

Heavy 8B–14B local LLMs incur 500–3,000 ms cold-start/prefill latency and high VRAM pressure, while burning unnecessary tokens on tasks that are purely algebraic, structural, tabular, static-AST, or control-theoretic. Conversely, ultra-lightweight nano models (`135M`–`0.5B` parameters) lose accuracy when fed unsegmented multi-topic prompts.

`SPEC-001` resolves both bottlenecks via a **three-tier nested execution architecture**:
1. **Zero-Token Pre-Grouped Tag Slicing (`TagType`, `DataSlice`, `PreGroupedBundle`):** Deterministically partitions raw input into minimal, single-topic slices *before* any model runs.
2. **Ultra-Lightweight Nested Routing & Nano Inference (`ThousandParamMicroModel`, `NestedCallableLightAgent`, `NestedModelOrchestrator`):** Routes each isolated slice through a 1,024-parameter pure-Python micro-scorer (< 0.2 ms, 0 VRAM, 0 LLM tokens) to either one of 8 deterministic Python solvers or a shared `LocalEngine`-backed nano model (`yggdrasil-nano` / `smollm2:135m` / `qwen2.5:0.5b`), while enforcing **Strict Air-Gap Privacy** before any `LeavesCloudAgent` call.
3. **Eight Pure-Python Deterministic Domain Tools:** Strictly typed Pydantic `BaseModel` solvers covering table handling, safe AST & ChemEng calculations, numerical comparisons, PDF conversion, BM25/W_i PDF linking, Python QA/AST optimization, FOPDT/PID control optimization, and air-gapped local-first literature gap analysis.

---

## 2. Compiled `<prompt_spec>` & Boolean Routing Logic (`/prompt-optimiser`)

```xml
<prompt_spec>
  <objective>
    Execute single-slice deterministic Python tools (0 LLM tokens, &lt;1ms typical compute) first,
    escalate only irreducible semantic micro-tasks to an isolated nano LLM via the shared LocalEngine,
    and permit LeavesCloudAgent synthesis solely on explicitly air-gap-cleared payloads.
  </objective>
  <target_directory>
    /02-yggdrasil-lab/specs/001-nested-nano-models-and-deterministic-tools-spec.md
    -> unlocks /03-agent-foundry/yggdrasil_agents/ and /04-yggdrasil-app/
  </target_directory>
  <constraints>
    - Law 1 (Spec-First Gate): All runtime classes, functions, schemas, and mathematical equations in /03-agent-foundry/ and /04-yggdrasil-app/ MUST match SPEC-001 exactly.
    - Law 2 (Zero-Hallucination): External scholarly lookups MUST use verified endpoints (Crossref /works, arXiv /api/query, OpenAlex /works); Ollama Modelfile syntax MUST use verified directives (FROM, PARAMETER, SYSTEM, TEMPLATE).
    - Law 3 (Single Local Model / VRAM Discipline): ThousandParamMicroModel and all 8 deterministic tools run with 0 VRAM. Any nano LLM inference via NestedCallableLightAgent MUST share the single resident LocalEngine singleton (http://localhost:11434/v1 Ollama or http://localhost:1234/v1 LM Studio); parallel model loading in VRAM is prohibited.
    - Law 4 (Air-Gap Privacy): Any DataSlice, PreGroupedBundle, or payload originating from personal_vault.db or flagged contains_personal_vault_data=True MUST NEVER be routed to LeavesCloudAgent, google-genai, or external research APIs; violations MUST raise PermissionError.
    - Package Isolation: yggdrasil_agents MUST NOT hardcode or own /04-yggdrasil-app/vaults/*.db SQLite connections; references.json entries or paths are dependency-injected by the caller.
    - Type Safety: All public tool/agent inputs and outputs MUST inherit from pydantic.BaseModel with explicit Field bounds and Python >= 3.11 type annotations.
  </constraints>
  <logic_rules>
    IF task_matches_deterministic_tag (#TABLE_DATA, #CALC_SOLVE, #DATA_COMPARE, #PDF_CONVERT, #SMART_PDF_LINK, #CODE_OPTIMISE, #CONTROL_SYSTEM, #RESEARCH_GAP) AND can_execute_in_pure_python
      THEN run deterministic Python solver (&lt;1 ms, 0 LLM tokens) with only that tag's DataSlice
    ELSE IF semantic_micro_inference_required
      THEN invoke ultra-lightweight nano model (yggdrasil-nano / smollm2:135m / qwen2.5:0.5b via shared LocalEngine) on the pre-grouped slice only
    ELSE IF cloud_synthesis_requested AND payload.contains_personal_vault_data == False
      THEN route sanitized summary to LeavesCloudAgent
    ELSE IF cloud_synthesis_requested AND payload.contains_personal_vault_data == True
      THEN BLOCK_CLOUD_GEMINI_CALL AND RAISE PermissionError (or execute strictly locally via TwigsExecutor / NestedCallableLightAgent when fallback allowed)
    ELSE
      route to local TwigsExecutor on the pre-grouped slice via shared LocalEngine
  </logic_rules>
  <verification_criteria>
    - Pre-grouped slicer isolates multi-tag inputs in &lt; 0.5 ms with 0 LLM tokens and enforces taint propagation.
    - ThousandParamMicroModel reports exact parameter_count == 1024 and executes forward scoring in &lt; 0.2 ms using pure Python stdlib math.
    - All 8 deterministic functions validate inputs/outputs via Pydantic BaseModel, return llm_tokens_used == 0, and pass numerical accuracy assertions.
    - NestedCallableLightAgent calls LocalEngine.get_shared() exclusively (zero secondary AsyncOpenAI/Ollama clients).
    - Air-gap tests verify PermissionError is raised before network I/O when contains_personal_vault_data == True on both LeavesCloudAgent and external research_tool_function calls.
  </verification_criteria>
</prompt_spec>
```

### 2.1 Explicit Boolean Routing Rules & Decision Cascade

Canonical `IF / THEN / ELSE` evaluation order executed per `DataSlice`:

- `IF task_matches_deterministic_tag (#TABLE_DATA, #CALC_SOLVE, #DATA_COMPARE, #PDF_CONVERT, #SMART_PDF_LINK, #CODE_OPTIMISE, #CONTROL_SYSTEM, #RESEARCH_GAP) AND can_execute_in_pure_python THEN run deterministic Python solver (<1ms, 0 LLM tokens) with only that tag's DataSlice`
- `ELSE IF semantic_micro_inference_required THEN invoke ultra-lightweight nano model (yggdrasil-nano / smollm2:135m / qwen2.5:0.5b via shared LocalEngine) on the pre-grouped slice only`
- `ELSE IF cloud_synthesis_requested AND payload.contains_personal_vault_data == False THEN route sanitized summary to LeavesCloudAgent`
- `ELSE IF cloud_synthesis_requested AND payload.contains_personal_vault_data == True THEN raise PermissionError (strict air-gap block) or force local TwigsExecutor fallback`

```
Raw Input ─► Pre-Group Slicer (0 tokens) ─► PreGroupedBundle[DataSlice_1..K]
                                                   │
                 ┌─────────────────────────────────┴─────────────────────────────────┐
                 ▼                                                                   │
    ThousandParamMicroModel (1,024 params, <0.2 ms, 0 VRAM)                          │
                 │                                                                   │
                 ├─► IF tag ∈ DETERMINISTIC_TAGS AND can_execute_in_pure_python ─────► Deterministic Solver (0 tokens, <1ms)
                 │                                                                   │
                 ├─► ELSE IF semantic_micro_inference_required ──────────────────────► NestedCallableLightAgent(DataSlice only) via LocalEngine
                 │                                                                   │
                 ├─► ELSE IF cloud_synthesis_requested AND NOT contains_personal_vault_data ─► SanitizedCloudRequest ─► LeavesCloudAgent
                 │                                                                   │
                 └─► ELSE (Air-Gap Tainted or Local Fallback) ───────────────────────► TwigsExecutor (LocalEngine) / PermissionError on forced cloud
```

---

## 3. Pre-Grouped Tag Slicing Protocol (`TagType`, `DataSlice`, `PreGroupedBundle`)

Downstream ultra-lightweight nano models (`yggdrasil-nano`) and deterministic tools **never** scan full unsegmented multi-topic prompts. A zero-LLM deterministic pre-slicer partitions raw input into isolated `DataSlice` objects.

### 3.1 `TagType` Enumeration & Tag Sets

```python
class TagType(str, Enum):
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
```

- **`DETERMINISTIC_TAGS`:** Frozen set of the 8 pure-Python solver tags:
  `{#TABLE_DATA, #CALC_SOLVE, #DATA_COMPARE, #PDF_CONVERT, #SMART_PDF_LINK, #CODE_OPTIMISE, #CONTROL_SYSTEM, #RESEARCH_GAP}`.

### 3.2 `DataSlice` & `PreGroupedBundle` Pydantic Schemas

1. **`DataSlice(BaseModel)`**
   - `slice_id: str` — Unique deterministic identifier (`f"{bundle_id}-s{index}"`, `min_length=1`).
   - `tag: TagType` — Assigned slice classification.
   - `title: str = ""` — Optional short slice header extracted from tag line.
   - `raw_payload: str = Field(min_length=1)` — **Strictly scoped** text/data belonging only to this tag.
   - `structured_kv: dict[str, str | float | int | bool | list[str]] = Field(default_factory=dict)` — Optional pre-parsed `key=value` header parameters inside the slice.
   - `byte_size: int = Field(ge=0)` — UTF-8 byte count of `raw_payload`.
   - `estimated_tokens: int = Field(ge=1)` — Deterministic token proxy: $\max(1, \lceil \text{len}(\text{raw\_payload}) / 4 \rceil)$.
   - `can_execute_in_pure_python: bool = False` — True iff `tag in DETERMINISTIC_TAGS` AND deterministic structural preconditions for that tag are satisfied (e.g., parseable delimiters, valid equation/parameters, valid Python AST, valid FOPDT/step arrays, etc.).
   - `contains_personal_vault_data: bool = True` — Safe-by-default air-gap taint flag.
   - `privacy_tier: PrivacyTier = "air_gapped"` — `Literal["air_gapped", "sanitized"]` (reusing `roots.PrivacyTier`).
   - `source_span: tuple[int, int] = (0, 0)` — Character offsets `(start, end)` in original input; validator enforces `0 <= start <= end`.
   - `priority_weight: float = Field(default=1.0, ge=0.0)` — Priority weight $W_i$ computed by `TrunkRouter`.
   - **Model Validator (Air-Gap Invariant):**
     `IF contains_personal_vault_data == True AND privacy_tier != "air_gapped" THEN raise ValueError("Air-gapped vault data cannot carry privacy_tier='sanitized'.")`

2. **`PreGroupedBundle(BaseModel)`**
   - `bundle_id: str` (`min_length=1`)
   - `source_id: str` (`min_length=1`)
   - `from_personal_vault: bool = True` (safe default)
   - `total_input_chars: int = Field(ge=0)`
   - `slices: list[DataSlice] = Field(default_factory=list)`
   - `untagged_remainder: str = ""` — Narrative text outside explicit tag blocks.
   - `tag_index: dict[TagType, list[str]] = Field(default_factory=dict)` — Maps `TagType -> list[slice_id]` for $O(1)$ lookup.
   - `contains_personal_vault_data: bool = True` — Aggregate taint: `from_personal_vault or any(s.contains_personal_vault_data for s in slices)`.
   - `token_savings_ratio: float = Field(default=0.0, ge=0.0, le=1.0)` — Defined as:
     $$\text{token\_savings\_ratio} = \begin{cases} 0.0 & \text{if } \text{slices} = \emptyset \text{ or } \text{total\_input\_chars} = 0 \\ \max\!\left(0.0,\; 1.0 - \frac{\max_{s \in \text{slices}} \text{len}(s.\text{raw\_payload})}{\text{total\_input\_chars}}\right) & \text{otherwise} \end{cases}$$
   - `slicing_latency_ms: float = Field(default=0.0, ge=0.0)`

### 3.3 Deterministic Slicing Grammar & Algorithm

1. **Explicit Delimiter Grammar ($O(N)$ single-pass scanner, 0 LLM tokens):**
   - Matches block headers at line start matching:
     `^(?:\[)?(#(?:TABLE_DATA|CALC_SOLVE|DATA_COMPARE|PDF_CONVERT|SMART_PDF_LINK|CODE_OPTIMISE|CONTROL_SYSTEM|RESEARCH_GAP|SEMANTIC_MICRO|GENERAL_SYNTHESIS))(?:\])?(?:\s*[:|-]\s*(.*))?$`
   - Optional explicit closing marker `[/#TAG]` or `---END_SLICE---`; otherwise a slice terminates immediately before the next tag header or EOF.
   - Inline `key=value` directives on the header line populate `structured_kv` deterministically without polluting `raw_payload`.
2. **Untagged Fallback Classification:**
   - If no explicit `#TAG` blocks exist in the input, the slicer splits on Markdown `##` sections or fenced code/table blocks (or treats the single input as one candidate block) and passes each block through `ThousandParamMicroModel.predict(...)` (< 0.2 ms) to assign the highest-probability `TagType` and evaluate structural `can_execute_in_pure_python` preconditions.
3. **Mandatory Taint Propagation:**
   - If `from_personal_vault=True` OR deterministic PII/vault pattern triggers (e.g., `personal_vault.db`, `privacy_tier="air_gapped"`, API key/credential tokens), all slices inherit `contains_personal_vault_data=True` and `privacy_tier="air_gapped"`.

---

## 4. Ultra-Lightweight Callable Nano-Model Architecture

### 4.1 `ThousandParamMicroModel` (~1,024 Deterministic Weight Parameters)

`ThousandParamMicroModel` provides sub-millisecond routing, solvability scoring, and privacy-risk screening in pure Python (`math` + `hashlib` only—zero PyTorch/NumPy dependency, **0 VRAM**, **0 LLM tokens**).

#### Exact Parameter Geometry ($P_{\text{total}} = 1,024$)
Let input feature vector $\mathbf{x} \in \mathbb{R}^{48}$, hidden layer $\mathbf{h} \in \mathbb{R}^{16}$, output logits $\mathbf{z} \in \mathbb{R}^{14}$:

- **Layer 1 (Hidden Projection):**
  $$\mathbf{h} = \text{ReLU}(W_1 \mathbf{x} + \mathbf{b}_1), \qquad W_1 \in \mathbb{R}^{16 \times 48}\ (768\text{ params}), \quad \mathbf{b}_1 \in \mathbb{R}^{16}\ (16\text{ params})$$
- **Layer 2 (Multi-Head Logit Projection):**
  $$\mathbf{z} = W_2 \mathbf{h} + \mathbf{b}_2, \qquad W_2 \in \mathbb{R}^{14 \times 16}\ (224\text{ params}), \quad \mathbf{b}_2 \in \mathbb{R}^{14}\ (14\text{ params})$$
- **Global Calibration Scalars (2 params):**
  - $\tau_{\text{temp}} > 0$: softmax temperature scalar (`1` param)
  - $\theta_{\text{esc}} \in \mathbb{R}$: semantic-escalation decision margin (`1` param)

**Exact Total Parameters:**
$$P_{\text{total}} = (16 \times 48) + 16 + (14 \times 16) + 14 + 2 = 768 + 16 + 224 + 14 + 2 = \mathbf{1,024}$$

- **Weight Loading & Invariant:** Initialized from deterministic embedded constants (`DEFAULT_MICRO_WEIGHTS_1024`) or an explicit serialized weight vector JSON (`from_weights(...)`), asserting `model.parameter_count == 1024` (`len(w1_flat) + len(b1) + len(w2_flat) + len(b2) + 2 == 1024`). Pure Python `float` arithmetic guarantees `< 0.2 ms` inference per slice with `0` VRAM.

#### Deterministic 48-Dimensional Feature Extractor $\phi(\text{slice}) \to \mathbf{x} \in \mathbb{R}^{48}$
1. **Dims $x_{0..31}$ (32-dim Signed Hash Projection):**
   Tokenize `raw_payload` (lowercased word tokens + character 3-grams). For each token $w$, compute deterministic `blake2b(digest_size=8)` integer $h(w)$:
   - Bucket index $j = h(w) \bmod 32$
   - Sign $s(w) = +1$ if `(h(w) >> 5) & 1 == 0` else $-1$
   - Accumulate $v_j \mathrel{+}= s(w)$, then $L_2$-normalize: $\mathbf{x}_{0..31} = \mathbf{v} / \max(10^{-12}, \|\mathbf{v}\|_2)$.
2. **Dims $x_{32..47}$ (16-dim Explicit Domain & Structural Signals in $[0, 1]$):**
   - $x_{32}$: Explicit `#TAG` prefix indicator (`1.0` or `0.0`)
   - $x_{33}$: Table delimiter density (`|`, `,`, `\t` line consistency)
   - $x_{34}$: Algebraic / ChemEng formula & SI unit token density (`=`, `^`, `exp`, `log`, `mol`, `kJ`, `Pa`, `K`, `bar`, `Re`)
   - $x_{35}$: Comparison / paired-array density (`baseline`, `candidate`, `delta`, `vs`, `rmse`, `mae`)
   - $x_{36}$: PDF file / page-marker indicator (`.pdf`, `Page `, `%%PDF`, `dehyphenate`)
   - $x_{37}$: PDF cross-link / BM25 query density (`Table`, `Fig`, `Eq`, `[1]`, `section`)
   - $x_{38}$: Python AST/code density (`def `, `async def `, `class `, `import `, `return `)
   - $x_{39}$: Control-system keyword density (`FOPDT`, `PID`, `IMC`, `Ziegler`, `Cohen`, `Kp`, `tau`, `theta`, `IAE`, `ISE`, `ITAE`)
   - $x_{40}$: Research-gap / bibliography token density (`doi`, `arXiv`, `Crossref`, `OpenAlex`, `gap`, `citation`, `references.json`)
   - $x_{41}$: Personal vault / PII risk lexical score (`personal_vault`, `air_gapped`, `private`, `password`, `token`, `secret`, `SSN`)
   - $x_{42}$: Normalized log-length $\min(1.0, \ln(1 + |\text{raw\_payload}|) / 10.0)$
   - $x_{43}$: Line-break density $\min(1.0, \text{lines} / 50.0)$
   - $x_{44}$: Key-value / JSON structure ratio
   - $x_{45}$: Open-ended semantic cue density (`explain`, `summarize`, `brainstorm`, `why`, `interpret`)
   - $x_{46}$: Balanced bracket / syntax regularity score
   - $x_{47}$: Constant bias anchor `1.0`

#### Output Head Mapping ($\mathbf{z}_{0..13}$)
- $\mathbf{z}_{0..9}$: Class logits for the 10 `TagType` values; calibrated probabilities:
  $$p_k = \frac{\exp(z_k / \tau_{\text{temp}})}{\sum_{m=0}^{9} \exp(z_m / \tau_{\text{temp}})}$$
- $z_{10}$: `deterministic_score` $= \sigma(z_{10}) = \frac{1}{1 + e^{-z_{10}}}$
- $z_{11}$: `semantic_escalation_score` $= \sigma(z_{11} - \theta_{\text{esc}})$
- $z_{12}$: `cloud_eligibility_score` $= \sigma(z_{12})$ (advisory only; **never overrides** boolean `contains_personal_vault_data` air-gap guard!)
- $z_{13}$: `privacy_risk_score` $= \sigma(z_{13})$

#### `MicroModelPrediction(BaseModel)` Schema
- `slice_id: str`
- `predicted_tag: TagType`
- `tag_probabilities: dict[TagType, float]` (values in $[0.0, 1.0]$, sum $\approx 1.0$)
- `deterministic_score: float = Field(ge=0.0, le=1.0)`
- `semantic_escalation_score: float = Field(ge=0.0, le=1.0)`
- `cloud_eligibility_score: float = Field(ge=0.0, le=1.0)`
- `privacy_risk_score: float = Field(ge=0.0, le=1.0)`
- `parameter_count: Literal[1024] = 1024`
- `latency_ms: float = Field(ge=0.0)`

---

### 4.2 `NestedCallableLightAgent` (Callable Nano LLM via Shared `LocalEngine`)

Invoked **only** when `semantic_micro_inference_required == True` (e.g., an unstructured note inside a single slice, natural-language interpretation of solver telemetry, or micro-extraction that pure Python cannot complete).

- **Single-VRAM Rule (Law 3):** `NestedCallableLightAgent` MUST obtain its `pydantic_ai.Agent` from `LocalEngine.get_shared(...)` (`self.engine.create_micro_agent(...)`). It MUST NEVER instantiate a second `AsyncOpenAI`, `OllamaModel`, or parallel local server connection.
- **Supported Resident Nano Models:** `yggdrasil-nano` (default target), `smollm2:135m`, `qwen2.5:0.5b` (via Ollama `http://localhost:11434/v1` or LM Studio `http://localhost:1234/v1` fallback).
- **Single-Slice Scope Enforcement:** Accepts `NanoSliceInferenceInput` containing **only one** `DataSlice` (optionally enriched with a compact summary of a deterministic tool result), never the entire raw multi-tag user prompt.

#### Pydantic Schemas for `NestedCallableLightAgent`
1. **`NanoSliceInferenceInput(BaseModel)`:**
   - `slice: DataSlice`
   - `instruction: str = Field(min_length=1, max_length=512)`
   - `micro_hint: MicroModelPrediction | None = None`
   - `deterministic_context: str | None = Field(default=None, max_length=2048)`
   - `max_output_chars: int = Field(default=1024, ge=64, le=4096)`
2. **`NanoSliceInferenceOutput(BaseModel)`:**
   - `slice_id: str`
   - `model_name: str`
   - `concise_answer: str`
   - `extracted_facts: list[str] = Field(default_factory=list)`
   - `confidence: float = Field(default=0.75, ge=0.0, le=1.0)`
   - `requires_cloud_synthesis: bool = False` (forced `False` if `slice.contains_personal_vault_data == True`)
   - `executed_locally: Literal[True] = True`
   - `privacy_tier: PrivacyTier`
   - `latency_ms: float = Field(ge=0.0)`
3. **Callable Async Interface:**
   - `async def __call__(self, request: NanoSliceInferenceInput) -> NanoSliceInferenceOutput`
   - `async def infer_slice(self, request: NanoSliceInferenceInput) -> NanoSliceInferenceOutput`
   - Post-execution taint clamp: if `request.slice.contains_personal_vault_data == True`, force `output.privacy_tier = "air_gapped"` and `output.requires_cloud_synthesis = False`.

---

### 4.3 `NestedModelOrchestrator`

Coordinates the entire nested pipeline for a raw prompt or `PreGroupedBundle`:

1. **`OrchestratorConfig(BaseModel)`:**
   - `allow_cloud_synthesis: bool = False` (safe-by-default!)
   - `allow_external_research: bool = False`
   - `decay_parameters: DecayParameters = Field(default_factory=DecayParameters)`
   - `semantic_escalation_threshold: float = Field(default=0.55, ge=0.0, le=1.0)`
   - `nano_model_name: str = "yggdrasil-nano"`
2. **`SliceExecutionResult(BaseModel)`:**
   - `slice_id: str`
   - `tag: TagType`
   - `execution_tier: Literal["deterministic_python", "nano_local_llm", "twigs_local_llm", "leaves_cloud", "air_gap_blocked"]`
   - `weight_wi: float = Field(ge=0.0)`
   - `should_prune: bool = False`
   - `deterministic_output: BaseModel | None = None`
   - `nano_output: NanoSliceInferenceOutput | None = None`
   - `cloud_output: LeafCloudSynthesis | None = None`
   - `air_gap_blocked: bool = False`
   - `llm_tokens_used: int = Field(default=0, ge=0)`
   - `latency_ms: float = Field(ge=0.0)`
   - `error: str | None = None`
3. **`OrchestratorExecutionReport(BaseModel)`:**
   - `bundle_id: str`
   - `total_slices: int = Field(ge=0)`
   - `deterministic_hits: int = Field(ge=0)`
   - `nano_llm_calls: int = Field(ge=0)`
   - `cloud_calls: int = Field(ge=0)`
   - `air_gap_blocks: int = Field(ge=0)`
   - `token_savings_ratio: float = Field(ge=0.0, le=1.0)`
   - `results: list[SliceExecutionResult] = Field(default_factory=list)`
   - `total_latency_ms: float = Field(ge=0.0)`
4. **Routing Rules Inside `NestedModelOrchestrator.process_bundle(...)`:**
   - Strictly executes the `<logic_rules>` boolean cascade in Section 2.
   - Evaluates `TrunkRouter.evaluate_node(...)` per slice to compute $W_i$ and `should_prune`.
   - Wraps heavy synchronous solvers (`pdf_converter_function` on disk files) in `await asyncio.to_thread(...)` so the async event loop never blocks.
   - Guarantees **zero** tainted data leaves the local process: if `cloud_synthesis_requested` and `slice.contains_personal_vault_data` is `True`, marks `air_gap_blocked=True` (and raises `PermissionError` if `strict_raise_on_cloud_taint=True`).

---

### 4.4 Ollama `Modelfile.yggdrasil-nano` Bridge

Target downstream path (in `/03-agent-foundry/` when implemented): `/03-agent-foundry/modelfiles/Modelfile.yggdrasil-nano`.

Verified Ollama directives (`FROM`, `PARAMETER`, `SYSTEM`):

```dockerfile
# Yggdrasil Nano Resident Micro-Agent (Single-Slice Semantic Inference)
# Primary ultra-fast footprint (~135M params); swap to qwen2.5:0.5b for denser JSON schemas.
FROM smollm2:135m

# Deterministic, low-hallucination decoding over pre-grouped DataSlices
PARAMETER temperature 0.1
PARAMETER seed 0
PARAMETER top_p 0.85
PARAMETER top_k 20
PARAMETER repeat_penalty 1.05
PARAMETER num_ctx 2048
PARAMETER num_predict 512

SYSTEM """
You are yggdrasil-nano, an isolated single-slice local micro-agent.
Operate strictly on the single pre-grouped DataSlice provided in the prompt.
Return concise, structured JSON matching the requested schema.
Never invent citations, DOIs, physical constants, or external facts.
Preserve all air-gap privacy flags and numerical units verbatim.
"""
```

#### `LocalEngine` & Single-VRAM Residency Bridge
- Local CLI build command:
  `ollama create yggdrasil-nano -f ./modelfiles/Modelfile.yggdrasil-nano`
- Alternative higher-capacity nano build tag:
  Change `FROM smollm2:135m` to `FROM qwen2.5:0.5b` (tag `yggdrasil-nano:0.5b`).
- `LocalEngine` integration (single resident instance, Law 3):
  - **Ollama:** `LocalEngineConfig(provider="ollama", ollama_base_url="http://localhost:11434/v1", model_name="yggdrasil-nano")`
  - **LM Studio Fallback:** `LocalEngineConfig(provider="lm_studio", lm_studio_base_url="http://localhost:1234/v1", model_name="smollm2-135m-instruct")`
  - **Single-Tag Residency Rule:** Avoid creating multiple Ollama tags with distinct `num_ctx`/`temperature` parameters for concurrent `roots`/`trunk`/`twigs` calls (which causes VRAM thrashing). Share **one** active `Modelfile` tag via `LocalEngine.get_shared()`. If transitioning explicitly between `qwen2.5:14b` and `yggdrasil-nano`, `await LocalEngine.reset_shared()` MUST be awaited first before calling `LocalEngine.get_shared(nano_config)`.

---

## 5. Deterministic Tool Specifications (All 8 Functions)

All 8 tools share these invariants:
- `llm_tokens_used: Literal[0] = 0` on every output model.
- `execution_time_ms: float = Field(ge=0.0)` measured via `time.perf_counter()`.
- Pure-Python execution without cloud LLM dependencies.
- Safe-by-default `contains_personal_vault_data: bool = True`.

---

### 5.1 `data_handling_function(TableHandlingInput) -> TableHandlingOutput` (`#TABLE_DATA`)

#### Pydantic Input / Output Schemas
- **`TableHandlingInput(BaseModel)`:**
  - `slice_id: str`
  - `raw_table: str = Field(min_length=1)`
  - `input_format: Literal["auto", "csv", "tsv", "markdown", "json_records"] = "auto"`
  - `operations: list[Literal["clean_whitespace", "coerce_numeric", "drop_empty_rows", "deduplicate", "summary_stats", "zscore_outliers", "sort", "filter", "to_markdown", "to_csv"]] = Field(default_factory=lambda: ["clean_whitespace", "coerce_numeric", "summary_stats", "to_markdown"])`
  - `group_by_column: str | None = None`
  - `sort_by_column: str | None = None`
  - `sort_descending: bool = False`
  - `filter_column: str | None = None`
  - `filter_operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "contains"] | None = None`
  - `filter_value: str | float | int | None = None`
  - `zscore_threshold: float = Field(default=3.0, gt=0.0)`
  - `contains_personal_vault_data: bool = True`
- **`ColumnSummaryStats(BaseModel)`:**
  - `column: str`
  - `inferred_dtype: Literal["numeric", "string", "boolean", "mixed", "empty"]`
  - `non_null_count: int = Field(ge=0)`
  - `null_count: int = Field(ge=0)`
  - `mean: float | None = None`
  - `std_dev: float | None = None`
  - `min_val: float | None = None`
  - `median_val: float | None = None`
  - `max_val: float | None = None`
  - `outlier_row_indices: list[int] = Field(default_factory=list)`
- **`GroupAggregateRow(BaseModel)`:**
  - `group_key: str`
  - `row_count: int = Field(ge=0)`
  - `numeric_means: dict[str, float] = Field(default_factory=dict)`
  - `numeric_sums: dict[str, float] = Field(default_factory=dict)`
- **`TableHandlingOutput(BaseModel)`:**
  - `slice_id: str`
  - `detected_format: Literal["csv", "tsv", "markdown", "json_records"]`
  - `headers: list[str]`
  - `row_count: int = Field(ge=0)`
  - `column_count: int = Field(ge=0)`
  - `rows: list[list[str | float | int | bool | None]]`
  - `column_stats: list[ColumnSummaryStats] = Field(default_factory=list)`
  - `grouped_aggregates: list[GroupAggregateRow] = Field(default_factory=list)`
  - `rendered_markdown: str = ""`
  - `rendered_csv: str = ""`
  - `warnings: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Mathematical Formulas
For numeric values $\{x_{1,j}, \dots, x_{n_j,j}\}$ in column $j$ ($n_j \ge 1$):
$$\bar{x}_j = \frac{1}{n_j}\sum_{r=1}^{n_j} x_{r,j}, \qquad s_j = \begin{cases} \sqrt{\frac{1}{n_j - 1}\sum_{r=1}^{n_j} (x_{r,j} - \bar{x}_j)^2} & n_j \ge 2 \\ 0.0 & n_j = 1 \end{cases}$$
Z-score outlier detection (applied only when $s_j > 0$):
$$\text{is\_outlier}(r, j) \iff \frac{|x_{r,j} - \bar{x}_j|}{s_j} > z_{\text{threshold}}$$

#### Verification Criteria
1. Auto-detects CSV, TSV, Markdown pipe tables (stripping separator rows like `| --- | :---: |`), and JSON record lists.
2. Summary stats (`mean`, `std_dev`, `median_val`) match `statistics` stdlib values within $10^{-12}$.
3. Unknown `sort_by_column` or `filter_column` raises `ValueError` deterministically rather than failing silently.

---

### 5.2 `calculation_solver_function(CalculationSolverInput) -> CalculationSolverOutput` (`#CALC_SOLVE`)

#### Pydantic Input / Output Schemas
- **`UnitQuantity(BaseModel)`:**
  - `value: float`
  - `unit: str = Field(min_length=1)`
- **`CalculationSolverInput(BaseModel)`:**
  - `slice_id: str`
  - `mode: Literal["evaluate_expression", "unit_convert", "ideal_gas", "arrhenius", "reynolds_number", "antoine_vapor_pressure", "newton_root", "simpson_integrate"]`
  - `expression: str | None = None`
  - `variables: dict[str, float] = Field(default_factory=dict)`
  - `quantity: UnitQuantity | None = None`
  - `target_unit: str | None = None`
  - `parameters: dict[str, float] = Field(default_factory=dict)`
  - `solve_for: str | None = None`
  - `significant_figures: int = Field(default=6, ge=1, le=15)`
  - `contains_personal_vault_data: bool = True`
- **`CalculationSolverOutput(BaseModel)`:**
  - `slice_id: str`
  - `mode: str`
  - `result_value: float`
  - `result_unit: str = "dimensionless"`
  - `formatted_result: str`
  - `residual_error: float = Field(default=0.0, ge=0.0)`
  - `iterations_used: int = Field(default=0, ge=0)`
  - `formula_applied: str`
  - `unit_conversion_factor: float | None = None`
  - `warnings: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Mathematical & ChemEng Formulations + Safety Rules
1. **AST-Sandboxed Evaluator (`evaluate_expression`):**
   - Strictly forbids `eval()` / `exec()`. Uses `ast.parse(expression, mode="eval")` permitting ONLY:
     `Expression`, `BinOp` (`Add`, `Sub`, `Mult`, `Div`, `FloorDiv`, `Pow`, `Mod`), `UnaryOp` (`UAdd`, `USub`), `Constant` (`int | float`, explicitly rejecting `bool` via `not isinstance(node.value, bool)` and enforcing `math.isfinite`), `Name` (`ast.Load` context only, in `variables` or constants `pi`, `e`, `R_gas=8.31446261815324`), and `Call` (`ast.Name` function in whitelisted math functions `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `exp`, `log`, `log10`, `sqrt`, `abs`, `pow`, `min`, `max`, with `not node.keywords` and no `ast.Starred` args).
   - Guard `ast.Pow` exponents with `abs(right) <= 1000.0` (DoS guard) and reject non-finite outputs via `math.isfinite`.
   - Any disallowed AST node (`Attribute`, `Subscript`, `Import`, `Lambda`, etc.) raises `ValueError`.
2. **Dimensional & Affine Unit Conversion (`unit_convert`):**
   - Each supported unit stores SI dimension vector $(M, L, T, \Theta, N)$ and scale/offset relative to SI base.
   - Dimension mismatch (e.g., `bar` to `K`) raises `ValueError`.
   - Temperature conversions: $T_{\text{K}} = T_{^\circ\text{C}} + 273.15 = \frac{5}{9}(T_{^\circ\text{F}} - 32) + 273.15$.
3. **Ideal Gas Law (`ideal_gas`):**
   - $P V = n R T$ ($R = 8.31446261815324\ \text{J}\cdot\text{mol}^{-1}\cdot\text{K}^{-1}$; $P$ in Pa, $V$ in $\text{m}^3$, $n$ in mol, $T > 0$ in K).
4. **Arrhenius Kinetics (`arrhenius`):**
   - $k(T) = A \exp\!\left(-\frac{E_a}{R T}\right)$ ($E_a$ in $\text{J/mol}$, $T > 0\ \text{K}$, $A > 0$).
5. **Reynolds Number (`reynolds_number`):**
   - $\mathrm{Re} = \frac{\rho v D}{\mu}$ ($\mu > 0$, $D > 0$, $\rho > 0$), appending regime note (`laminar` $< 2100$, `transitional` $[2100, 4000]$, `turbulent` $> 4000$).
6. **Antoine Equation (`antoine_vapor_pressure`):**
   - $P_{\text{mmHg}} = 10^{\,A - \frac{B}{C + T_{^\circ\text{C}}}}$ (guards $C + T_{^\circ\text{C}} = 0$).
7. **Newton-Raphson Root Solver (`newton_root`):**
   - Finds $f(x) = 0$ from `x0` via $x_{k+1} = x_k - \frac{f(x_k)}{f'(x_k)}$ with central derivative $h = 10^{-7}\max(1.0, |x_k|)$, max 100 iterations, tolerance $|f(x_k)| < 10^{-10}$, guarding $|f'(x_k)| < 10^{-14}$.
8. **Composite Simpson's $1/3$ Quadrature (`simpson_integrate`):**
   - Over $[a, b]$ with forced even $n_{\text{steps}} \ge 2$:
     $$I \approx \frac{b-a}{3 n}\left[f(x_0) + 4\sum_{\text{odd } k} f(x_k) + 2\sum_{\text{even } k} f(x_k) + f(x_n)\right]$$

#### Verification Criteria
1. Injection test `__import__('os').system('echo pwn')` raises `ValueError` without execution.
2. `ideal_gas`, `arrhenius`, `unit_convert`, `newton_root`, and `simpson_integrate` match analytical solutions to $\le 10^{-8}$ relative error.

---

### 5.3 `data_comparison_function(DataComparisonInput) -> DataComparisonOutput` (`#DATA_COMPARE`)

#### Pydantic Input / Output Schemas
- **`DataComparisonInput(BaseModel)`:**
  - `slice_id: str`
  - `comparison_mode: Literal["numeric_series", "key_value_records", "table_diff"]`
  - `baseline_label: str = "baseline"`
  - `candidate_label: str = "candidate"`
  - `baseline_series: list[float] = Field(default_factory=list)`
  - `candidate_series: list[float] = Field(default_factory=list)`
  - `baseline_record: dict[str, str | float | int | bool | None] = Field(default_factory=dict)`
  - `candidate_record: dict[str, str | float | int | bool | None] = Field(default_factory=dict)`
  - `abs_tolerance: float = Field(default=1e-6, ge=0.0)`
  - `rel_tolerance: float = Field(default=0.01, ge=0.0)`
  - `contains_personal_vault_data: bool = True`
- **`FieldDelta(BaseModel)`:**
  - `key: str`
  - `status: Literal["matched", "modified", "added", "removed", "tolerance_exceeded"]`
  - `baseline_value: str | float | int | bool | None = None`
  - `candidate_value: str | float | int | bool | None = None`
  - `abs_delta: float | None = None`
  - `rel_delta: float | None = None`
- **`NumericErrorMetrics(BaseModel)`:**
  - `sample_count: int = Field(ge=0)`
  - `mae: float = Field(ge=0.0)`
  - `rmse: float = Field(ge=0.0)`
  - `max_abs_error: float = Field(ge=0.0)`
  - `mape_percent: float | None = Field(default=None, ge=0.0)`
  - `pearson_r: float | None = Field(default=None, ge=-1.0, le=1.0)`
  - `r_squared: float | None = None`
  - `within_tolerance_count: int = Field(ge=0)`
  - `total_compared: int = Field(ge=0)`
- **`DataComparisonOutput(BaseModel)`:**
  - `slice_id: str`
  - `comparison_mode: str`
  - `all_within_tolerance: bool`
  - `numeric_metrics: NumericErrorMetrics | None = None`
  - `field_deltas: list[FieldDelta] = Field(default_factory=list)`
  - `summary: str`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Mathematical Formulas
For aligned baseline $y_k$ and candidate $\hat{y}_k$ ($k = 1 \dots N$, requiring $N \ge 1$ and $|y| = |\hat{y}|$):
$$\text{MAE} = \frac{1}{N}\sum_{k=1}^N |\hat{y}_k - y_k|, \qquad \text{RMSE} = \sqrt{\frac{1}{N}\sum_{k=1}^N (\hat{y}_k - y_k)^2}$$
$$\text{MAPE (\%)} = \frac{100}{|\{k : y_k \ne 0\}|}\sum_{y_k \ne 0} \frac{|\hat{y}_k - y_k|}{|y_k|}$$
$$R^2 = 1 - \frac{\sum_{k=1}^N (\hat{y}_k - y_k)^2}{\sum_{k=1}^N (y_k - \bar{y})^2}, \qquad r = \frac{\sum_{k=1}^N (y_k - \bar{y})(\hat{y}_k - \bar{\hat{y}})}{\sqrt{\sum_{k=1}^N (y_k - \bar{y})^2 \sum_{k=1}^N (\hat{y}_k - \bar{\hat{y}})^2}}$$
Tolerance predicate per scalar or series element:
$$|\hat{y}_k - y_k| \le \text{abs\_tolerance} + \text{rel\_tolerance} \cdot |y_k|$$

#### Verification Criteria
1. Identical vectors yield `mae == 0.0`, `rmse == 0.0`, `r_squared == 1.0`, `pearson_r == 1.0`, and `all_within_tolerance == True`.
2. Mismatched vector lengths raise `ValueError`.
3. Zero-variance baseline handles $R^2 = \text{None}$ and `pearson_r = None` without `ZeroDivisionError`.

---

### 5.4 `pdf_converter_function(PdfConverterInput) -> PdfConverterOutput` (`#PDF_CONVERT`)

#### Pydantic Input / Output Schemas
- **`PdfPageArtifact(BaseModel)`:**
  - `page_number: int = Field(ge=1)`
  - `char_count: int = Field(ge=0)`
  - `word_count: int = Field(ge=0)`
  - `extracted_text: str`
  - `detected_headings: list[str] = Field(default_factory=list)`
  - `detected_tables_count: int = Field(default=0, ge=0)`
- **`PdfConverterInput(BaseModel)`:**
  - `slice_id: str`
  - `source_path: str | None = None`
  - `raw_extracted_pages: list[str] | None = None`
  - `page_range: tuple[int, int] | None = None` (validated `1 <= start <= end`)
  - `output_format: Literal["markdown", "plain_text", "page_chunks"] = "markdown"`
  - `normalize_whitespace: bool = True`
  - `dehyphenate_linebreaks: bool = True`
  - `strip_headers_footers: bool = True`
  - `contains_personal_vault_data: bool = True`
- **`PdfConverterOutput(BaseModel)`:**
  - `slice_id: str`
  - `source_sha256: str`
  - `total_pages: int = Field(ge=0)`
  - `converted_pages: list[PdfPageArtifact] = Field(default_factory=list)`
  - `combined_markdown: str`
  - `detected_dois: list[str] = Field(default_factory=list)`
  - `detected_equations_count: int = Field(default=0, ge=0)`
  - `warnings: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Deterministic Rules & Air-Gap Constraints
1. **Input Guard:** Rejects remote `http://` / `https://` `source_path` values (`ValueError`); accepts only local files or `raw_extracted_pages`. Requires either `source_path` or `raw_extracted_pages`.
2. **Offline Parser Priority (`pypdf`):** Downstream `/03-agent-foundry/pyproject.toml` MUST declare `pypdf>=4.0.0` (verified pure-Python PDF parser). Uses `pypdf.PdfReader(..., strict=True)` locally (checking `reader.is_encrypted` and calling `reader.decrypt(...)` or raising `PermissionError`/`ValueError` when password-locked without key), falling back to `pymupdf` (`fitz`) only if explicitly installed. Raises `RuntimeError` if a binary `.pdf` is provided without `pypdf`/`fitz` and without `raw_extracted_pages`. Never transmits PDF bytes externally.
3. **Deterministic Cleaning:**
   - Dehyphenate line breaks: `re.sub(r"([A-Za-z])-\r?\n([a-z])", r"\1\2", text)`
   - Repeated top/bottom lines across $\ge 60\%$ of pages (when total pages $\ge 3$) are stripped as running headers/footers if `strip_headers_footers=True`.
   - Extract DOIs deterministically via `r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b"`.
   - Compute `source_sha256` over file bytes or joined UTF-8 page text.

#### Verification Criteria
1. Dehyphenation rejoins split words (`"thermo-\ndynamics"` $\to$ `"thermodynamics"`).
2. Repeated running header across 4/4 pages is removed cleanly when `strip_headers_footers=True`.
3. Remote URL `source_path` is rejected before any file/network access.

---

### 5.5 `smart_pdf_handling_function(SmartPdfInput) -> SmartPdfOutput` (`#SMART_PDF_LINK`)

#### Pydantic Input / Output Schemas
- **`PdfSectionNode(BaseModel)`:**
  - `section_id: str`
  - `heading: str`
  - `page_start: int = Field(ge=1)`
  - `page_end: int = Field(ge=1)`
  - `text_excerpt: str`
  - `relevance_score: float = Field(default=0.0, ge=0.0)`
  - `decay_weight_wi: float = Field(default=1.0, ge=0.0)`
  - `linked_citations: list[str] = Field(default_factory=list)`
  - `linked_equations: list[str] = Field(default_factory=list)`
  - `linked_tables: list[str] = Field(default_factory=list)`
- **`SmartPdfEdge(BaseModel)`:**
  - `source_section_id: str`
  - `target_ref: str`
  - `relation: Literal["cites", "references_table", "references_figure", "references_equation", "continues_topic"]`
  - `page_number: int = Field(ge=1)`
- **`SmartPdfInput(BaseModel)`:**
  - `slice_id: str`
  - `pages: list[PdfPageArtifact] = Field(min_length=1)`
  - `source_path: str | None = None` (optional local PDF path for native `/Annots` `/Link` / `/GoTo` `/D` / `/Dest` / `named_destinations` resolution via `pypdf`)
  - `query: str | None = None`
  - `top_k: int = Field(default=5, ge=1, le=50)`
  - `decay_rate: float = Field(default=0.05, ge=0.0)`
  - `alpha: float = Field(default=0.15, ge=0.0)`
  - `contains_personal_vault_data: bool = True`
- **`SmartPdfOutput(BaseModel)`:**
  - `slice_id: str`
  - `sections: list[PdfSectionNode]`
  - `top_matching_sections: list[PdfSectionNode] = Field(default_factory=list)`
  - `cross_links: list[SmartPdfEdge] = Field(default_factory=list)`
  - `citation_keys_found: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Mathematical Ranking & $W_i$ Resonance Coupling
1. **Okapi BM25 ($k_1 = 1.5, b = 0.75$):**
   For query terms $q$ and section $d$ of token count $|d|$ across $N_{\text{sec}}$ sections with mean length $\bar{L}$:
   $$\text{BM25}(q, d) = \sum_{t \in q} \ln\!\left(\frac{N_{\text{sec}} - \text{df}(t) + 0.5}{\text{df}(t) + 0.5} + 1\right)\cdot \frac{\text{tf}(t, d)(k_1 + 1)}{\text{tf}(t, d) + k_1\left(1 - b + b\frac{|d|}{\bar{L}}\right)}$$
2. **Yggdrasil Context-Decay Priority Coupling:**
   Each section's cross-reference count forms its resonance signal $R_i = |\text{cross\_links}(i)|$:
   $$W_i = W_{i,0}\, e^{-\lambda \Delta t} + \alpha R_i$$
   where $W_{i,0} = 1.0 + \text{BM25}(q, d_i)$ (or $1.0$ if `query is None`) and $\Delta t$ defaults to `0.0` for freshly indexed pages.

#### Verification Criteria
1. Deterministic cross-link regex captures `[1]`, `[2, 5]`, `Table 2`, `Fig. 3`, and `Eq. 4.1` into typed `SmartPdfEdge` objects.
2. BM25 ranks sections containing rare exact query terms strictly higher than unrelated sections.

---

### 5.6 `coding_optimiser_function(CodingOptimiserInput) -> CodingOptimiserOutput` (`#CODE_OPTIMISE`)

#### Pydantic Input / Output Schemas
- **`CodeFinding(BaseModel)`:**
  - `rule_id: str`
  - `severity: Literal["info", "warning", "error", "critical"]`
  - `line_number: int = Field(ge=1)`
  - `symbol_name: str = ""`
  - `message: str`
  - `deterministic_fix_hint: str = ""`
- **`FunctionMetric(BaseModel)`:**
  - `name: str`
  - `is_async: bool`
  - `line_start: int = Field(ge=1)`
  - `line_end: int = Field(ge=1)`
  - `cyclomatic_complexity: int = Field(ge=1)`
  - `max_nesting_depth: int = Field(ge=0)`
  - `has_complete_type_annotations: bool`
- **`CodingOptimiserInput(BaseModel)`:**
  - `slice_id: str`
  - `source_code: str = Field(min_length=1)`
  - `language: Literal["python"] = "python"`
  - `max_cyclomatic_complexity: int = Field(default=10, ge=1)`
  - `max_nesting_depth: int = Field(default=4, ge=1)`
  - `enforce_yggdrasil_qa_rules: bool = True`
  - `contains_personal_vault_data: bool = True`
- **`CodingOptimiserOutput(BaseModel)`:**
  - `slice_id: str`
  - `syntax_valid: bool`
  - `syntax_error: str | None = None`
  - `loc: int = Field(ge=0)`
  - `function_metrics: list[FunctionMetric] = Field(default_factory=list)`
  - `findings: list[CodeFinding] = Field(default_factory=list)`
  - `maintainability_score: float = Field(default=100.0, ge=0.0, le=100.0)`
  - `passes_qa_static_gate: bool`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Deterministic AST Metrics & Yggdrasil QA Rules
1. **McCabe Cyclomatic Complexity per Function:**
   $$M = 1 + |\{\text{If}, \text{For}, \text{AsyncFor}, \text{While}, \text{With}, \text{AsyncWith}, \text{ExceptHandler}, \text{IfExp}, \text{comprehension.ifs}\}| + \sum_{b \in \text{BoolOp}} (|b.\text{values}| - 1)$$
2. **Maintainability Proxy ($\in [0, 100]$):**
   $$S_{\text{maint}} = \max\!\Big(0.0,\; \min\!\Big(100.0,\; 100.0 - 2.0\max(0, \bar{M} - 3) - 8.0 N_{\text{error/crit}} - 2.0 N_{\text{warn}}\Big)\Big)$$
3. **Deterministic Yggdrasil & Structural AST Rules (`enforce_yggdrasil_qa_rules=True`):**
   - Scope-isolated `ast.NodeVisitor` resets loop/async nesting depth on nested `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` boundaries, and restores depth in `try ... finally`.
   - `YGG-ASYNC-001` (`error`): `time.sleep(...)`, `requests.*`, `urllib.request.urlopen`, `subprocess.run`, or sync `httpx.get/post` called inside `ast.AsyncFunctionDef` (excluding callables explicitly offloaded via `asyncio.to_thread(...)` or `loop.run_in_executor(...)`).
   - `YGG-VRAM-002` (`error`): Direct instantiation of `AsyncOpenAI(...)` or `OllamaModel(...)` outside `local_engine.py` / `LocalEngine`.
   - `YGG-AIRGAP-003` (`critical`): References to `personal_vault` alongside `LeavesCloudAgent` or `genai.Client` in the same function scope.
   - `YGG-TYPE-004` (`warning`): Public function missing parameter or return type annotations.
   - `PY-MUTABLE-005` (`error`): Mutable default literal (`[]`, `{}`, `set()`) in function signature.
   - `PY-COMPLEXITY-006` (`warning`): $M > \text{max\_cyclomatic\_complexity}$ or loop/comprehension nesting (`For`, `AsyncFor`, `While`, plus multi-generator `ListComp`/`SetComp`/`DictComp`/`GeneratorExp` clauses `len(node.generators)`) $> \text{max\_nesting\_depth}$.

#### Verification Criteria
1. Flags `async def f(): time.sleep(1)` with `YGG-ASYNC-001` and `passes_qa_static_gate == False`.
2. Invalid Python syntax sets `syntax_valid == False` and captures `syntax_error` cleanly without crashing.

---

### 5.7 `control_system_optimiser_function(ControlSystemInput) -> ControlSystemOutput` (`#CONTROL_SYSTEM`)

#### Pydantic Input / Output Schemas
- **`FopdtModelParams(BaseModel)`:**
  - `kp: float` (must satisfy `kp != 0.0`)
  - `tau: float = Field(gt=0.0)`
  - `theta: float = Field(ge=0.0)`
  - `time_unit: str = "s"`
- **`PidGains(BaseModel)`:**
  - `kc: float`
  - `tau_i: float = Field(ge=0.0)` (`0.0` denotes no integral action for P-only)
  - `tau_d: float = Field(ge=0.0)`
  - `ki: float` (`kc / tau_i` if `tau_i > 0` else `0.0`)
  - `kd: float` (`kc * tau_d`)
  - `controller_type: Literal["P", "PI", "PID"]`
  - `tuning_method: Literal["imc", "simc", "ziegler_nichols", "cohen_coon"]`
- **`StepPerformanceMetrics(BaseModel)`:**
  - `iae: float = Field(ge=0.0)`
  - `ise: float = Field(ge=0.0)`
  - `itae: float = Field(ge=0.0)`
  - `overshoot_percent: float = Field(ge=0.0)`
  - `rise_time: float | None = Field(default=None, ge=0.0)`
  - `settling_time: float | None = Field(default=None, ge=0.0)`
  - `steady_state_error: float = Field(ge=0.0)`
  - `is_stable: bool`
- **`TuningCandidateResult(BaseModel)`:**
  - `gains: PidGains`
  - `performance: StepPerformanceMetrics`
- **`ControlSystemInput(BaseModel)`:**
  - `slice_id: str`
  - `fopdt: FopdtModelParams | None = None`
  - `step_test_times: list[float] | None = None`
  - `step_test_pv: list[float] | None = None`
  - `step_test_delta_u: float | None = None`
  - `controller_type: Literal["P", "PI", "PID"] = "PID"`
  - `tuning_method: Literal["imc", "simc", "ziegler_nichols", "cohen_coon", "auto_best_itae"] = "imc"`
  - `imc_tau_c: float | None = Field(default=None, gt=0.0)`
  - `setpoint_step: float = 1.0`
  - `simulation_horizon: float | None = Field(default=None, gt=0.0)`
  - `dt: float | None = Field(default=None, gt=0.0)`
  - `actuator_min: float | None = None`
  - `actuator_max: float | None = None`
  - `max_overshoot_percent: float = Field(default=25.0, ge=0.0)`
  - `include_trajectory: bool = False`
  - `contains_personal_vault_data: bool = True`
- **`ControlSystemOutput(BaseModel)`:**
  - `slice_id: str`
  - `identified_fopdt: FopdtModelParams`
  - `theta_over_tau: float = Field(ge=0.0)`
  - `recommended_gains: PidGains`
  - `performance: StepPerformanceMetrics`
  - `candidate_comparisons: list[TuningCandidateResult] = Field(default_factory=list)`
  - `time_points: list[float] = Field(default_factory=list)`
  - `pv_trajectory: list[float] = Field(default_factory=list)`
  - `mv_trajectory: list[float] = Field(default_factory=list)`
  - `warnings: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: Literal[True] = True`

#### Mathematical Equations: FOPDT Identification, PID Tuning & Closed-Loop Simulator

1. **FOPDT Plant & Empirical Two-Point Identification (Smith Method):**
   $$G_p(s) = \frac{K_p e^{-\theta s}}{\tau s + 1}$$
   If `fopdt` is omitted and `(step_test_times, step_test_pv, step_test_delta_u)` are supplied (requiring $\Delta u \ne 0$ and strictly increasing $t$):
   $$K_p = \frac{y_{\infty} - y_0}{\Delta u}, \qquad \tau = 1.5\,(t_{63.2\%} - t_{28.3\%}), \qquad \theta = \max(0.0,\; t_{63.2\%} - \tau)$$
   where $t_{28.3\%}, t_{63.2\%}$ are obtained by linear interpolation on the normalized step trajectory $(y(t) - y_0)/(y_\infty - y_0)$.

2. **PID Tuning Rules (for non-zero $K_p$; negative $K_p$ naturally yields reverse-acting $K_c$ so $K_c K_p > 0$):**
   - **IMC (Rivera–Morari–Skogestad):** With $\tau_c = \text{imc\_tau\_c}$ or default $\max(0.25\tau,\, 0.8\theta)$:
     - **PI:** $K_c = \frac{\tau}{K_p(\tau_c + \theta)}, \quad \tau_I = \tau, \quad \tau_D = 0$
     - **PID (1st-order Padé):** $K_c = \frac{\tau + 0.5\theta}{K_p(\tau_c + 0.5\theta)}, \quad \tau_I = \tau + 0.5\theta, \quad \tau_D = \frac{\tau \theta}{2\tau + \theta}$
     - **P:** $K_c = \frac{\tau}{K_p(\tau_c + \theta)}, \quad \tau_I = 0, \quad \tau_D = 0$
   - **SIMC (Skogestad IMC):**
     $$K_c = \frac{\tau}{K_p(\tau_c + \theta)}, \qquad \tau_I = \min\!\big(\tau,\; 4(\tau_c + \theta)\big), \qquad \tau_D = 0.0$$
     *(Skogestad SIMC for FOPDT models is natively PI with $\tau_D = 0.0$; if `controller_type="PID"` is requested under `"simc"`, set $\tau_D = 0.0$ and emit an informational warning or select `"imc"` for Padé derivative action.)*
   - **Ziegler–Nichols (Open-Loop, requires $\theta > 0$):**
     - **P:** $K_c = \frac{\tau}{K_p\theta}$
     - **PI:** $K_c = \frac{0.9\tau}{K_p\theta}, \quad \tau_I = \frac{10}{3}\theta$
     - **PID:** $K_c = \frac{1.2\tau}{K_p\theta}, \quad \tau_I = 2.0\theta, \quad \tau_D = 0.5\theta$
   - **Cohen–Coon (requires $\theta > 0$, let $r = \theta/\tau$):**
     - **P:** $K_c = \frac{\tau}{K_p\theta}\left(1 + \frac{r}{3}\right)$
     - **PI:** $K_c = \frac{\tau}{K_p\theta}\left(0.9 + \frac{r}{12}\right), \quad \tau_I = \theta\left(\frac{30 + 3r}{9 + 20r}\right)$
     - **PID:** $K_c = \frac{\tau}{K_p\theta}\left(\frac{4}{3} + \frac{r}{4}\right), \quad \tau_I = \theta\left(\frac{32 + 6r}{13 + 8r}\right), \quad \tau_D = \theta\left(\frac{4}{11 + 2r}\right)$
   *(Note: if $\theta = 0$ and `ziegler_nichols` or `cohen_coon` is requested, fallback cleanly to $\theta_{\text{eff}} = 10^{-3}\tau$ with an explicit warning or recommend `imc`.)*

3. **Closed-Loop Exact-ZOH Step-Response Simulator & Error Integrals:**
   - Default simulation horizon $T_{\text{sim}} = \max(10\tau,\, 12(\tau + \theta))$; step $\Delta t = \min(0.02\tau,\, 0.1\theta \text{ if } \theta > 0 \text{ else } 0.02\tau,\, T_{\text{sim}} / 400)$.
   - Delay buffer index $d = \text{round}(\theta / \Delta t)$; exact ZOH plant update:
     $$y_{k+1} = e^{-\Delta t/\tau} y_k + K_p\left(1 - e^{-\Delta t/\tau}\right) u_{k - d}$$
   - Discrete PID with derivative-on-measurement filter ($T_f = 0.1 \tau_D$) and optional actuator saturation `[actuator_min, actuator_max]` with anti-windup freeze.
   - Trapezoidal error integrals over $[0, T_{\text{sim}}]$:
     $$\text{IAE} = \sum_{k=0}^{N-1} \frac{|e_k| + |e_{k+1}|}{2}\Delta t, \qquad \text{ISE} = \sum_{k=0}^{N-1} \frac{e_k^2 + e_{k+1}^2}{2}\Delta t, \qquad \text{ITAE} = \sum_{k=0}^{N-1} \frac{t_k|e_k| + t_{k+1}|e_{k+1}|}{2}\Delta t$$
   - Stability criterion `is_stable`: true iff $\max_k |y_k| < 10 |r_{\text{step}}|$, no NaN/Inf, and late-window max absolute error (final 20% of horizon) $\le \max(0.15 |r_{\text{step}}|, 10^{-6})$ and smaller than peak error.
   - `auto_best_itae`: Evaluates all valid methods (`imc`, `simc`, `ziegler_nichols`, `cohen_coon`) in pure Python and picks the stable candidate minimizing `ITAE` subject to `overshoot_percent <= max_overshoot_percent` (or lowest overshoot if none satisfies cap).

#### Verification Criteria
1. For $K_p = 2.0, \tau = 10.0, \theta = 2.0$, IMC-PID with $\tau_c = 2.0$ yields $K_c = 1.833333\dots$, $\tau_I = 11.0$, $\tau_D = 0.90909\dots$, `is_stable == True`, and `steady_state_error < 0.02`.
2. Two-point step identification recovers $(K_p, \tau, \theta)$ within $\le 3\%$ from a synthetic noiseless FOPDT step curve.

---

### 5.8 `research_tool_function(ResearchToolInput) -> ResearchToolOutput` (`#RESEARCH_GAP`)

#### Pydantic Input / Output Schemas
- **`ReferenceEntry(BaseModel)`:**
  - `ref_id: str`
  - `title: str`
  - `authors: list[str] = Field(default_factory=list)`
  - `year: int | None = None`
  - `doi: str | None = None`
  - `url: str | None = None`
  - `tags: list[str] = Field(default_factory=list)`
  - `abstract_or_notes: str = ""`
- **`ReferenceMatch(BaseModel)`:**
  - `ref_id: str`
  - `source: Literal["local_references_json", "crossref", "arxiv", "openalex"]`
  - `title: str`
  - `authors: list[str] = Field(default_factory=list)`
  - `year: int | None = None`
  - `doi: str | None = None`
  - `url: str | None = None`
  - `relevance_score: float = Field(ge=0.0)`
- **`ResearchGapItem(BaseModel)`:**
  - `gap_id: str`
  - `gap_type: Literal["missing_citation", "unverified_claim", "outdated_evidence", "methodological_gap", "missing_doi"]`
  - `severity: Literal["low", "medium", "high"]`
  - `excerpt: str`
  - `suggested_queries: list[str] = Field(default_factory=list)`
- **`ResearchToolInput(BaseModel)`:**
  - `slice_id: str`
  - `research_text: str = Field(min_length=1)`
  - `query_terms: list[str] = Field(default_factory=list)`
  - `dois_to_verify: list[str] = Field(default_factory=list)`
  - `local_references: list[ReferenceEntry] = Field(default_factory=list)`
  - `references_json_path: str | None = None` (optional path injected by `/04-yggdrasil-app/` and read via `asyncio.to_thread` when `local_references` is empty)
  - `allow_external_lookup: bool = False` (safe default!)
  - `external_providers: list[Literal["crossref", "arxiv", "openalex"]] = Field(default_factory=lambda: ["crossref", "openalex"])`
  - `min_local_matches_before_external: int = Field(default=1, ge=0)`
  - `max_results_per_provider: int = Field(default=5, ge=1, le=20)`
  - `contains_personal_vault_data: bool = True` (safe default!)
  - `privacy_tier: PrivacyTier = "air_gapped"`
  - `crossref_mailto: str | None = None`
- **`ResearchToolOutput(BaseModel)`:**
  - `slice_id: str`
  - `air_gap_status: Literal["local_only", "external_blocked_tainted", "external_sanitized_executed"]`
  - `local_matches: list[ReferenceMatch] = Field(default_factory=list)`
  - `external_matches: list[ReferenceMatch] = Field(default_factory=list)`
  - `identified_gaps: list[ResearchGapItem] = Field(default_factory=list)`
  - `providers_queried: list[str] = Field(default_factory=list)`
  - `warnings: list[str] = Field(default_factory=list)`
  - `execution_time_ms: float = Field(ge=0.0)`
  - `llm_tokens_used: Literal[0] = 0`
  - `executed_locally: bool = True` (`True` for `"local_only"` and `"external_blocked_tainted"`, `False` when `"external_sanitized_executed"`)

#### Strict Air-Gap Privacy Guard & Verified External Metadata Rules
1. **Hard Air-Gap Reject Gate (executed BEFORE any external HTTP construction):**
   ```
   IF payload.allow_external_lookup == True AND (
       payload.contains_personal_vault_data == True
       OR payload.privacy_tier != "sanitized"
   ) THEN RAISE PermissionError("Air-gap violation: external research queries are prohibited on personal_vault/tainted data.")
   ```
   Additionally, run deterministic lexical PII/vault screening on `query_terms` / `dois_to_verify` (`personal_vault.db`, `air_gapped`, email/credential/token patterns); if detected, raise `PermissionError` before outbound HTTP.
2. **Local-First Lookup (`references.json`):**
   - Caller (`/04-yggdrasil-app/`) injects entries loaded from `/04-yggdrasil-app/vaults/references.json` into `local_references`.
   - Deterministic scoring compares normalized `query_terms`, `dois_to_verify`, and `research_text` keywords against `ReferenceEntry` (`title`, `tags`, `doi`, `abstract_or_notes`).
   - If `len(local_matches) >= payload.min_local_matches_before_external` OR `not payload.allow_external_lookup`, return immediately with `air_gap_status="local_only"` and `0` network calls.
3. **Verified Async External Metadata Endpoints (`httpx.AsyncClient`):**
   - Executed asynchronously via `async def research_tool_function(payload: ResearchToolInput, http_client: httpx.AsyncClient | None = None) -> ResearchToolOutput` (with pure-sync `evaluate_local_research_gaps(payload)` helper for offline-only paths).
   - Strict host allowlist:
     - **Crossref REST API:** `https://api.crossref.org/works/{doi}` or `https://api.crossref.org/works?query=...&rows=...&select=DOI,title,author,published,URL` (append `&mailto=...` when `crossref_mailto` is supplied).
     - **arXiv API (Atom 1.0 XML):** `https://export.arxiv.org/api/query?search_query=all:...&max_results=...` (parsed safely via `xml.etree.ElementTree`, respecting arXiv's $\le 1\ \text{req}/3\ \text{s}$ rate-limit constraint).
     - **OpenAlex REST API:** `https://api.openalex.org/works?search=...&per-page=...` or `https://api.openalex.org/works/https://doi.org/{doi}`.
   - Never sends `payload.research_text` verbatim to external APIs—only sanitized keyword `query_terms` or valid `dois_to_verify`!

#### Verification Criteria
1. Calling `research_tool_function` with `allow_external_lookup=True` and `contains_personal_vault_data=True` raises `PermissionError` with **0** `httpx` requests issued.
2. With `local_references` containing a matching ChemEng citation and `min_local_matches_before_external=1`, external providers are never queried (`providers_queried == []`).
3. Gap detector flags quantitative/comparative assertions lacking citations or DOIs with `llm_tokens_used == 0`.

---

## 6. Downstream Package & Application Placement Matrix

| Artifact / Module | Target Directory | Allowed Role |
| :--- | :--- | :--- |
| `pre_slicer.py` (`TagType`, `DataSlice`, `PreGroupedBundle`, `pre_group_prompt`) | `/03-agent-foundry/yggdrasil_agents/` | Pure-Python deterministic tag slicing & taint propagation |
| `micro_model.py` (`ThousandParamMicroModel`, `MicroModelPrediction`) | `/03-agent-foundry/yggdrasil_agents/` | 1,024-parameter deterministic CPU router/scorer |
| `nano_agent.py` (`NestedCallableLightAgent`, `NanoSliceInferenceInput/Output`) | `/03-agent-foundry/yggdrasil_agents/` | Single-slice nano LLM wrapper bound to shared `LocalEngine` |
| `deterministic_tools.py` (all 8 deterministic functions & Pydantic I/O models) | `/03-agent-foundry/yggdrasil_agents/` | Zero-token pure-Python solvers + air-gapped async research metadata |
| `orchestrator.py` (`NestedModelOrchestrator`, `OrchestratorConfig`, `OrchestratorExecutionReport`) | `/03-agent-foundry/yggdrasil_agents/` | `IF/THEN/ELSE` nested dispatch integrating `TrunkRouter` + `LeavesCloudAgent` |
| `__init__.py` & `pyproject.toml` (`pypdf>=4.0.0`) | `/03-agent-foundry/` | Public symbol exports & pure-Python PDF parsing dependency |
| `modelfiles/Modelfile.yggdrasil-nano` | `/03-agent-foundry/modelfiles/` | Reproducible Ollama blueprint for `yggdrasil-nano` |
| `tests/test_nested_nano_and_tools.py` | `/03-agent-foundry/tests/` | Unit tests covering 1,024 params, all 8 tools, VRAM single-engine lock, and `PermissionError` air-gap checks |
| Vault injection (`references.json` loader & `state_tree.db` node sync) | `/04-yggdrasil-app/` | Loads `/04-yggdrasil-app/vaults/references.json`, passes `local_references` to `ResearchToolInput`, renders SVG telemetry |

---

## 7. `qa-auditor` Acceptance Checklist for Downstream Implementation

Before any implementation of `SPEC-001` in `/03-agent-foundry/` or `/04-yggdrasil-app/` is marked complete, `qa-auditor` MUST verify `PASS` across all 4 gates:

1. **Gate 1 — Spec Alignment:** Exact symbol names (`TagType`, `DataSlice`, `PreGroupedBundle`, `ThousandParamMicroModel`, `NestedCallableLightAgent`, `NestedModelOrchestrator`, and all 8 exact `*_function` + Input/Output models) match `SPEC-001`.
2. **Gate 2 — Pydantic `BaseModel` & Type Safety:** Every public function and agent uses Python `>= 3.11` type hints and strict `pydantic.BaseModel` schemas (`mypy --strict` / `ruff` clean).
3. **Gate 3 — Async Safety & Single-VRAM Discipline:** `ThousandParamMicroModel` and deterministic tools consume `0` VRAM; `NestedCallableLightAgent` obtains its agent strictly from `LocalEngine.get_shared()`; no blocking HTTP/file calls inside `async def` (`httpx.AsyncClient` and `asyncio.to_thread` used properly).
4. **Gate 4 — Air-Gap Privacy Gate:** `contains_personal_vault_data=True` or `privacy_tier="air_gapped"` hard-blocks both `LeavesCloudAgent` and external queries in `research_tool_function` with `PermissionError` before any network call.
