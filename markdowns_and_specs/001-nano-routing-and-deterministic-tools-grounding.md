# 001 — Nano Routing & Deterministic Tools Grounding Log

- **Author:** `01-code-oracle`
- **Target Scope:** Python 3.11+ stdlib (`ast`, `math`, `statistics`), `pypdf`, `pydantic` v2, and Ollama `Modelfile` syntax for deterministic Yggdrasil micro-agents and routing tools.
- **Verification Sources:**
  - Python 3.11.14 Official Docs (`python/cpython` `v3.11.14` via Context7 & `docs.python.org/3.11/library/{ast,math,statistics}.html`)
  - `pypdf` Stable Docs & Source (`py-pdf/pypdf` & `pypdf.readthedocs.io/en/stable` via Context7)
  - Pydantic v2 Docs (`pydantic.dev/docs/validation/latest` via Context7)
  - Ollama Official Modelfile Reference (`ollama/ollama` `docs/modelfile.mdx` via Context7)
  - Local Workspace Inspection (`03-agent-foundry/pyproject.toml`, `03-agent-foundry/yggdrasil_agents/{local_engine,trunk,twigs}.py`, `04-yggdrasil-app/app.py`)

> [!IMPORTANT]
> **Observed Environment & Packaging Gaps:**
> 1. `03-agent-foundry/pyproject.toml` declares `requires-python = ">=3.11"` and `pydantic>=2.7.0`, `pydantic-ai>=1.0.0`, `openai>=1.30.0`, `google-genai>=1.0.0`, and `httpx>=0.27.0`, **but does not yet declare `pypdf`**. Add `pypdf` to package dependencies before importing it in `03` or `04`.
> 2. No runnable `python.exe` interpreter was present on `PATH` in this workspace environment (only the Windows Store stub); all SDK signatures below are verified from upstream official documentation and source repositories rather than local runtime execution.

---

## 1. Python 3.11+ `ast` — Safe Arithmetic Evaluator & Static Detectors

Verified against CPython `v3.11.14` `Doc/library/ast.rst` and Python 3.11 ASDL grammar.

### 1.1 Parsing Modes & Core Traversal
- **`ast.parse(source, filename="<unknown>", mode="exec")`**:
  - `mode="eval"` parses a single expression into `ast.Expression(body=...)`.
  - `mode="exec"` parses module statements into `ast.Module(body=[...], type_ignores=[...])`.
- **`ast.NodeVisitor`**:
  - Calling `visitor.visit(node)` dispatches to `visit_<NodeClassName>(node)`, falling back to `self.generic_visit(node)`.
  - **Mandatory Rule:** Custom `visit_*` methods **suppress child traversal** unless they explicitly call `self.generic_visit(node)` (or manually visit desired child attributes).

### 1.2 Safe Arithmetic AST Evaluator (No `eval()`)
Only evaluate `ast.Expression` trees composed strictly of whitelisted numeric literals, operators, and optional variable/function lookup dicts:

| Node Class | Fields (Python 3.11) | Safe Handling Rule |
| :--- | :--- | :--- |
| `ast.Expression` | `body` | Verify root `isinstance(tree, ast.Expression)` and evaluate `tree.body`. |
| `ast.Constant` | `value` | Allow `isinstance(node.value, (int, float))` **and** `not isinstance(node.value, bool)` (`bool` subclasses `int` in Python). Reject non-finite values with `math.isfinite`. |
| `ast.UnaryOp` | `op`, `operand` | Whitelist `ast.UAdd` (`+x`), `ast.USub` (`-x`). |
| `ast.BinOp` | `left`, `op`, `right` | Whitelist `ast.Add`, `ast.Sub`, `ast.Mult`, `ast.Div`, `ast.FloorDiv`, `ast.Mod`, `ast.Pow`. Guard `ast.Pow` exponent magnitude (prevent CPU/memory DoS) and zero denominators. |
| `ast.Name` *(optional)* | `id`, `ctx` | Allow only `isinstance(node.ctx, ast.Load)` when `node.id` exists in an explicit `variables: Mapping[str, float]`. |
| `ast.Call` *(optional)* | `func`, `args`, `keywords` | Allow only `isinstance(node.func, ast.Name)` in an explicit math allowlist, with `not node.keywords` and no `ast.Starred` arguments. |

