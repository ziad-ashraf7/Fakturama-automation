# Fakturama Image-to-Cash Automation

This take-home solution extracts one order image with Mistral Document AI, validates the structured result with Pydantic and Decimal rules, and drives Fakturama 2.2.0 through Microsoft UI Automation.

## Scope

The implemented path is a focused Windows CLI workflow:

`image -> OrderInput -> New Order -> exact master-data resolution -> verified Order -> follow-up Invoice -> payment state -> persisted verification`

The target platform is Windows x64 with Python 3.12 and Fakturama 2.2.0. The local `docs/assignment.pdf` is the source of truth for development and is intentionally not committed.

See [docs/design.md](docs/design.md) for the concise take-home design and [docs/written-answers.md](docs/written-answers.md) for the written response.

## Setup

Prerequisites:

- Windows x64
- Python 3.12
- Fakturama 2.2.0 installed and configured
- A Mistral API key for extraction
- Git

Create the environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Set `MISTRAL_API_KEY` in the local `.env`. The placeholder file contains no secret. `MISTRAL_MODEL` defaults to `mistral-ocr-latest`; `FAKTURAMA_EXE`, `UIA_TIMEOUT_SECONDS`, and `ARTIFACT_ROOT` may be adjusted for the machine.

Put the supplied image under `samples/input/`, for example:

```
samples/input/order.png
```

Run:

```powershell
fakturama-automation run samples/input/order.png
# equivalent:
python -m fakturama_automation.cli run samples/input/order.png
```

The CLI prints `SUCCESS`, `MANUAL_REVIEW`, or `FAILED` and writes per-run evidence under `artifacts/runs/<run-id>/`.

## Architecture

- `domain/`: Pydantic models, Decimal calculations, reconciliation, exact-match decisions, and typed outcomes.
- `extraction/mistral.py`: the only implemented extraction provider. Mistral structured output first enters a permissive draft DTO, then becomes strict `OrderInput` only after validation and reconciliation.
- `automation/app.py`: semantic pywinauto UIA discovery, bounded waits, Order lifecycle, the verified unique-SKU Product insertion path, and the opaque Items-grid keyboard path.
- `automation/masters.py`: exact Debtor, payment-code, VAT, and Product resolution while keeping the same Order open.
- `automation/documents.py`: Order header/line population, explicit Save, Documents verification, follow-up Invoice activation, and payment state.
- `workflow.py` / `cli.py`: one direct orchestration path and terminal outcomes.

UIA selectors use accessible names, control types, semantic parent/child relationships, and dynamically discovered section-local Images. No screen coordinates, fixed window sizes, global descendant indexes, direct database access, or computer vision are used. The opaque Items grid uses only the controlled keyboard path and observable read-back established during the feasibility probe.

## Verification and outcomes

A Save click is not treated as persistence. The workflow requires a matching persisted Documents observation before proceeding to the linked Invoice. The Invoice is created only from the saved Order's `Create a follow-up document -> Invoice` action; the global `Create: New Invoice` action is not used.

- `SUCCESS`: Order and linked Invoice were saved and verified.
- `MANUAL_REVIEW`: required source data is missing/uncertain, or business identity/master data is ambiguous or conflicting.
- `FAILED`: provider/configuration, UI, or other technical failure.

Mistral output is untrusted. Missing required source financial values raise `ManualReviewRequired`; malformed provider output raises a typed extraction failure; API/configuration failures are failed technical runs. Money uses `Decimal` and `ROUND_HALF_UP`.

## Tests and lint

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

The UIA smoke tests are opt-in and require a controlled Fakturama session:

```powershell
$env:RUN_UIA_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests/integration/test_uia_smoke.py -q
Remove-Item Env:RUN_UIA_TESTS
```

The default unit suite does not require Fakturama or network access.

## Evidence and limitations

Curated Task 4 UIA evidence is in [docs/screenshots/](docs/screenshots/). It demonstrates semantic section discovery, unique Product insertion, and Items-grid read-back. A supplied source image and a clean live Fakturama run are required to capture the final Order/Invoice screenshots; no fabricated end-to-end evidence is included.

Known limitations are intentionally narrow: broader Fakturama maintenance-dialog variants and additional opaque-grid columns need more live coverage, and the final sample-image run depends on the supplied image and a configured Mistral key. See the written answer for concrete follow-up work.
