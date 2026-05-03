from __future__ import annotations

from datetime import datetime, timezone

from app.services.extraction import (
    ExtractionInput,
    extract_ausgangsrechnung_title,
    extract_belege_title,
    extract_eingangsrechnung_title,
    extract_invoice_number,
    normalize_amount,
    normalize_date,
)


def test_belege_golden_titles() -> None:
    assert extract_belege_title(
        ExtractionInput("Belege", "ACME\nDISTRIBUTORS\nInvoice draft", created_at=datetime(2026, 4, 12, tzinfo=timezone.utc))
    ).title == "ACME_B_04/26_NA_NA"
    assert extract_belege_title(
        ExtractionInput("Belege", "CommerceBank\nCard statement", created_at=datetime(2026, 4, 12, tzinfo=timezone.utc))
    ).title == "CommerceBank_B_04/26_NA_NA"
    assert extract_belege_title(
        ExtractionInput("Belege", "WORLD HEALTH ORGANIZATION\nMasern Sauglinge und Kinder", created_at=datetime(2022, 10, 1, tzinfo=timezone.utc))
    ).title == "Dok_B_10/22_NA_NA"
    assert extract_belege_title(
        ExtractionInput("Belege", "FANGO\nTherapie Zuzahlung Preisliste", created_at=datetime(2025, 4, 1, tzinfo=timezone.utc))
    ).title == "Dok_B_04/25_NA_NA"


def test_eingangsrechnung_golden_titles() -> None:
    assert extract_eingangsrechnung_title(
        ExtractionInput("Eingangsrechnung", "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25")
    ).title == "Demo_PR400000005_12/10/2020_205,25"
    assert extract_eingangsrechnung_title(
        ExtractionInput("Eingangsrechnung", "Fenster Beruhmt KG\nRechnungsnr. 7453\nRechnungsdatum 08.11.2015\nGesamtbetrag 2.975,00")
    ).title == "FensterBeruhmt_7453_08/11/2015_2975,00"
    assert extract_eingangsrechnung_title(
        ExtractionInput("Eingangsrechnung", "Muster GmbH\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nGrand Total 222,51")
    ).title == "Muster_M1675_29/10/2020_222,51"


def test_ausgangsrechnung_golden_titles() -> None:
    habermann = "\n".join(
        [
            "Muster GmbH",
            "Hauptstrasse 1",
            "10000 Berlin",
            "Habermann Sohne KG",
            "Nebenweg 2",
            "20000 Hamburg",
            "Rechnung Nr. M1675",
            "Rechnungsdatum 29.10.2020",
            "Endsumme 222,51",
        ]
    )
    assert extract_ausgangsrechnung_title(ExtractionInput("Ausgangsrechnung", habermann)).title == "HabermannSohne_M1675_29/10/2020_222,51"
    assert normalize_amount("2,539,46") == "2539,46"
    muster = "\n".join(
        [
            "Demo AG",
            "Industriestrasse 1",
            "10000 Berlin",
            "Musterkunde & Co. KG",
            "Kundenweg 4",
            "30000 Bonn",
            "Rechnung-Nr. 2400",
            "Rechnungsdatum 15.07.2019",
            "Invoice Total 2,539,46",
        ]
    )
    assert extract_ausgangsrechnung_title(ExtractionInput("Ausgangsrechnung", muster)).title == "MusterkundeCo_2400_15/07/2019_2539,46"


def test_invoice_number_variants_and_date_normalization() -> None:
    assert extract_invoice_number("Invoice No. INV-22/7") == "INV-22/7"
    assert extract_invoice_number("Kundennummer 123\nRechnung-Nr. 2400") == "2400"
    assert extract_invoice_number("Rechnungsnummer: 12345") == "12345"
    assert extract_invoice_number("Rechnungsnr.: 7453") == "7453"
    assert extract_invoice_number("Rechnungs-Nr.: M1675") == "M1675"
    assert extract_invoice_number("Rechnung Nr.: 2015-1234") == "2015-1234"
    assert extract_invoice_number("Belegnummer: B-77") == "B-77"
    assert extract_invoice_number("IBAN DE12345678901234567890\nTelefon 5551234") == "NA"
    assert normalize_date("29.10.20") == "29/10/2020"
    assert normalize_date("08.11.2015") == "08/11/2015"
    assert normalize_date("2020-10-29") == "29/10/2020"
