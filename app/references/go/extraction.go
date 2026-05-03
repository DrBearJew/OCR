package extraction

import (
	"regexp"
	"strconv"
	"strings"
	"time"
)

type DocumentState string

const (
	Uploaded           DocumentState = "uploaded"
	QueuedForOCR       DocumentState = "queued_for_ocr"
	OCRProcessing      DocumentState = "ocr_processing"
	OCRDone            DocumentState = "ocr_done"
	MetadataProcessing DocumentState = "metadata_processing"
	Complete           DocumentState = "complete"
	Failed             DocumentState = "failed"
)

type Input struct {
	Text             string
	OriginalFilename string
	CreatedAt        *time.Time
	ExistingTitle    string
}

var invoiceNumberPatterns = []*regexp.Regexp{
	regexp.MustCompile(`(?i)\bEingangsrechnung\s+([A-Z0-9][A-Z0-9./-]{2,})\b`),
	regexp.MustCompile(`(?i)\bRechnungs\s*nummer\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bRechnungs\s*nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bRechnungs\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bRechnung\s*-\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bRechnung\s*Nr\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bInvoice\s*No\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bInvoice\s*Number\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
	regexp.MustCompile(`(?i)\bBeleg(?:nr|nummer)\.?\s*[:#.]?\s*([A-Z0-9][A-Z0-9./-]{1,})\b`),
}

func compactParty(value string) string {
	value = regexp.MustCompile(`(?i)\b(ges\.?\s*mbh|gesmbh|gmbh|mbh|ag|kg|ug|inc|ltd|llc|sarl|e\.?k\.?)\b`).ReplaceAllString(value, " ")
	value = regexp.MustCompile(`[^A-Za-z0-9 ]+`).ReplaceAllString(value, " ")
	parts := strings.Fields(value)
	if len(parts) > 3 {
		parts = parts[:3]
	}
	out := strings.Join(parts, "")
	if out == "" {
		return "Dok"
	}
	if len(out) > 40 {
		return out[:40]
	}
	return out
}

func compactSender(value string) string {
	value = strings.ReplaceAll(value, "&", " And ")
	value = regexp.MustCompile(`[_/\\|]+`).ReplaceAllString(value, " ")
	value = regexp.MustCompile(`[^A-Za-z0-9 .,-]+`).ReplaceAllString(value, " ")
	parts := strings.Fields(value)
	if len(parts) > 3 {
		parts = parts[:3]
	}
	for i, part := range parts {
		if part == strings.ToUpper(part) && len(part) <= 8 {
			continue
		}
		if len(part) > 0 {
			parts[i] = strings.ToUpper(part[:1]) + part[1:]
		}
	}
	out := regexp.MustCompile(`[^A-Za-z0-9]+`).ReplaceAllString(strings.Join(parts, ""), "")
	if len(out) > 32 {
		return out[:32]
	}
	return out
}

func NormalizeDate(raw string) string {
	re := regexp.MustCompile(`(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})`)
	m := re.FindStringSubmatch(raw)
	if m == nil {
		return ""
	}
	day, _ := strconv.Atoi(m[1])
	month, _ := strconv.Atoi(m[2])
	year, _ := strconv.Atoi(m[3])
	if year < 100 {
		if year < 70 {
			year += 2000
		} else {
			year += 1900
		}
	}
	return fmtDate(day, month, year)
}

func fmtDate(day, month, year int) string {
	return two(day) + "/" + two(month) + "/" + strconv.Itoa(year)
}

func two(n int) string {
	if n < 10 {
		return "0" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

func NormalizeAmount(raw string) string {
	value := regexp.MustCompile(`[^0-9,.\-]`).ReplaceAllString(strings.TrimSpace(raw), "")
	if value == "" {
		return "NA"
	}
	var candidates []string
	if strings.Contains(value, ",") && strings.Contains(value, ".") {
		if strings.LastIndex(value, ",") > strings.LastIndex(value, ".") {
			candidates = append(candidates, strings.ReplaceAll(strings.ReplaceAll(value, ".", ""), ",", "."))
		} else {
			candidates = append(candidates, strings.ReplaceAll(value, ",", ""))
		}
	} else if strings.Contains(value, ",") {
		parts := strings.Split(value, ",")
		last := parts[len(parts)-1]
		if len(last) == 2 {
			candidates = append(candidates, strings.ReplaceAll(strings.ReplaceAll(value, ".", ""), ",", "."))
		} else if len(parts) == 2 && len(last) == 3 {
			candidates = append(candidates, strings.ReplaceAll(value, ",", ""))
		}
	} else if strings.Contains(value, ".") {
		parts := strings.Split(value, ".")
		if len(parts) == 2 && len(parts[1]) == 3 {
			candidates = append(candidates, strings.ReplaceAll(value, ".", ""))
		} else {
			candidates = append(candidates, value)
		}
	} else {
		candidates = append(candidates, value)
	}
	lastSep := regexp.MustCompile(`([.,])(\d{2})$`).FindStringSubmatchIndex(value)
	if lastSep != nil {
		intPart := regexp.MustCompile(`[^0-9]`).ReplaceAllString(value[:lastSep[2]], "")
		frac := value[lastSep[4]:lastSep[5]]
		if intPart != "" {
			candidates = append(candidates, intPart+"."+frac)
		}
	}
	for _, candidate := range candidates {
		if parsed, err := strconv.ParseFloat(candidate, 64); err == nil {
			return strings.ReplaceAll(strconv.FormatFloat(parsed, 'f', 2, 64), ".", ",")
		}
	}
	return "NA"
}

func ExtractInvoiceNumber(text string) string {
	clean := regexp.MustCompile(`[^A-Za-z0-9./-]+`)
	for _, line := range strings.Split(text, "\n") {
		low := strings.ToLower(strings.TrimSpace(line))
		if strings.Contains(low, "kundennummer") || strings.Contains(low, "customer") || strings.Contains(low, "auftrags") || strings.Contains(low, "bestell") {
			continue
		}
		for _, pattern := range invoiceNumberPatterns {
			if m := pattern.FindStringSubmatch(line); m != nil {
				out := clean.ReplaceAllString(m[1], "")
				if len(out) > 40 {
					return out[:40]
				}
				return out
			}
		}
	}
	return "NA"
}

func invoiceDate(text string, createdAt *time.Time) string {
	lines := strings.Split(text, "\n")
	for _, line := range lines {
		low := strings.ToLower(line)
		if strings.Contains(low, "rechnungsdatum") || strings.Contains(low, "invoice date") {
			if d := NormalizeDate(line); d != "" {
				return d
			}
		}
	}
	for _, line := range lines {
		low := strings.ToLower(line)
		if strings.Contains(low, "lieferdatum") || strings.Contains(low, "leistungsdatum") || strings.Contains(low, "valutadatum") {
			continue
		}
		if strings.Contains(low, "datum") || strings.Contains(low, "date") {
			if d := NormalizeDate(line); d != "" {
				return d
			}
		}
	}
	if createdAt != nil {
		return fmtDate(createdAt.Day(), int(createdAt.Month()), createdAt.Year())
	}
	return "00/00/0000"
}

func invoiceAmount(text string) string {
	numRe := regexp.MustCompile(`\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b|\b\d+[.,]\d{2}\b|\b\d+\b`)
	type row struct {
		score int
		value float64
		amount string
	}
	var rows []row
	for _, line := range strings.Split(text, "\n") {
		nums := numRe.FindAllString(line, -1)
		if len(nums) == 0 {
			continue
		}
		low := strings.ToLower(line)
		score := 0
		if regexp.MustCompile(`endsumme|gesamtsumme|gesamtbetrag|zu zahlen|balance due|invoice total|grand total|brutto`).MatchString(low) {
			score = 4
		} else if regexp.MustCompile(`summe|gesamt|total|rechnungsbetrag`).MatchString(low) {
			score = 2
		}
		if regexp.MustCompile(`netto|mwst|ust|steuer|skonto|rabatt`).MatchString(low) && score < 4 {
			score -= 3
		}
		amount := NormalizeAmount(nums[len(nums)-1])
		if amount == "NA" {
			continue
		}
		val, _ := strconv.ParseFloat(strings.ReplaceAll(amount, ",", "."), 64)
		rows = append(rows, row{score, val, amount})
	}
	best := row{score: -999}
	for _, candidate := range rows {
		if candidate.score > best.score || (candidate.score == best.score && candidate.value > best.value) {
			best = candidate
		}
	}
	if best.score == -999 {
		return "NA"
	}
	return best.amount
}

func ExtractBelegeSender(text, originalFilename string) string {
	lines := nonEmptyLines(text)
	if len(lines) >= 2 && regexp.MustCompile(`^[A-Z]{3,8}$`).MatchString(lines[0]) && regexp.MustCompile(`^[A-Z][A-Z ]{3,24}$`).MatchString(lines[1]) {
		return compactSender(lines[0])
	}
	bad := regexp.MustCompile(`(?i)worldhealthorganization|sauglinge|impf|masern|rki|who|therapie|zuzahlung|behandl|fango|microsoft|bgm`)
	for i, line := range lines {
		if i >= 12 {
			break
		}
		token := compactSender(line)
		low := strings.ToLower(token)
		if token == "" || bad.MatchString(low) || strings.Contains(line, ":") || regexp.MustCompile(`\d{2,}`).MatchString(line) {
			continue
		}
		if regexp.MustCompile(`(?i)bank|gmbh|ag|market|shop|store|distributors`).MatchString(line) || regexp.MustCompile(`^[A-Z][A-Za-z0-9]{2,20}$`).MatchString(token) {
			return token
		}
	}
	stem := regexp.MustCompile(`\.[A-Za-z0-9]{1,5}$`).ReplaceAllString(originalFilename, "")
	if stem != "" && !regexp.MustCompile(`(?i)scan|img|image|document|invoice|rechnung|impf|therapie`).MatchString(stem) {
		return compactSender(stem)
	}
	return "Dok"
}

func ExtractEingangsrechnungSender(text, originalFilename string) string {
	for i, line := range nonEmptyLines(text) {
		if i >= 18 {
			break
		}
		if regexp.MustCompile(`(?i)firma|kunde|rechnung|invoice|datum|summe|telefon|mail|www|lieferdatum`).MatchString(line) {
			continue
		}
		candidate := regexp.MustCompile(`(?i)\b(phone|telefon|fax|mail|www)\b`).Split(line, 2)[0]
		candidate = regexp.MustCompile(`(?i)\b(strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b`).Split(candidate, 2)[0]
		candidate = regexp.MustCompile(`\b\d{4,5}\b`).Split(candidate, 2)[0]
		sender := compactParty(candidate)
		if sender != "Dok" && len(sender) >= 3 {
			return sender
		}
	}
	if originalFilename != "" {
		return compactParty(regexp.MustCompile(`\.[A-Za-z0-9]{1,5}$`).ReplaceAllString(originalFilename, ""))
	}
	return "Dok"
}

func ExtractAusgangsrechnungRecipient(text string) string {
	meta := regexp.MustCompile(`(?i)\b(rechnung|rechnungs|invoice|datum|date|kunden-?nr|kundennummer|bestell-?nr|auftrags-?nr|telefon|phone|fax|mail|www|summe|ust|mwst|endsumme|iban|bic|konto|pos\.)`)
	var clean []string
	seen := map[string]bool{}
	for i, line := range nonEmptyLines(text) {
		if i >= 25 || meta.MatchString(line) {
			break
		}
		if regexp.MustCompile(`@|www\.|\+\d|^\d{4,5}\s|\d|\b(?i:strasse|straße|str\.?|weg|gasse|allee|platz|ufer|ring)\b`).MatchString(line) {
			continue
		}
		candidate := compactParty(line)
		if candidate != "Dok" && len(candidate) >= 3 && !seen[candidate] {
			seen[candidate] = true
			clean = append(clean, candidate)
		}
	}
	if len(clean) >= 2 {
		return clean[1]
	}
	return "Dok"
}

func ExtractBelegeTitle(input Input) string {
	date := "00/00"
	if input.CreatedAt != nil {
		date = two(int(input.CreatedAt.Month())) + "/" + two(input.CreatedAt.Year()%100)
	}
	return ExtractBelegeSender(input.Text, input.OriginalFilename) + "_B_" + date + "_" + belegeAmount(input.Text) + "_" + payment(input.Text)
}

func ExtractEingangsrechnungTitle(input Input) string {
	return ExtractEingangsrechnungSender(input.Text, input.OriginalFilename) + "_" + ExtractInvoiceNumber(input.Text) + "_" + invoiceDate(input.Text, input.CreatedAt) + "_" + invoiceAmount(input.Text)
}

func ExtractAusgangsrechnungTitle(input Input) string {
	return ExtractAusgangsrechnungRecipient(input.Text) + "_" + ExtractInvoiceNumber(input.Text) + "_" + invoiceDate(input.Text, input.CreatedAt) + "_" + invoiceAmount(input.Text)
}

func belegeAmount(text string) string {
	numRe := regexp.MustCompile(`\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b|\b\d+[.,]\d{2}\b|\b\d+\b`)
	bestScore := -1
	best := ""
	for _, line := range strings.Split(text, "\n") {
		score := 0
		low := strings.ToLower(line)
		if regexp.MustCompile(`summe|gesamt|total|betrag|balance due|zu zahlen|endbetrag|invoice total|rechnungsbetrag`).MatchString(low) {
			score += 2
		}
		if strings.Contains(low, "eur") || strings.Contains(line, "€") || strings.Contains(line, "$") {
			score++
		}
		for _, number := range numRe.FindAllString(line, -1) {
			if score > bestScore || (score == bestScore && len(number) > len(best)) {
				bestScore = score
				best = number
			}
		}
	}
	if bestScore < 2 {
		return "NA"
	}
	return NormalizeAmount(best)
}

func payment(text string) string {
	low := strings.ToLower(text)
	if regexp.MustCompile(`\b(bar|cash|barzahlung)\b`).MatchString(low) {
		return "Bar"
	}
	if regexp.MustCompile(`\b(karte|ec|girocard|visa|mastercard|amex|electronic cash|debit)\b`).MatchString(low) {
		return "Karte"
	}
	return "NA"
}

func nonEmptyLines(text string) []string {
	var out []string
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			out = append(out, line)
		}
	}
	return out
}
