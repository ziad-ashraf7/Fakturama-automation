# Written answers

## Approach

The implementation uses one deterministic Python workflow. Mistral produces structured extraction data, but it never controls Fakturama. The workflow validates the data with Pydantic, reconciles all source totals with Decimal calculations, and then uses semantic pywinauto UIA controls.

The most important reliability choice is postcondition verification: saving an Order or Invoice is not accepted as success until the persisted Documents state can be observed. Product selection uses Fakturama's verified unique-filter behavior because the SWT table is opaque to UIA. The Items grid uses the smallest proven keyboard path and read-back.

## If I had three more hours

I would spend the time on the actual remaining risks observed in the implementation:

1. Run the complete supplied sample image through Mistral and Fakturama on a clean data state, then capture annotated Order, Documents, linked-Invoice, and payment-state screenshots.
2. Harden the maintenance-dialog selectors for the exact Fakturama installation by recording stable semantic names for Debtor, VAT, Product, and payment-method creation, while keeping the same semantic parent/child strategy.
3. Add a second controlled UIA run covering a non-zero VAT and a missing Product/VAT creation branch, because the initial grid fixture exposed only Tax-free VAT.
4. Improve persisted Documents-row parsing so the generated Order and Invoice number/state/total are read from explicit row fields rather than a whole-list text check.

I would not add another OCR provider, a database, a web service, computer vision, or a checkpoint framework; those would not reduce the current submission risk.