```python
import ast
import math
import operator
from collections.abc import Callable, Mapping

_BIN_OPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

def safe_eval_arithmetic(expr: str, variables: Mapping[str, float] | None = None) -> float:
    tree = ast.parse(expr, mode="eval")
    env = variables or {}

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"Unsupported constant type: {type(node.value).__name__}")
            val = float(node.value)
            if not math.isfinite(val):
                raise ValueError("Non-finite constant rejected.")
            return val
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id not in env:
                raise KeyError(f"Unknown variable: {node.id}")
            return float(env[node.id])
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left = _eval(node.left)
            right = _eval(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000.0:
                raise ValueError("Exponent magnitude exceeds safe bound.")
            result = _BIN_OPS[type(node.op)](left, right)
            if not math.isfinite(result):
                raise ValueError("Non-finite arithmetic result.")
            return result
        raise ValueError(f"Disallowed AST node: {type(node).__name__}")

    return _eval(tree)
```

### 1.3 AST Complexity / $O(N^2)+$ Nested-Loop Detector
Track loop nesting depth per function/module scope using `ast.NodeVisitor`:
- **Loop statements:** `ast.For` (`target`, `iter`, `body`, `orelse`), `ast.AsyncFor` (`target`, `iter`, `body`, `orelse`), `ast.While` (`test`, `body`, `orelse`).
- **Comprehension expressions:** `ast.ListComp`, `ast.SetComp`, `ast.DictComp`, `ast.GeneratorExp` each store `generators: list[ast.comprehension]`. A comprehension with `k = len(node.generators)` clauses adds `k` nested loop levels (e.g., `[(i, j) for i in a for j in b]` has `k == 2`, i.e., $O(N^2)$).
- **Scope isolation:** When visiting nested `ast.FunctionDef`, `ast.AsyncFunctionDef`, or `ast.ClassDef`, push/reset `loop_depth = 0` for the inner definition body so defining a helper inside a loop is not conflated with executing a nested loop.
- Always decrement/restore `loop_depth` in `try ... finally` around `self.generic_visit(node)` so sibling loops remain independent.

### 1.4 Sync-in-Async Blocking Call Detector
Walk `ast.Module` with `ast.NodeVisitor` tracking `async_depth`:
- Enter `ast.AsyncFunctionDef`: increment `async_depth += 1`, call `self.generic_visit(node)`, decrement in `finally`.
- Enter synchronous `ast.FunctionDef`: save/set `async_depth = 0` for its inner body, restore in `finally` (intra-procedural check).
- Inside `async_depth > 0`, inspect `ast.Call(func, args, keywords)`:
  - Resolve `node.func` if `ast.Name` (e.g., `open`, `input`) or chained `ast.Attribute(value, attr, ctx)` (e.g., `time.sleep`, `requests.get`, `requests.post`, `urllib.request.urlopen`, `subprocess.run`).
  - Also inspect `ast.With` vs `ast.AsyncWith` and note `ast.Await(value)` wraps awaitable expressions.
  - Exclude calls passed as target callables to `asyncio.to_thread(...)` or `loop.run_in_executor(...)` if inspecting offloading patterns.

---

## 2. Python 3.11+ `math` & `statistics` — Deterministic Scientific & Control Math

Verified against Python 3.11 standard library documentation (`math`, `statistics`).

### 2.1 Verified Primitives & Guarantees
- `math.exp(x)` — computes $e^x$ more accurately than `math.e ** x` or `pow(math.e, x)`; raises `OverflowError` on float overflow.
- `math.log(x[, base])` — natural log by default; raises `ValueError` for $x \le 0$.
- `math.sqrt(x)` — real square root; raises `ValueError` for $x < 0$.
- `math.fabs(x)` — always returns `float` absolute value.
- `math.isfinite(x)` — returns `True` iff `x` is neither `±inf` nor `nan`.
- `math.isclose(a, b, *, rel_tol=1e-09, abs_tol=0.0)` — floating-point tolerance comparison (`NaN` is never close; `inf` only close to matching `inf`).
- `statistics.mean(data)` — exact/type-preserving arithmetic mean (`int`, `float`, `Decimal`, `Fraction`); raises `StatisticsError` on empty input.
- `statistics.fmean(data, weights=None)` — fast C-implemented floating-point mean, always returns `float`, supports optional `weights` (Python 3.11+); raises `StatisticsError` on empty input or `ValueError` on mismatched `weights` length.
- `statistics.stdev(data, xbar=None)` — sample standard deviation ($N - 1$ denominator); raises `StatisticsError` if `< 2` elements.

