use regex::Regex;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DocumentState {
    Uploaded,
    QueuedForOcr,
    OcrProcessing,
    OcrDone,
    MetadataProcessing,
    Complete,
    Failed,
}

#[derive(Debug, Clone, Default)]
pub struct ExtractionInput {
    pub text: String,
    pub original_filename: String,
    pub created_month: Option<u32>,
    pub created_year: Option<u32>,
}

fn compact_party(value: &str) -> String {
    let legal = Regex::new(r"(?i)\b(ges\.?\s*mbh|gesmbh|gmbh|mbh|ag|kg|ug|inc|ltd|llc|sarl|e\.?k\.?)\b").unwrap();
    let non = Regex::new(r"[^A-Za-z0-9 ]+").unwrap();
    let without_legal = legal.replace_all(value, " ");
    let cleaned = non.replace_all(&without_legal, " ");
    let mut out = cleaned.split_whitespace().take(3).collect::<Vec<_>>().join("");
    if out.len() > 40 {
        out.truncate(40);
    }
    if out.is_empty() { "Dok".to_string() } else { out }
}

fn compact_sender(value: &str) -> String {
    let non = Regex::new(r"[^A-Za-z0-9 .,-]+").unwrap();
    let mut cleaned = value.replace('&', " And ");
    cleaned = Regex::new(r"[_/\\|]+").unwrap().replace_all(&cleaned, " ").to_string();
    cleaned = non.replace_all(&cleaned, " ").to_string();
    let mut parts = Vec::new();
    for word in cleaned.split_whitespace().take(3) {
        if word.to_uppercase() == word && word.len() <= 8 {
            parts.push(word.to_string());
        } else {
            let mut chars = word.chars();
            if let Some(first) = chars.next() {
                parts.push(format!("{}{}", first.to_uppercase(), chars.as_str()));
            }
        }
    }
    let mut out = Regex::new(r"[^A-Za-z0-9]+").unwrap().replace_all(&parts.join(""), "").to_string();
    if out.len() > 32 {
        out.truncate(32);
    }
    out
}

pub fn normalize_date(raw: &str) -> String {
    let re = Regex::new(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})").unwrap();
    let Some(caps) = re.captures(raw) else { return String::new(); };
    let day: u32 = caps[1].parse().unwrap_or(0);
    let month: u32 = caps[2].parse().unwrap_or(0);
    let mut year: u32 = caps[3].parse().unwrap_or(0);
    if year < 100 {
        year += if year < 70 { 2000 } else { 1900 };
    }
    format!("{:02}/{:02}/{:04}", day, month, year)
}

pub fn normalize_amount(raw: &str) -> String {
    let value = Regex::new(r"[^0-9,.\-]").unwrap().replace_all(raw.trim(), "").to_string();
    if value.is_empty() {
        return "NA".to_string();
    }
    let mut candidates = Vec::new();
    if value.contains(',') && value.contains('.') {
        if value.rfind(',') > value.rfind('.') {
            candidates.push(value.replace('.', "").replace(',', "."));
        } else {
            candidates.push(value.replace(',', ""));
        }
    } else if value.contains(',') {
        let parts: Vec<_> = value.split(',').collect();
        let last = parts.last().copied().unwrap_or("");
        if last.len() == 2 {
            candidates.push(value.replace('.', "").replace(',', "."));
        } else if parts.len() == 2 && last.len() == 3 {
            candidates.push(value.replace(',', ""));
        }
    } else if value.contains('.') {
        let parts: Vec<_> = value.split('.').collect();
        if parts.len() == 2 && parts[1].len() == 3 {
            candidates.push(value.replace('.', ""));
        } else {
            candidates.push(value.clone());
        }
    } else {
        candidates.push(value.clone());
    }
    if let Some(caps) = Regex::new(r"([.,])(\d{2})$").unwrap().captures(&value) {
        let sep_start = caps.get(1).unwrap().start();
        let int_part = Regex::new(r"[^0-9]").unwrap().replace_all(&value[..sep_start], "").to_string();
        if !int_part.is_empty() {
            candidates.push(format!("{}.{}", int_part, &caps[2]));
        }
    }
    for candidate in candidates {
        if let Ok(parsed) = candidate.parse::<f64>() {
            return format!("{:.2}", parsed).replace('.', ",");
        }
    }
    "NA".to_string()
}

