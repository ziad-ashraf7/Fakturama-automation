# Written answers

## Approach

The implementation uses one deterministic Python workflow. Mistral produces structured extraction data, but it never controls Fakturama. The workflow validates the data with Pydantic, reconciles all source totals with Decimal calculations, and then uses semantic pywinauto UIA controls.

The most important reliability choice is postcondition verification: saving an Order or Invoice is not accepted as success until the persisted Documents state can be observed. Product selection uses Fakturama's verified unique-filter behavior because the SWT table is opaque to UIA. The Items grid uses the smallest proven keyboard path and read-back.

## If I had three more hours

I would spend the time on the risks that remained after the demonstrated run:

1. Finish and re-verify automated secondary debtor-address creation/update for the exact Fakturama installation. The native editor reuses one SWT content Pane across address tabs, and the English role value must be scoped and persisted without changing the Main address.
2. Replace the Documents screenshot/manual evidence boundary with a small, installation-specific reader for the custom SWT Documents rows, so generated number, state, reference, and total are read back programmatically.
3. Add one more clean run covering a genuinely missing VAT/Product branch and strengthen persisted Invoice payment read-back assertions, including the compact date display used by the payment control.

I would not add another OCR provider, a database, a web service, computer vision framework, or checkpoint system; those would expand the take-home beyond its demonstrated risk.