### 2.2 Deterministic Domain Patterns

1. **Arrhenius Rate Constant:** $k(T) = A \exp\!\left(-\frac{E_a}{R T}\right)$
   ```python
   R_GAS_CONSTANT = 8.314462618  # J / (mol * K)

   def arrhenius_rate(pre_exp: float, ea_j_mol: float, temp_k: float) -> float:
       if pre_exp < 0.0 or ea_j_mol < 0.0 or temp_k <= 0.0:
           raise ValueError("Require A >= 0, Ea >= 0, and T > 0 K.")
       rate = pre_exp * math.exp(-ea_j_mol / (R_GAS_CONSTANT * temp_k))
       if not math.isfinite(rate):
           raise OverflowError("Arrhenius evaluation overflowed float precision.")
       return rate
   ```

2. **Reynolds Number:** $Re = \frac{\rho v D}{\mu}$
   ```python
   def reynolds_number(density: float, velocity: float, diameter: float, viscosity: float) -> float:
       if density <= 0.0 or velocity < 0.0 or diameter <= 0.0 or viscosity <= 0.0:
           raise ValueError("Require density > 0, velocity >= 0, diameter > 0, viscosity > 0.")
       return (density * velocity * diameter) / viscosity
   ```

3. **Newton-Raphson Scalar Root Finding:** $x_{n+1} = x_n - \frac{f(x_n)}{f'(x_n)}$
   ```python
   def newton_raphson(
       fn: Callable[[float], float],
       dfn: Callable[[float], float],
       x0: float,
       tol: float = 1e-9,
       max_iter: int = 100,
       deriv_floor: float = 1e-14,
   ) -> float:
       x = x0
       for _ in range(max_iter):
           fx = fn(x)
           if math.fabs(fx) <= tol:
               return x
           dfx = dfn(x)
           if math.fabs(dfx) < deriv_floor:
               raise ZeroDivisionError("Derivative magnitude fell below numerical floor.")
           x_next = x - (fx / dfx)
           if not math.isfinite(x_next):
               raise ValueError("Newton-Raphson iterate became non-finite.")
           if math.isclose(x_next, x, rel_tol=tol, abs_tol=tol):
               return x_next
           x = x_next
       raise RuntimeError("Newton-Raphson did not converge within max_iter.")
   ```

4. **Discrete FOPDT + PID Step Response Simulation:**
   - Exact zero-order-hold FOPDT discretization (unconditionally stable for any $\Delta t > 0, \tau_p > 0$, dead-time steps $d = \max(0, \text{round}(\theta_p / \Delta t))$ via `collections.deque`):
     $$a = e^{-\Delta t / \tau_p}, \quad y_{k+1} = a \, y_k + K_p (1 - a) \, u_{k-d}$$
   - Positional PID update with `e_k = setpoint - y_k`, trapezoidal/Euler integral accumulation, and finite-difference derivative `(e_k - e_prev) / dt`, guarding `tau_p > 0`, `dt > 0`, and `math.isfinite`.

5. **MAE & RMSE via `statistics.fmean` + `math.sqrt`:**
   ```python
   def regression_errors(y_true: Sequence[float], y_pred: Sequence[float]) -> tuple[float, float]:
       if not y_true or len(y_true) != len(y_pred):
           raise ValueError("y_true and y_pred must be non-empty sequences of equal length.")
       mae = statistics.fmean(math.fabs(a - b) for a, b in zip(y_true, y_pred))
       rmse = math.sqrt(statistics.fmean((a - b) ** 2 for a, b in zip(y_true, y_pred)))
       return mae, rmse
   ```

---

## 3. `pypdf` — Document Parsing, Text, Metadata & Cross-Page Links

Verified against `pypdf` stable docs (`pypdf.readthedocs.io/en/stable`) and `py-pdf/pypdf` source (`_page.py`, `_writer.py`, `PdfDocCommon.rst`).

### 3.1 Verified Imports & Reader Basics
```python
from pypdf import PageObject, PdfReader
from pypdf.generic import ArrayObject, Destination, DictionaryObject
```
- `reader = PdfReader(stream, strict=True)` — accepts a path or binary stream.
- Encryption guard: inspect `reader.is_encrypted`; call `reader.decrypt(password)` before reading pages when encrypted.
- Page count: `len(reader.pages)` or `reader.get_num_pages()`.
- Page lookup: `page = reader.pages[idx]` or `reader.get_page(idx)` (0-indexed `PageObject`).

### 3.2 Text Extraction (`PageObject.extract_text`)
- Default extraction: `page.extract_text()`
- Orientation filter: `page.extract_text(0)` or `page.extract_text((0, 90))`
- Layout-preserving extraction options:
  ```python
  text = page.extract_text(
      extraction_mode="layout",
      layout_mode_space_vertically=False,
      layout_mode_scale_weight=1.0,
      layout_mode_strip_rotated=False,
  )
  ```

### 3.3 Document Metadata
`meta = reader.metadata` (`DocumentInformation | None`). **Every field may be `None`**:
- `meta.title`, `meta.author`, `meta.subject`, `meta.creator`, `meta.producer`, `meta.creation_date`, `meta.modification_date`
- Additional document-level fields: `reader.pdf_header` (e.g., `"%PDF-1.7"`), `reader.xmp_metadata`, `reader.outline` (nested list of `Destination` objects).

### 3.4 Cross-Page Link Annotations & Destination Resolution
Verified directly in `pypdf._page.PageObject.annotations` and `pypdf._writer._insert_filtered_annotations`:
- Page annotations live under `page["/Annots"]` (check `"/Annots" in page` or `page.annotations`, which returns `ArrayObject | None`).
- Each annotation item may be an `IndirectObject`; dereference via `annot = entry.get_object()`.
- Filter for links: `annot.get("/Subtype") == "/Link"`.
- **Important PDF-Spec / `pypdf` Key Distinction:**
  - **Direct destination on `/Link`:** `annot.get("/Dest")`
  - **Action dictionary (`/A`):** dereference `action = annot["/A"].get_object()`:
    - External URI: `action.get("/S") == "/URI"` -> URL string at `action.get("/URI")`.
    - Internal GoTo: `action.get("/S") == "/GoTo"` -> destination lives under **`action.get("/D")`** (not `"/Dest"`!).
- **Resolving Destination to Zero-Based Page Index:**
  - Named destination (`isinstance(dest, (str, bytes))`): look up `named = reader.named_destinations.get(str(dest))` (`Destination`) and resolve with `reader.get_destination_page_number(named) -> int | None`.
  - `Destination` object (`isinstance(dest, Destination)`): call `reader.get_destination_page_number(dest) -> int | None`.
  - Explicit PDF destination `ArrayObject` (`[page_ref, /XYZ, ...]`): dereference `target = dest[0].get_object()`; if `isinstance(target, PageObject)`, call `reader.get_page_number(target) -> int | None`.

```python
def extract_page_links(reader: PdfReader, page_index: int) -> list[dict[str, object]]:
    page = reader.pages[page_index]
    annots = page.annotations
    if not annots:
        return []
    links: list[dict[str, object]] = []
    for raw_annot in annots:
        annot = raw_annot.get_object()
        if not isinstance(annot, DictionaryObject) or annot.get("/Subtype") != "/Link":
            continue
        dest = annot.get("/Dest")
        if dest is None and "/A" in annot:
            action = annot["/A"].get_object()
            if isinstance(action, DictionaryObject):
                subtype = action.get("/S")
                if subtype == "/URI":
                    links.append({"type": "uri", "uri": str(action.get("/URI", ""))})
                    continue
                if subtype == "/GoTo":
                    dest = action.get("/D")
        if dest is not None and hasattr(dest, "get_object"):
            dest = dest.get_object()
        target_page: int | None = None
        if isinstance(dest, bytes):
            dest = dest.decode("utf-8", errors="replace")
        if isinstance(dest, str):
            named = reader.named_destinations.get(str(dest))
            if named is not None:
                target_page = reader.get_destination_page_number(named)
        elif isinstance(dest, Destination):
            target_page = reader.get_destination_page_number(dest)
        elif isinstance(dest, ArrayObject) and len(dest) > 0:
            page_obj = dest[0].get_object()
            if isinstance(page_obj, PageObject):
                target_page = reader.get_page_number(page_obj)
        links.append({"type": "internal", "target_page": target_page})
    return links
```

---

## 4. `pydantic` v2 — Verified Schema, Validation & Serialization Patterns

Verified against Pydantic v2 official docs (`pydantic.dev/docs/validation/latest/`) and `03-agent-foundry/yggdrasil_agents/`.

- **Core Imports:** `from pydantic import BaseModel, Field, ValidationError` and `from typing import Literal`.
- **`Field(...)` Constraints & Defaults:**
  - Numeric bounds: `gt`, `ge`, `lt`, `le`, `multiple_of` (e.g., `Field(default=0.8, ge=0.0, le=1.0)`).
  - Sequence/string bounds: `min_length`, `max_length`.
  - Mutable defaults: always use `Field(default_factory=list)` or `Field(default_factory=dict)`.
  - Documentation & serialization hooks: `description="..."`, `title="..."`, `examples=[...]`, `exclude=True`, `exclude_if=...`.
- **`typing.Literal`:**
  - Constrains values strictly (`Literal["ollama", "lm_studio"]`, `Literal[True]`, `Literal[1, 2]`).
  - Note: Pydantic applies strict-style matching for `Literal` (e.g., `'1'` fails against `Literal[1, 2]` with `literal_error`).
- **Validation Methods:**
  - `Model.model_validate(data, *, strict=None)` — validates Python dicts/objects.
  - `Model.model_validate_json(json_bytes_or_str, *, strict=None)` — parses and validates JSON directly in Rust core.
  - `strict=True` disables coercion (e.g., string ISO timestamps will not coerce to `datetime`).
- **Serialization Methods:**
  - `model.model_dump()` — returns Python `dict` preserving Python objects.
  - `model.model_dump(mode="json")` — returns JSON-compatible `dict`.
  - `model.model_dump_json(...)` — returns serialized JSON `str`.
  - Supported filters: `include=...`, `exclude=...`, `exclude_unset=True`, `exclude_defaults=True`, `exclude_none=True`, `polymorphic_serialization=True`.

---

## 5. Ollama `Modelfile` Syntax (`FROM`, `PARAMETER`, `SYSTEM`)

Verified against `github.com/ollama/ollama/blob/main/docs/modelfile.mdx` via Context7.

### 5.1 Instruction Reference
| Instruction | Requirement | Verified Syntax & Notes |
| :--- | :--- | :--- |
| `FROM` | **Required** | `FROM <model>:<tag>` (e.g., `FROM qwen2.5:14b`), `FROM <safetensors_dir>`, or `FROM ./model.gguf` (split shards: `FROM ./model-*.gguf`). |
| `PARAMETER num_ctx` | Optional | `PARAMETER num_ctx <int>` — context window in tokens (Ollama default: `2048`). |
| `PARAMETER temperature` | Optional | `PARAMETER temperature <float>` — sampling temperature (Ollama default: `0.8`; use `0.0`–`0.2` for deterministic JSON/tool routing). |
| `SYSTEM` | Optional | `SYSTEM """<system message>"""` — sets the system prompt baked into the model template (single-line or triple-quoted multi-line). |
| `#` comments | Optional | Lines starting with `#` are ignored as comments. |

Other verified `PARAMETER` keys in `modelfile.mdx`: `seed <int>` (default `0`), `num_predict <int>` (default `-1`), `repeat_last_n <int>` (default `64`), `repeat_penalty <float>` (default `1.0`), `stop "<pattern>"` (repeatable).

### 5.2 Reference Modelfile & CLI Usage
```dockerfile
FROM qwen2.5:14b
PARAMETER num_ctx 4096
PARAMETER temperature 0.1
SYSTEM """You are a deterministic Yggdrasil routing micro-agent. Return strictly valid JSON."""
```

Build and verify locally:
```bash
ollama create yggdrasil-nano-router -f ./Modelfile
ollama run yggdrasil-nano-router
```

> [!NOTE]
> **Single-VRAM Residency Constraint:** In Yggdrasil (`03-agent-foundry/yggdrasil_agents/local_engine.py`), `LocalEngine.get_shared()` raises `RuntimeError` if called with a conflicting `LocalEngineConfig`. Creating multiple Ollama tags with distinct `num_ctx` / `temperature` values will load separate resident models into VRAM if invoked concurrently; prefer sharing **one** `Modelfile` tag across `roots`, `trunk`, and `twigs`, passing per-request sampling overrides via the API payload where supported rather than swapping resident models.
