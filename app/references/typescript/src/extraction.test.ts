import { describe, expect, it } from 'vitest'
import {
  extractAusgangsrechnungTitle,
  extractBelegeTitle,
  extractEingangsrechnungTitle,
  normalizeAmount
} from './extraction'

const d2026 = new Date('2026-04-12T00:00:00Z')
const d2022 = new Date('2022-10-01T00:00:00Z')
const d2025 = new Date('2025-04-01T00:00:00Z')

describe('golden extraction', () => {
  it('extracts Belege titles', () => {
    expect(extractBelegeTitle({ text: 'ACME\nDISTRIBUTORS\nInvoice draft', createdAt: d2026 })).toBe('ACME_B_04/26_NA_NA')
    expect(extractBelegeTitle({ text: 'CommerceBank\nCard statement', createdAt: d2026 })).toBe('CommerceBank_B_04/26_NA_NA')
    expect(extractBelegeTitle({ text: 'WORLD HEALTH ORGANIZATION\nMasern Sauglinge und Kinder', createdAt: d2022 })).toBe('Dok_B_10/22_NA_NA')
    expect(extractBelegeTitle({ text: 'FANGO\nTherapie Zuzahlung Preisliste', createdAt: d2025 })).toBe('Dok_B_04/25_NA_NA')
  })

  it('extracts invoice titles', () => {
    expect(extractEingangsrechnungTitle({ text: 'Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25' })).toBe('Demo_PR400000005_12/10/2020_205,25')
    expect(extractEingangsrechnungTitle({ text: 'Fenster Beruhmt KG\nRechnungsnr. 7453\nRechnungsdatum 08.11.2015\nGesamtbetrag 2.975,00' })).toBe('FensterBeruhmt_7453_08/11/2015_2975,00')
    expect(extractEingangsrechnungTitle({ text: 'Muster GmbH\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nGrand Total 222,51' })).toBe('Muster_M1675_29/10/2020_222,51')
  })

  it('extracts outgoing invoice recipients', () => {
    const habermann = 'Muster GmbH\nHauptstrasse 1\n10000 Berlin\nHabermann Sohne KG\nNebenweg 2\n20000 Hamburg\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nEndsumme 222,51'
    const muster = 'Demo AG\nIndustriestrasse 1\n10000 Berlin\nMusterkunde & Co. KG\nKundenweg 4\n30000 Bonn\nRechnung-Nr. 2400\nRechnungsdatum 15.07.2019\nInvoice Total 2,539,46'
    expect(extractAusgangsrechnungTitle({ text: habermann })).toBe('HabermannSohne_M1675_29/10/2020_222,51')
    expect(normalizeAmount('2,539,46')).toBe('2539,46')
    expect(extractAusgangsrechnungTitle({ text: muster })).toBe('MusterkundeCo_2400_15/07/2019_2539,46')
  })
})

