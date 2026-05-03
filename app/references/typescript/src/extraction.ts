export type DocumentState =
  | 'uploaded'
  | 'queued_for_ocr'
  | 'ocr_processing'
  | 'ocr_done'
  | 'metadata_processing'
  | 'complete'
  | 'failed'

export interface ExtractionInput {
  text: string
  originalFilename?: string
  createdAt?: Date
  existingTitle?: string
}

const badBelege = [
  'worldhealthorganization', 'sauglinge', 'impf', 'masern', 'rki', 'who',
  'therapie', 'zuzahlung', 'behandl', 'fango', 'microsoft', 'bgm'
]

function stripAccents(value: string): string {
  return value.normalize('NFD').replace(/\p{Diacritic}/gu, '').replaceAll('ß', 'ss')
}

function compactParty(value: string): string {
  const cleaned = stripAccents(value)
    .replace(/\b(ges\.?\s*mbh|gesmbh|gmbh|mbh|ag|kg|ug|inc|ltd|llc|sarl|e\.?k\.?)\b/gi, ' ')
    .replace(/[^A-Za-z0-9 ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned.split(/\s+/).filter(Boolean).slice(0, 3).join('').slice(0, 40) || 'Dok'
}

function compactSender(value: string): string {
  const words = stripAccents(value)
    .replace(/&/g, ' And ')
    .replace(/[_/\\|]+/g, ' ')
    .replace(/[^A-Za-z0-9 .,-]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
  const token = words.slice(0, 3).map((word) => word.toUpperCase() === word && word.length <= 8 ? word : word[0].toUpperCase() + word.slice(1)).join('')
  return token.replace(/[^A-Za-z0-9]+/g, '').slice(0, 32)
}

export function normalizeDate(raw: string): string {
  const match = raw.match(/(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})/)
  if (!match) return ''
  let year = Number(match[3])
  if (year < 100) year = year < 70 ? 2000 + year : 1900 + year
  return `${Number(match[1]).toString().padStart(2, '0')}/${Number(match[2]).toString().padStart(2, '0')}/${year.toString().padStart(4, '0')}`
}

export function normalizeAmount(raw: string): string {
  const value = raw.trim().replace(/[^0-9,.-]/g, '')
  if (!value) return 'NA'
  const candidates: string[] = []
  if (value.includes(',') && value.includes('.')) {
    candidates.push(value.lastIndexOf(',') > value.lastIndexOf('.') ? value.replace(/\./g, '').replace(',', '.') : value.replace(/,/g, ''))
  } else if (value.includes(',')) {
    const parts = value.split(',')
    if (parts.at(-1)?.length === 2) candidates.push(value.replace(/\./g, '').replace(',', '.'))
    else if (parts.length === 2 && parts.at(-1)?.length === 3) candidates.push(value.replace(/,/g, ''))
  } else if (value.includes('.')) {
    const parts = value.split('.')
    candidates.push(parts.length === 2 && parts.at(-1)?.length === 3 ? value.replace(/\./g, '') : value)
  } else {
    candidates.push(value)
  }
  const last = value.match(/([.,])(\d{2})$/)
  if (last?.index !== undefined) {
    const intPart = value.slice(0, last.index).replace(/[^0-9]/g, '')
    if (intPart) candidates.push(`${intPart}.${last[2]}`)
  }
  for (const candidate of candidates) {
    const parsed = Number(candidate)
    if (!Number.isNaN(parsed)) return parsed.toFixed(2).replace('.', ',')
  }
  return 'NA'
}

export function extractInvoiceNumber(text: string): string {
  const patterns = [
    /\bEingangsrechnung\s+([A-Z0-9][A-Z0-9./-]{2,})\b/i,
    /\bRechnungs\s*nummer\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bRechnungs\s*nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bRechnungs\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bRechnung\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bRechnung\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bInvoice\s*No\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bInvoice\s*Number\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i,
    /\bBeleg(?:nr|nummer)\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b/i
  ]
  for (const line of text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)) {
    if (/kundennummer|customer|auftrags|bestell/i.test(line)) continue
    for (const pattern of patterns) {
      const match = line.match(pattern)
      if (match) return match[1].replace(/[^A-Za-z0-9./-]+/g, '').slice(0, 40)
    }
  }
  return 'NA'
}

function invoiceDate(text: string, createdAt?: Date): string {
  const lines = text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean)
  for (const line of lines) if (/rechnungsdatum|invoice date/i.test(line)) return normalizeDate(line) || '00/00/0000'
  for (const line of lines) {
    if (/lieferdatum|leistungsdatum|valutadatum/i.test(line)) continue
    if (/\bdatum\b|\bdate\b/i.test(line)) return normalizeDate(line) || '00/00/0000'
  }
  return createdAt ? `${createdAt.getDate().toString().padStart(2, '0')}/${(createdAt.getMonth() + 1).toString().padStart(2, '0')}/${createdAt.getFullYear()}` : '00/00/0000'
}

function invoiceAmount(text: string): string {
  const nums = /(?<!\d)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2}|\d+)(?!\d)/g
  const strong = /endsumme|gesamtsumme|gesamtbetrag|zu zahlen|balance due|invoice total|grand total|brutto/i
  const medium = /summe|gesamt|total|rechnungsbetrag/i
  const bad = /netto|mwst|ust|steuer|skonto|rabatt/i
  const rows: Array<[number, number, string]> = []
  for (const line of text.split(/\r?\n/)) {
    const found = [...line.matchAll(nums)].map((x) => x[1])
    if (!found.length) continue
    let score = strong.test(line) ? 4 : medium.test(line) ? 2 : 0
    if (bad.test(line) && !strong.test(line)) score -= 3
    const amount = normalizeAmount(found.at(-1) ?? '')
    if (amount !== 'NA') rows.push([score, Number(amount.replace(',', '.')), amount])
  }
  rows.sort((a, b) => b[0] - a[0] || b[1] - a[1])
  return rows[0]?.[2] ?? 'NA'
}

