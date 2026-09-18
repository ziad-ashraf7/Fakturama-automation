from fakturama_automation.automation.app import normalize_grid_readback


def test_normalize_grid_readback_reduces_fakturama_vat_label_to_source_value() -> None:
    assert normalize_grid_readback("VAT", "VAT 19% (19.0%)") == "VAT 19%"
