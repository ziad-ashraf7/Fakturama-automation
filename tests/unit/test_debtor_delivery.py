from fakturama_automation.automation.masters import debtor_addresses_complete
from fakturama_automation.domain.models import Address, Debtor


def test_debtor_with_delivery_source_is_incomplete_without_delivery_role() -> None:
    debtor = Debtor(
        company="Northstar Office GmbH",
        first_name="Marta",
        last_name="Klein",
        alias="NORTHSTAR-BERLIN",
        billing_address=Address(
            street="Friedrichstrasse 88",
            zip_code="10117",
            city="Berlin",
            country="Germany",
        ),
        delivery_address=Address(
            street="Beusselstrasse 44",
            zip_code="10553",
            city="Berlin",
            country="Germany",
            additional_name="Northstar Office Warehouse",
        ),
    )

    billing_only = """Northstar Office GmbH Marta Klein Friedrichstrasse 88 10117 Berlin Germany"""

    assert debtor_addresses_complete(billing_only, debtor) is False


def test_debtor_with_delivery_source_is_complete_with_delivery_role() -> None:
    debtor = Debtor(
        company="Northstar Office GmbH",
        alias="NORTHSTAR-BERLIN",
        billing_address=Address(
            street="Friedrichstrasse 88",
            zip_code="10117",
            city="Berlin",
            country="Germany",
        ),
        delivery_address=Address(
            street="Beusselstrasse 44",
            zip_code="10553",
            city="Berlin",
            country="Germany",
            additional_name="Northstar Office Warehouse",
        ),
    )

    both_roles = """Northstar Office GmbH Friedrichstrasse 88 10117 Berlin Germany
    Northstar Office Warehouse Beusselstrasse 44 10553 Berlin Germany Delivery address"""

    assert debtor_addresses_complete(both_roles, debtor) is True
