# Written answers

## Approach

The implementation uses one deterministic Python workflow. Mistral produces
structured extraction data, but never controls Fakturama. The workflow validates the
data with Pydantic, reconciles financial values with Decimal, and then uses semantic
pywinauto UIA controls. Exact master-data matching and persisted Documents
verification are preferred over guessing.

## If I had 3 more hours

I would spend the time on the remaining, evidenced risks:

1. Finish and re-verify automatic secondary Delivery Address creation/update for the
   exact Fakturama installation, including role assignment and post-save persistence.
2. Harden opaque Product/Items/Documents table verification with installation-specific
   row parsing, dynamic scrolling coverage, and more controlled screenshots.
3. Add recovery for stale/interrupted Fakturama tabs and modal state, plus bounded
   retry/backoff for transient Mistral/API disconnects.
4. Add clean-slate fixtures covering missing VAT, missing Products, and duplicate or
   ambiguous master data without relying on a warm workspace.
5. Expand failure-path tests and capture a short recorded demonstration covering both
   SUCCESS and safe MANUAL_REVIEW/FAILED outcomes.

I would not add another OCR provider, a database, a web service, computer-vision
framework, checkpoint store, or generic workflow layer; those would expand the
solution beyond the assignment and timebox.
