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
    normalize_filename_invoice_date,
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


def test_eingangsrechnung_multiline_o2_invoice_fields() -> None:
    text = """O2
Ihre Rechnung
Telefónica Germany GmbH & Co. OHG RE 90345 Nürnberg
Rechnungsnummer
1318249263/08
Ihre Kundennummer
6078977192
Rechnungsdatum
28.07.2025
Leistungszeitraum
23.06.2025 - 22.07.2025
Igor Serbul
Fällig am
04.08.2025
Grundgebühren
42,99 €
Vergünstigungen / Guthaben
-16,50 €
Rechnungsbetrag
26,49 €
(davon enthaltene MwSt. 4,23 €)
Zu zahlender Betrag
26,49 €
Telefónica Deutschland Holding AG, Sitz in München, Amtsgericht München HRB 201055.
"""
    result = extract_eingangsrechnung_title(ExtractionInput("Eingangsrechnung", text, original_filename="2025-7-28-RG-1.pdf"))
    recovered = extract_eingangsrechnung_title(
        ExtractionInput(
            "Eingangsrechnung",
            text,
            original_filename="2025-7-28-RG-1.pdf",
            existing_title="TelefnicaGermany_NA_17/06/2026_201055,00",
        )
    )

    assert result.invoice_number == "1318249263/08"
    assert result.date == "28/07/2025"
    assert result.amount == "26,49"
    assert result.title == "TelefonicaGermany_1318249263/08_28/07/2025_26,49"
    assert recovered.title == result.title


def test_eingangsrechnung_o2_invoice_ignores_stale_title_and_year_amounts() -> None:
    text = """Ihre Rechnung
O₂
Telefonica Germany GmbH & Co. OHG RF 90345 Nurnberg
Rechnungsnummer
1318249263/08
Ihre Kundennummer
6078977192
Rechnungsdatum
28.07.2025
Leistungszeitraum
23.06.2025 - 22.07.2025
Igor Serbul
Fällig am
04.08.2025
10365 Berlin
Grundgebühren
42,99 €
Vergünstigungen / Guthaben
-16,50 €
Rechnungsbetrag
26,49 €
(davon enthaltene MwSt. 4,23 €)
Ihre Rechnungsdetails
Mobilfunknummer 017630322126/Festnetznummer 03040558824
Vertragslaufzeit: 27.12.2023 - 26.12.2025
Netto in €
MwSt.-Satz
Brutto in €
(Zahlungseingänge bis zum 23.07.2025 sind berücksichtigt)
Gesamtbetrag aus vorheriger Rechnung
26,49
Zahlung Lastschrift - 03.07.2025
-26,49
Gesamt
0,00
"""
    result = extract_eingangsrechnung_title(
        ExtractionInput(
            "Eingangsrechnung",
            text,
            original_filename="2025-7-28-RG-1.pdf",
            existing_title="Leistungszeitraum_1318249263/08_28/07/2025_2025,00",
        )
    )

    assert result.sender == "TelefonicaGermany"
    assert result.amount == "26,49"
    assert result.title == "TelefonicaGermany_1318249263/08_28/07/2025_26,49"



def test_eingangsrechnung_o2_noisy_ocr_uses_filename_date_and_total_not_vat() -> None:
    text = """Tetefonica Germany GmbH & Co. OHG RE 90345 Nürnberg
Guten Tag Igor Serbul,
Rechnungsnummer
Ihre Kundennummer
Rechnungsdatum
Leistungszeitraum
Fällig am
Mobilfunknummer 017630322126 Grundgebühren
Vergünstigungen / Guthaben
Rechnungsbetrag (davon enthaltene MwSt. 4,23 €)
Zulählender Betrag
26,49 €
Ihre Rechnungsdetails
Zusammenstellung nach MwSt.-Sätzen
MwSt.-Satz
Nettorechnungsbetrag in €
MwSt.-Betrag in € Bruttorechnungsbetrag in €
19%
22,26
4,23
26,49
Gesamt
22,26
4,23
26,49
"""
    result = extract_eingangsrechnung_title(
        ExtractionInput(
            "Eingangsrechnung",
            text,
            original_filename="2025-9-26-RG.pdf",
            created_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        )
    )

    assert normalize_filename_invoice_date("2025-9-26-RG.pdf") == "26/09/2025"
    assert result.sender == "TelefonicaGermany"
    assert result.invoice_number == "NA"
    assert result.date == "26/09/2025"
    assert result.amount == "26,49"
    assert result.title == "TelefonicaGermany_NA_26/09/2025_26,49"

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


def test_neutral_file_in_invoice_collection_gets_plain_title() -> None:
    result = extract_eingangsrechnung_title(
        ExtractionInput(
            "Eingangsrechnung",
            "Natürliche Aktivierung\nAktiviert körpereigene Prozesse\nohne Fremdstoffe.",
            original_filename="ChatGPT Image 2 апр. 2026 г., 22_36_32.png",
            created_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
    )
    assert result.title == "NaturlicheAktivierung"
    assert result.sender is None
    assert result.invoice_number is None
    assert result.amount is None
    assert result.date is None
    assert result.metadata["neutral_file"] is True
    assert result.metadata["document_kind"] == "neutral"


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
