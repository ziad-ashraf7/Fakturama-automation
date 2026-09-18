# Fakturama Image-to-Cash Automation

## Design overview

The MVP is one deterministic Order-first workflow for Windows and Fakturama 2.2.0:

```text
order image -> Mistral structured extraction -> validated OrderInput
             -> New Order -> resolve/create master data
             -> save and verify Order -> linked follow-up Invoice
             -> apply payment state -> save and verify Invoice
```

The implementation is intentionally small: one Mistral extractor, pure financial rules, a reusable semantic UIA control layer, and one explicit workflow orchestrator. It does not use a database, web application, coordinate scripts, local OCR engines, or a provider/plugin framework.

## Extraction and validation

`MistralOrderExtractor` implements the small boundary:

```python
OrderExtractor.extract(image_path) -> OrderInput
```

It uses Mistral Document AI OCR annotations with a JSON schema for the required fields: order date, external reference, debtor and addresses, payment data, every SKU/description/quantity/net price/VAT/discount/source total, and order totals. `MISTRAL_API_KEY` and the selected OCR model are loaded from `.env`; no secret is stored in the repository.

Mistral output is untrusted. Pydantic validates the structure and Decimal-based domain rules validate financial values before Fakturama is touched. Missing or uncertain financial data, ambiguous identities, and source-total mismatches become `MANUAL_REVIEW`; missing configuration or technical failures become `FAILED`.

## Fakturama UI grounding

pywinauto with `backend="uia"` locates exactly one top-level window whose title starts with `Fakturama` and whose class is `SWT_Window0`. Controls are found by accessible name and control type, then by semantic parent/child relationships. The workflow uses named controls such as `Create: New Order`, `Save the current contents`, named fields, Data menu entries, and the linked follow-up Invoice action.

No absolute screen coordinates, fixed window layout, global descendant indexes, or direct database manipulation are used.

The unnamed SWT selectors are discovered dynamically from their semantic sections:

```text
Addresses/Items label -> parent Pane -> local Image controls
                     -> vertical ordering -> upper selector
```

The upper Address Image opens the existing-Debtor selector and the upper Items Image opens the existing-Product selector. A dynamically discovered target may use `click_input()` when no better UIA pattern exists.

The Items grid may be an opaque SWT area. The MVP first focuses it through UIA, edits with keyboard navigation, and reads values back. Computer vision is deliberately excluded unless this targeted approach fails in the actual supplied flow.

## End-to-end workflow

The New Order opens before missing master data is created and remains open while dependencies are resolved.

- Debtor matching requires exactly one visible row matching Company, First Name, Name, ZIP, and City. No match creates a Debtor; conflicting matches stop for manual review. A created Debtor is saved once, searched again from the same Order, selected, and address-population is verified.
- Payment Methods are matched exactly or created with the assignment’s required fields and mapping: Bank Transfer → Credit transfer, Credit Card → Credit card, and SEPA Direct Debit → SEPA direct debit.
- VAT is matched by exact name, percentage, and E-Invoice code `S`; missing VAT is created and verified before Product creation.
- Products are matched by exact SKU. Missing Products are created with the extracted SKU/description, calculated gross master price, VAT, zero cost price, and zero stock, then searched again and selected from the same Order.
- Every line verifies quantity, unit net price, VAT, discount, and calculated line total.

The Order keeps 0% overall discount and free shipping unless the image supplies order-level values. It is saved once, then verified in Documents by generated number, date, Cust.Ref., open state, and total.

The Invoice is created only through the saved Order’s `Create a follow-up document` → `Invoice` action. The global New Invoice action is not used. Copied fields, lines, totals, and the Order relationship are verified. Paid input sets paid state, extracted payment date, and full Invoice Total; unpaid input does not invent date or value. Documents verification confirms the Invoice and that the source Order remains open.

## Financial verification

Financial logic is pure and uses Decimal:

```text
Product gross = unit net × (1 + VAT / 100)
Line total    = quantity × unit net × (1 - discount / 100)
```

Product gross prices use documented two-decimal `ROUND_HALF_UP` rounding. Transaction discounts never modify Product master prices. Source totals and Fakturama totals must reconcile; mismatches are not silently corrected.

## Tradeoffs and verification

The design favors a reliable vertical happy path over broad coverage. Mistral is the only implemented extraction provider. Configuration, logging, artifacts, retries, and outcome serialization remain minimal. Unit tests cover Decimal calculations, validation, exact matching, payment mapping, VAT/Product rules, and ambiguity decisions. A focused UIA smoke test plus manual end-to-end verification is sufficient for the timebox.

Transient evidence is stored under ignored `artifacts/runs/<run-id>/`; curated screenshots go under `docs/screenshots/`. The input path is `samples/input/`. The assignment PDF remains a local source-of-truth file and is not required in the submitted repository.