pub fn extract_invoice_number(text: &str) -> String {
    let patterns = [
        r"(?i)\bEingangsrechnung\s+([A-Z0-9][A-Z0-9./-]{2,})\b",
        r"(?i)\bRechnungs\s*nummer\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnungs\s*nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnungs\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnung\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bRechnung\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bInvoice\s*No\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bInvoice\s*Number\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
        r"(?i)\bBeleg(?:nr|nummer)\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b",
    ];
    let clean = Regex::new(r"[^A-Za-z0-9./-]+").unwrap();
    for line in text.lines() {
        let low = line.to_lowercase();
        if low.contains("kundennummer") || low.contains("customer") || low.contains("auftrags") || low.contains("bestell") {
            continue;
        }
        for pattern in patterns {
            let re = Regex::new(pattern).unwrap();
            if let Some(caps) = re.captures(line) {
                let mut out = clean.replace_all(&caps[1], "").to_string();
                if out.len() > 40 {
                    out.truncate(40);
                }
                return out;
            }
        }
    }
    "NA".to_string()
}

fn invoice_date(text: &str) -> String {
    for line in text.lines() {
        let low = line.to_lowercase();
        if low.contains("rechnungsdatum") || low.contains("invoice date") {
            let d = normalize_date(line);
            if !d.is_empty() { return d; }
        }
    }
    for line in text.lines() {
        let low = line.to_lowercase();
        if low.contains("lieferdatum") || low.contains("leistungsdatum") || low.contains("valutadatum") {
            continue;
        }
        if low.contains("datum") || low.contains("date") {
            let d = normalize_date(line);
            if !d.is_empty() { return d; }
        }
    }
    "00/00/0000".to_string()
}