export function extractBelegeSender(text: string, originalFilename = ''): string {
  const lines = text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean).slice(0, 20)
  if (/^[A-Z]{3,8}$/.test(lines[0] ?? '') && /^[A-Z][A-Z ]{3,24}$/.test(lines[1] ?? '')) return compactSender(lines[0])
  for (const line of lines.slice(0, 12)) {
    const token = compactSender(line)
    const low = token.toLowerCase()
    if (!token || badBelege.some((x) => low.includes(x)) || /^(\d+|rechnung|invoice|betrag|datum|summe)$/i.test(token)) continue
    if (line.includes(':') || /\d{2,}/.test(line)) continue
    if (/(bank|gmbh|ag|market|shop|store|distributors)/i.test(line) || /^[A-Z][A-Za-z0-9]{2,20}$/.test(token)) return token
  }
  const stem = originalFilename.replace(/\.[A-Za-z0-9]{1,5}$/, '')
  if (stem && !/(scan|img|image|document|invoice|rechnung|impf|therapie)/i.test(stem)) return compactSender(stem)
  return 'Dok'
}

function belegeMonthYear(text: string, createdAt?: Date): string {
  const date = normalizeDate(text)
  if (date) return `${date.slice(3, 5)}/${date.slice(-2)}`
  return createdAt ? `${(createdAt.getMonth() + 1).toString().padStart(2, '0')}/${(createdAt.getFullYear() % 100).toString().padStart(2, '0')}` : '00/00'
}

function belegeAmount(text: string): string {
  const rows: Array<[number, string]> = []
  const nums = /(?<!\d)(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2}|\d+)(?!\d)/g
  for (const line of text.split(/\r?\n/)) {
    let score = /(summe|gesamt|total|betrag|balance due|zu zahlen|endbetrag|invoice total|rechnungsbetrag)/i.test(line) ? 2 : 0
    if (/eur|€|\$/i.test(line)) score += 1
    for (const match of line.matchAll(nums)) rows.push([score, match[1]])
  }
  rows.sort((a, b) => b[0] - a[0] || b[1].length - a[1].length)
  return rows[0]?.[0] >= 2 ? normalizeAmount(rows[0][1]) : 'NA'
}

function payment(text: string): string {
  if (/\b(bar|cash|barzahlung)\b/i.test(text)) return 'Bar'
  if (/\b(karte|ec|girocard|visa|mastercard|amex|electronic cash|debit)\b/i.test(text)) return 'Karte'
  return 'NA'
}

export function extractEingangsrechnungSender(text: string, originalFilename = ''): string {
  for (const line of text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean).slice(0, 18)) {
    if (/(firma|kunde|rechnung|invoice|datum|summe|telefon|mail|www|lieferdatum)/i.test(line)) continue
    const candidate = line.split(/\b(phone|telefon|fax|mail|www)\b/i)[0].split(/\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b/i)[0].split(/\b\d{4,5}\b/)[0]
    const sender = compactParty(candidate)
    if (sender !== 'Dok' && sender.length >= 3) return sender
  }
  return originalFilename ? compactParty(originalFilename.replace(/\.[A-Za-z0-9]{1,5}$/, '')) : 'Dok'
}

export function extractAusgangsrechnungRecipient(text: string): string {
  const meta = /\b(rechnung|rechnungs|invoice|datum|date|kunden-?nr|kundennummer|bestell-?nr|auftrags-?nr|telefon|phone|fax|mail|www|summe|ust|mwst|endsumme|iban|bic|konto|pos\.)/i
  const top: string[] = []
  for (const line of text.split(/\r?\n/).map((x) => x.trim()).filter(Boolean).slice(0, 25)) {
    if (meta.test(line)) break
    top.push(line)
  }
  const clean = top
    .filter((line) => !meta.test(line) && !/@|www\.|\+\d/.test(line) && !/^\d{4,5}\s/.test(line) && !/\d/.test(line) && !/\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b/i.test(line))
    .map(compactParty)
    .filter((x, i, rows) => x !== 'Dok' && x.length >= 3 && rows.indexOf(x) === i)
  return clean[1] ?? 'Dok'
}

export function extractBelegeTitle(input: ExtractionInput): string {
  return `${extractBelegeSender(input.text, input.originalFilename)}_B_${belegeMonthYear(input.text, input.createdAt)}_${belegeAmount(input.text)}_${payment(input.text)}`
}

export function extractEingangsrechnungTitle(input: ExtractionInput): string {
  return `${extractEingangsrechnungSender(input.text, input.originalFilename)}_${extractInvoiceNumber(input.text)}_${invoiceDate(input.text, input.createdAt)}_${invoiceAmount(input.text)}`
}

export function extractAusgangsrechnungTitle(input: ExtractionInput): string {
  return `${extractAusgangsrechnungRecipient(input.text)}_${extractInvoiceNumber(input.text)}_${invoiceDate(input.text, input.createdAt)}_${invoiceAmount(input.text)}`
}
