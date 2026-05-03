package extraction

import (
	"testing"
	"time"
)

func TestGoldenExtraction(t *testing.T) {
	d2026 := time.Date(2026, 4, 12, 0, 0, 0, 0, time.UTC)
	d2022 := time.Date(2022, 10, 1, 0, 0, 0, 0, time.UTC)
	d2025 := time.Date(2025, 4, 1, 0, 0, 0, 0, time.UTC)
	tests := []struct {
		name string
		got  string
		want string
	}{
		{"acme", ExtractBelegeTitle(Input{Text: "ACME\nDISTRIBUTORS\nInvoice draft", CreatedAt: &d2026}), "ACME_B_04/26_NA_NA"},
		{"bank", ExtractBelegeTitle(Input{Text: "CommerceBank\nCard statement", CreatedAt: &d2026}), "CommerceBank_B_04/26_NA_NA"},
		{"leaflet", ExtractBelegeTitle(Input{Text: "WORLD HEALTH ORGANIZATION\nMasern Sauglinge und Kinder", CreatedAt: &d2022}), "Dok_B_10/22_NA_NA"},
		{"therapy", ExtractBelegeTitle(Input{Text: "FANGO\nTherapie Zuzahlung Preisliste", CreatedAt: &d2025}), "Dok_B_04/25_NA_NA"},
		{"demo", ExtractEingangsrechnungTitle(Input{Text: "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25"}), "Demo_PR400000005_12/10/2020_205,25"},
		{"fenster", ExtractEingangsrechnungTitle(Input{Text: "Fenster Beruhmt KG\nRechnungsnr. 7453\nRechnungsdatum 08.11.2015\nGesamtbetrag 2.975,00"}), "FensterBeruhmt_7453_08/11/2015_2975,00"},
		{"muster", ExtractEingangsrechnungTitle(Input{Text: "Muster GmbH\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nGrand Total 222,51"}), "Muster_M1675_29/10/2020_222,51"},
		{"habermann", ExtractAusgangsrechnungTitle(Input{Text: "Muster GmbH\nHauptstrasse 1\n10000 Berlin\nHabermann Sohne KG\nNebenweg 2\n20000 Hamburg\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nEndsumme 222,51"}), "HabermannSohne_M1675_29/10/2020_222,51"},
		{"musterkunde", ExtractAusgangsrechnungTitle(Input{Text: "Demo AG\nIndustriestrasse 1\n10000 Berlin\nMusterkunde & Co. KG\nKundenweg 4\n30000 Bonn\nRechnung-Nr. 2400\nRechnungsdatum 15.07.2019\nInvoice Total 2,539,46"}), "MusterkundeCo_2400_15/07/2019_2539,46"},
	}
	for _, tt := range tests {
		if tt.got != tt.want {
			t.Fatalf("%s: got %q want %q", tt.name, tt.got, tt.want)
		}
	}
	if got := NormalizeAmount("2,539,46"); got != "2539,46" {
		t.Fatalf("malformed amount got %q", got)
	}
}