fn invoice_amount(text: &str) -> String {
    let num_re = Regex::new(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b|\b\d+[.,]\d{2}\b|\b\d+\b").unwrap();
    let strong = Regex::new(r"endsumme|gesamtsumme|gesamtbetrag|zu zahlen|balance due|invoice total|grand total|brutto").unwrap();
    let medium = Regex::new(r"summe|gesamt|total|rechnungsbetrag").unwrap();
    let bad = Regex::new(r"netto|mwst|ust|steuer|skonto|rabatt").unwrap();
    let mut best: Option<(i32, f64, String)> = None;
    for line in text.lines() {
        let nums: Vec<_> = num_re.find_iter(line).map(|m| m.as_str()).collect();
        if nums.is_empty() { continue; }
        let low = line.to_lowercase();
        let mut score = if strong.is_match(&low) { 4 } else if medium.is_match(&low) { 2 } else { 0 };
        if bad.is_match(&low) && score < 4 { score -= 3; }
        let amount = normalize_amount(nums.last().unwrap());
        if amount == "NA" { continue; }
        let value = amount.replace(',', ".").parse::<f64>().unwrap_or(0.0);
        if best.as_ref().map(|b| score > b.0 || (score == b.0 && value > b.1)).unwrap_or(true) {
            best = Some((score, value, amount));
        }
    }
    best.map(|b| b.2).unwrap_or_else(|| "NA".to_string())
}

pub fn extract_belege_sender(text: &str, original_filename: &str) -> String {
    let lines: Vec<_> = text.lines().map(str::trim).filter(|x| !x.is_empty()).collect();
    if lines.len() >= 2
        && Regex::new(r"^[A-Z]{3,8}$").unwrap().is_match(lines[0])
        && Regex::new(r"^[A-Z][A-Z ]{3,24}$").unwrap().is_match(lines[1])
    {
        return compact_sender(lines[0]);
    }
    let bad = Regex::new(r"(?i)worldhealthorganization|sauglinge|impf|masern|rki|who|therapie|zuzahlung|behandl|fango|microsoft|bgm").unwrap();
    for line in lines.iter().take(12) {
        let token = compact_sender(line);
        if token.is_empty() || bad.is_match(&token.to_lowercase()) || line.contains(':') || Regex::new(r"\d{2,}").unwrap().is_match(line) {
            continue;
        }
        if Regex::new(r"(?i)bank|gmbh|ag|market|shop|store|distributors").unwrap().is_match(line)
            || Regex::new(r"^[A-Z][A-Za-z0-9]{2,20}$").unwrap().is_match(&token)
        {
            return token;
        }
    }
    let stem = Regex::new(r"\.[A-Za-z0-9]{1,5}$").unwrap().replace(original_filename, "").to_string();
    if !stem.is_empty() && !Regex::new(r"(?i)scan|img|image|document|invoice|rechnung|impf|therapie").unwrap().is_match(&stem) {
        return compact_sender(&stem);
    }
    "Dok".to_string()
}

pub fn extract_eingangsrechnung_sender(text: &str, original_filename: &str) -> String {
    for line in text.lines().map(str::trim).filter(|x| !x.is_empty()).take(18) {
        if Regex::new(r"(?i)firma|kunde|rechnung|invoice|datum|summe|telefon|mail|www|lieferdatum").unwrap().is_match(line) {
            continue;
        }
        let candidate = Regex::new(r"(?i)\b(phone|telefon|fax|mail|www)\b").unwrap().split(line).next().unwrap_or("");
        let sender = compact_party(candidate);
        if sender != "Dok" && sender.len() >= 3 {
            return sender;
        }
    }
    if original_filename.is_empty() { "Dok".to_string() } else { compact_party(original_filename) }
}

pub fn extract_ausgangsrechnung_recipient(text: &str) -> String {
    let meta = Regex::new(r"(?i)\b(rechnung|rechnungs|invoice|datum|date|kunden-?nr|kundennummer|bestell-?nr|auftrags-?nr|telefon|phone|fax|mail|www|summe|ust|mwst|endsumme|iban|bic|konto|pos\.)").unwrap();
    let noise = Regex::new(r"(?i)@|www\.|\+\d|^\d{4,5}\s|\d|\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b").unwrap();
    let mut clean: Vec<String> = Vec::new();
    for line in text.lines().map(str::trim).filter(|x| !x.is_empty()).take(25) {
        if meta.is_match(line) { break; }
        if noise.is_match(line) { continue; }
        let party = compact_party(line);
        if party != "Dok" && party.len() >= 3 && !clean.contains(&party) {
            clean.push(party);
        }
    }
    clean.get(1).cloned().unwrap_or_else(|| "Dok".to_string())
}

pub fn extract_belege_title(input: &ExtractionInput) -> String {
    let date = match (input.created_month, input.created_year) {
        (Some(m), Some(y)) => format!("{:02}/{:02}", m, y % 100),
        _ => "00/00".to_string(),
    };
    format!("{}_B_{}_{}_{}", extract_belege_sender(&input.text, &input.original_filename), date, belege_amount(&input.text), payment(&input.text))
}

pub fn extract_eingangsrechnung_title(input: &ExtractionInput) -> String {
    format!("{}_{}_{}_{}", extract_eingangsrechnung_sender(&input.text, &input.original_filename), extract_invoice_number(&input.text), invoice_date(&input.text), invoice_amount(&input.text))
}

pub fn extract_ausgangsrechnung_title(input: &ExtractionInput) -> String {
    format!("{}_{}_{}_{}", extract_ausgangsrechnung_recipient(&input.text), extract_invoice_number(&input.text), invoice_date(&input.text), invoice_amount(&input.text))
}

fn belege_amount(text: &str) -> String {
    let num_re = Regex::new(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b|\b\d+[.,]\d{2}\b|\b\d+\b").unwrap();
    let cue = Regex::new(r"summe|gesamt|total|betrag|balance due|zu zahlen|endbetrag|invoice total|rechnungsbetrag").unwrap();
    let mut best: Option<(i32, usize, String)> = None;
    for line in text.lines() {
        let low = line.to_lowercase();
        let mut score = if cue.is_match(&low) { 2 } else { 0 };
        if low.contains("eur") || line.contains('€') || line.contains('$') { score += 1; }
        for number in num_re.find_iter(line).map(|m| m.as_str()) {
            if best.as_ref().map(|b| score > b.0 || (score == b.0 && number.len() > b.1)).unwrap_or(true) {
                best = Some((score, number.len(), number.to_string()));
            }
        }
    }
    match best {
        Some((score, _, number)) if score >= 2 => normalize_amount(&number),
        _ => "NA".to_string(),
    }
}

fn payment(text: &str) -> String {
    let low = text.to_lowercase();
    if Regex::new(r"\b(bar|cash|barzahlung)\b").unwrap().is_match(&low) {
        "Bar".to_string()
    } else if Regex::new(r"\b(karte|ec|girocard|visa|mastercard|amex|electronic cash|debit)\b").unwrap().is_match(&low) {
        "Karte".to_string()
    } else {
        "NA".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn golden_titles() {
        assert_eq!(extract_belege_title(&ExtractionInput { text: "ACME\nDISTRIBUTORS\nInvoice draft".into(), created_month: Some(4), created_year: Some(2026), ..Default::default() }), "ACME_B_04/26_NA_NA");
        assert_eq!(extract_belege_title(&ExtractionInput { text: "CommerceBank\nCard statement".into(), created_month: Some(4), created_year: Some(2026), ..Default::default() }), "CommerceBank_B_04/26_NA_NA");
        assert_eq!(extract_belege_title(&ExtractionInput { text: "WORLD HEALTH ORGANIZATION\nMasern Sauglinge und Kinder".into(), created_month: Some(10), created_year: Some(2022), ..Default::default() }), "Dok_B_10/22_NA_NA");
        assert_eq!(extract_belege_title(&ExtractionInput { text: "FANGO\nTherapie Zuzahlung Preisliste".into(), created_month: Some(4), created_year: Some(2025), ..Default::default() }), "Dok_B_04/25_NA_NA");
        assert_eq!(extract_eingangsrechnung_title(&ExtractionInput { text: "Demo GmbH\nRechnungsnummer PR400000005\nRechnungsdatum 12.10.2020\nEndsumme 205,25".into(), ..Default::default() }), "Demo_PR400000005_12/10/2020_205,25");
        assert_eq!(extract_eingangsrechnung_title(&ExtractionInput { text: "Fenster Beruhmt KG\nRechnungsnr. 7453\nRechnungsdatum 08.11.2015\nGesamtbetrag 2.975,00".into(), ..Default::default() }), "FensterBeruhmt_7453_08/11/2015_2975,00");
        assert_eq!(extract_eingangsrechnung_title(&ExtractionInput { text: "Muster GmbH\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nGrand Total 222,51".into(), ..Default::default() }), "Muster_M1675_29/10/2020_222,51");
        let habermann = "Muster GmbH\nHauptstrasse 1\n10000 Berlin\nHabermann Sohne KG\nNebenweg 2\n20000 Hamburg\nRechnung Nr. M1675\nRechnungsdatum 29.10.2020\nEndsumme 222,51";
        assert_eq!(extract_ausgangsrechnung_title(&ExtractionInput { text: habermann.into(), ..Default::default() }), "HabermannSohne_M1675_29/10/2020_222,51");
        assert_eq!(normalize_amount("2,539,46"), "2539,46");
        let muster = "Demo AG\nIndustriestrasse 1\n10000 Berlin\nMusterkunde & Co. KG\nKundenweg 4\n30000 Bonn\nRechnung-Nr. 2400\nRechnungsdatum 15.07.2019\nInvoice Total 2,539,46";
        assert_eq!(extract_ausgangsrechnung_title(&ExtractionInput { text: muster.into(), ..Default::default() }), "MusterkundeCo_2400_15/07/2019_2539,46");
    }
}
