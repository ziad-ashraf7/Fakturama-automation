# Design

## Goals and constraints

The system accepts one order image and drives Fakturama 2.2.0 on Windows through one
Order-first happy path. Correctness, inspectability, exact matching, financial
reconciliation, and persisted-state verification take priority over breadth. The
implementation deliberately excludes web services, databases, queues, coordinate
scripts, local OCR engines, and provider/plugin frameworks.

## Proposed architecture

~~~text
CLI
  -> Mistral extraction adapter
  -> permissive extraction DTO
  -> Pydantic/domain validation and Decimal reconciliation
  -> direct workflow orchestrator
  -> Fakturama UIA automation
  -> persisted Order and Invoice verification
~~~

domain/ owns typed models, calculations, exact-match decisions, and outcome
exceptions. extraction/mistral.py is the only extraction provider. automation/app.py
contains the shared UIA connection and control behavior; masters.py resolves
Debtors, Payment Terms, VATs, and Products; documents.py populates and verifies
Orders and linked Invoices. workflow.py and cli.py keep orchestration direct and
small.

## Image extraction strategy

Mistral OCR receives the image and returns structured output using the official
mistralai SDK and a constrained schema. The provider response is untrusted. It is
first parsed into a small draft DTO that can represent missing or uncertain values,
then validated into strict OrderInput only after Pydantic checks and independent
Decimal calculations.

Required source fields include the order date, external reference, debtor/address
data, payment data, item rows, source line totals, and order totals. Product gross
price and transaction line totals are calculated with Decimal and documented
ROUND_HALF_UP money rounding. Missing or uncertain business values and financial
inconsistencies become MANUAL_REVIEW; malformed provider output and technical
provider/configuration failures become typed FAILED paths.

## UI control discovery and grounding

pywinauto with backend="uia" identifies the top-level Fakturama window by title
prefix and class SWT_Window0. Controls are selected by accessible name, control
type, and semantic parent/child relationships. Examples include the New Order action,
named fields, Save action, Data menu, and the follow-up Invoice action.

The upper unnamed selectors are grounded dynamically through their semantic sections:

~~~text
section label -> parent Pane -> local Image controls -> vertical ordering
~~~

No absolute screen coordinates, fixed resolutions, stored rectangles, or global
descendant indexes are used. click_input() is used only after semantic discovery
when no stronger UIA pattern is available.

Some SWT tables expose no useful rows through UIA. For those narrow boundaries, the
workflow captures the current semantic Pane and uses OCR/local image geometry only
to identify an exact visible row. The selected row is then verified by a visible
postcondition. The Product picker keeps automatic unique-filter insertion as its
primary path and uses guarded Enter only for one exact visible fallback result.
Bounded waits observe controls, dialogs, focus, and persisted rows rather than using
long blind sleeps.

## Master-data strategy

The workflow opens a New Order first and keeps it open while resolving dependencies.
Debtors, Payment Terms, VATs, and Products are matched exactly after presentation
normalization. Zero matches permit the assignment-specific creation branch; multiple
or conflicting matches stop with MANUAL_REVIEW. Newly created data is saved once,
verified, and then searched again from the same Order when required. VAT is resolved
before Product creation, and the Product master gross price never includes a
transaction-line discount.

The demonstrated submission uses a pre-seeded Debtor with both Invoice and Delivery
address roles. Automatic creation of a secondary Delivery Address remains a known
limitation.

## Order and Invoice strategy

The workflow leaves Fakturama's generated Order number unchanged, sets the extracted
date and reference, uses Net pricing and With VAT, and completes every line with
quantity, unit net price, VAT, and discount. It verifies addresses, lines, line
totals, order-level discount/shipping defaults, and totals before invoking Save.

After persistence, the Order is verified in Documents. The Invoice is created only
from the saved Order's Create a follow-up document -> Invoice action, never from the
global New Invoice action. Payment Terms are resolved before opening the linked
Invoice. Paid input sets the mapped payment method, paid state, extracted payment
date, and full Invoice total. The Invoice number, Documents row, reference, state,
and total are required before success.

## Error handling and evidence

The outcomes are intentionally small:

- SUCCESS means required persisted state was verified.
- MANUAL_REVIEW means source/business ambiguity or uncertainty.
- FAILED means technical/provider/UI failure.

Every run receives an identifier and stores sanitized extraction/validation JSON and
a run log under ignored artifacts/runs/. Curated screenshots are kept under
docs/screenshots/. Important UI actions require an observable postcondition, so
the workflow fails safely instead of silently selecting an uncertain row.

## Trade-offs and architectural decisions

1. **UIA plus targeted visual fallback.** Semantic controls are stable and
   inspectable; opaque SWT tables require OCR/local geometry. The benefit is coverage
   without fixed coordinates, at the cost of latency and visual sensitivity.
2. **Mistral instead of local OCR.** Structured extraction is compact and handles
   varied order images well, but introduces network, quota, and API-key dependency.
3. **Exact matching.** It prevents the wrong customer/product from being selected,
   but legitimate ambiguity becomes a manual-review outcome.
4. **No fixed coordinates.** The workflow survives window movement and resizing, but
   requires more discovery and read-back logic.
5. **Strong postconditions.** Persisted verification prevents false success, but
   opaque SWT read-back is the main runtime risk.
6. **Timebox trade-off.** Production-grade recovery, automated secondary-address
   creation, exhaustive scrolling/layout coverage, and multiple extraction providers
   were deferred to keep the vertical path understandable and testable.
