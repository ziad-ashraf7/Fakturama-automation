# Fakturama Image-to-Cash Automation

## Overview

This take-home solution turns one order image into a validated Fakturama Order and,
when the desktop workflow succeeds, a linked Invoice:

~~~text
image -> Mistral extraction -> validated OrderInput
      -> New Order -> exact master-data resolution
      -> saved Order verification -> linked follow-up Invoice
      -> payment state -> persisted Invoice verification
~~~

The implementation is a focused Windows CLI for Fakturama 2.2.0. The local
docs/assignment.pdf is the development source of truth and is intentionally not
committed.
## Demo

The following recording demonstrates the complete image-to-cash automation workflow in Fakturama.

[▶ Watch the full automation demo](docs/recordings/Demo.mp4)

## Features

- Mistral Document AI OCR with one small extraction adapter.
- Pydantic boundary validation and Decimal-based financial calculations.
- Microsoft UI Automation through pywinauto with backend="uia".
- Exact Debtor, Payment Term, VAT, and Product matching.
- Creation of missing Payment Terms, VAT definitions, and Products.
- Order-first workflow that keeps the same Order open while resolving dependencies.
- Linked Invoice creation only through Create a follow-up document -> Invoice.
- Paid/unpaid Invoice handling with payment date and full-value verification.
- Saved-record verification through Fakturama Documents.
- Per-run extraction JSON, validation JSON, logs, and failure evidence.
- Safe MANUAL_REVIEW/FAILED outcomes instead of ambiguous UI selections.

## Architecture

~~~text
src/fakturama_automation/
  cli.py                 command-line entry point
  config.py              typed environment configuration
  domain/                Pydantic models, Decimal rules, outcomes
  extraction/            Mistral response parsing and validation boundary
  automation/app.py      UIA connection, controls, Order grid interaction
  automation/masters.py  Debtor, payment, VAT, and Product resolution
  automation/documents.py Order/Invoice population and persistence checks
  workflow.py            direct Order-to-Cash orchestration
~~~

The deterministic Python workflow controls Fakturama. Mistral never controls the
mouse or chooses UI actions.

## Requirements

- Windows x64
- Python 3.12+
- Fakturama 2.2.0
- Git
- A Mistral API key for image extraction

Runtime dependencies are mistralai, pydantic, pydantic-settings, and pywinauto.
Development dependencies add pytest and ruff.

## Setup

From PowerShell:

~~~powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
~~~

Set MISTRAL_API_KEY only in the local, ignored .env. The committed
.env.example contains placeholders only. Optional settings are
MISTRAL_MODEL (default mistral-ocr-latest), FAKTURAMA_EXE,
UIA_TIMEOUT_SECONDS, and ARTIFACT_ROOT.

Put the supplied image under samples/input/, for example
samples/input/Picture1.jpg.

## Running

Start Fakturama 2.2.0 with the intended workspace and no blocking modal dialog.
Then run:

~~~powershell
.\\.venv\\Scripts\\python.exe -m fakturama_automation.cli run samples/input/Picture1.jpg
~~~

The installed console script is equivalent:

~~~powershell
fakturama-automation run samples/input/Picture1.jpg
~~~

The CLI reports SUCCESS, MANUAL_REVIEW, or FAILED. Each run writes evidence
under artifacts/runs/<run-id>/, including the sanitized Mistral response, draft,
validation result, strict OrderInput when valid, and run.log. Runtime artifacts
are ignored by Git.

## UI Automation and verification

Selectors use accessible name, control type, and semantic parent/child relationships.
The Fakturama window is grounded by its title prefix and SWT_Window0 class. Section
local unnamed SWT Images are discovered from the semantic Addresses and Items
sections; absolute screen coordinates, fixed layouts, and global descendant indexes
are not used.

Several SWT tables are opaque. The implementation uses narrowly scoped, dynamically
captured visual/OCR fallbacks only where semantic UIA rows are unavailable, then
requires exact identity and observable read-back. Waits are bounded and based on
visible application state. A Save click alone is never treated as persistence.

## Outcomes

- SUCCESS: the Order and linked Invoice were saved and their required persisted
  state was verified.
- MANUAL_REVIEW: source data is missing/uncertain, or business identity/master
  data is ambiguous or conflicting.
- FAILED: configuration, provider, UI, or other technical failure.

Money uses Decimal and explicit ROUND_HALF_UP rules. The global
Create: New Invoice action is not used; the Invoice must come from the saved
Order's follow-up-document action.

## Tests and lint

~~~powershell
.\\.venv\\Scripts\\python.exe -m pytest
.\\.venv\\Scripts\\ruff.exe check .
.\\.venv\\Scripts\\python.exe -m compileall src tests
~~~

The optional UIA smoke test requires a controlled Fakturama session:

~~~powershell
$env:RUN_UIA_TESTS = "1"
.\\.venv\\Scripts\\python.exe -m pytest tests/integration/test_uia_smoke.py -q
Remove-Item Env:RUN_UIA_TESTS
~~~

## Demonstration evidence

Curated screenshots are in [docs/screenshots](docs/screenshots/README.md). The
successful demonstrated run includes:

- [saved Order PO000066](docs/screenshots/saved-order-PO000066.png)
- [saved linked Invoice INV000005](docs/screenshots/saved-invoice-INV000005.png)
- [Documents verification](docs/screenshots/documents-verified-PO000066-INV000005.png)
- [Items-grid Task 4 evidence](docs/screenshots/task4-grid.png)

That demonstration used pre-seeded CUST000005 and verified totals of
570.00 net, 108.30 VAT, and 678.30 gross. These are evidence from that run,
not hardcoded workflow constants. A recent standalone rerun reached an intermittent
MAT-DESK-02 visible-product-row verification failure; it was not silently claimed
as successful or fixed.

## Known limitations

1. Automated creation/update of a secondary debtor Delivery Address is not
   production-complete. The demonstrated E2E uses a pre-seeded debtor with valid
   Invoice and Delivery address roles.
2. Fakturama exposes several SWT tables as opaque controls, so OCR/local dynamic
   geometry remains a visual robustness boundary.
3. Unexpected open tabs, modal dialogs, or stale Fakturama state can prevent a run
   from starting safely; the workflow fails rather than guessing.
4. The latest standalone rerun failed while verifying the visible MAT-DESK-02
   Product row. This is documented as an unresolved UI/OCR verification limitation,
   not represented as a completed fix.

See [docs/design.md](docs/design.md) for the concise design and
[docs/written-answers.md](docs/written-answers.md) for the written response,
including the three-hour extension plan.
