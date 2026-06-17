# ADR: Paperless-style metadata auto-assignment with Qwen

## Status
Accepted

## Context
Dok OCR must auto-assign metadata after OCR in the same spirit as Paperless-ngx: a consumed document should receive correspondent/sender, document type or collection, tags/folders, dates, invoice numbers, amounts, custom fields, and a useful title without manual review when the evidence is clear.

The failure on document `4ebf57df-8c93-4c33-a84d-2dbaab05de22` showed that the previous flow treated deterministic parser output as field truth too early. A weak deterministic amount from a legal footer (`HRB 201055`), a stale `_NA` title, and a damaged sender could block completion even though Qwen had grounded evidence for the correct invoice metadata.

Server Paperless evidence used for this decision:

- `/usr/src/paperless/src/documents/models.py`: Paperless models `Correspondent`, `DocumentType`, `Tag`, and `StoragePath` inherit matching fields from `MatchingModel`.
- `/usr/src/paperless/src/documents/matching.py`: Paperless combines rule matching and automatic classifier predictions for assignable document metadata.
- `/usr/src/paperless/src/documents/signals/handlers.py`: post-consumption handlers assign correspondent, document type, tags, and storage path.
- `/usr/src/paperless/src/documents/apps.py`: `document_consumption_finished` wires assignment handlers before indexing/workflows.
- `/opt/paperless/paperless-ngx/paperless-gpt/prompts/*.tmpl`: Paperless-GPT uses LLM prompts for correspondent, document type, tags, title, and custom-field extraction.

## Decision
Introduce an explicit metadata authority resolver between candidate generation and persisted document fields.

Pipeline:

```text
OCR text
  -> candidate generation
       deterministic parser candidates
       Qwen metadata-brain candidates
       Paperless-style profile/rule candidates
       similar reviewed document candidates
  -> metadata authority resolver
  -> canonical document metadata
  -> derived title/folder/tags/search data
  -> review gate only for unresolved or unsafe cases
```

Authority order:

```text
manual lock
  > explicit manual value
  > high-confidence grounded Qwen candidate
  > exact deterministic label extraction
  > learned/similar-document candidate
  > weak fallback extraction
  > review
```

Generated titles, folders, tags, and search hints are derived outputs. They must not become authoritative input for a later Qwen call unless manually locked or manually overridden.

## Consequences
Positive:

- Qwen can auto-correct weak deterministic output when it has OCR-grounded evidence.
- Review blockers are reserved for real uncertainty, missing required fields, OCR failures, or strong unresolved conflicts.
- Field provenance is explicit and stored with the document.
- The architecture now matches the Paperless pattern of post-consumption assignment instead of scattered field mutation.

Tradeoffs:

- Deterministic extraction remains valuable but no longer has blanket authority.
- The resolver adds a formal candidate ledger that increases metadata JSON size slightly.
- Future profile/rule learning still needs a dedicated DB-backed matching profile model.

## Implementation Plan
1. Add `app/backend/app/services/metadata_resolver.py` with candidate and resolution contracts.
2. Make `processing.py` delegate canonical field decisions to the resolver while keeping compatibility wrappers for current callers/tests.
3. Store `metadata_json["metadata_resolution"]` for auditability.
4. Update Qwen prompt payload so stale generated titles are not treated as authoritative input.
5. Add resolver tests proving Qwen wins over weak deterministic candidates and manual locks still win.
6. Later: add DB-backed Paperless-style metadata profiles for sender, type, tag, folder, and custom-field assignment.

## Verification
- Unit tests for resolver authority order.
- Existing processing/Qwen tests must continue passing.
- Regression test for O2/Telefonica invoice behavior.
- Live document diagnostics must show complete processing with no review blockers when fields are resolved.

## Rollback
Revert the resolver import/delegation in `processing.py` and remove `metadata_resolution` storage. Since no DB migration is introduced in this phase, rollback is code-only.


## Implemented Profile Matcher Slice
The next backend slice implements DB-backed Paperless-style profile matching using the existing metadata tables:

- `correspondents.match_rules`
- `document_types.match_rules`
- `tags.match_rules`
- `storage_path_rules.match_rules`

Supported rule shapes:

```json
{"matching_algorithm": "any", "match": ["Telefonica", "O2"]}
{"matching_algorithm": "all", "match": ["invoice", "mobile"]}
{"matching_algorithm": "literal", "match": "Rechnungsbetrag"}
{"matching_algorithm": "regex", "match": "Rechnungsnummer\s+[A-Z0-9/-]+"}
{"matching_algorithm": "fuzzy", "match": "Telefónica Germany"}
{"matching_algorithm": "automatic", "aliases": ["Mobilfunk", "Invoices/Mobile"]}
```

The matcher evaluates OCR text, canonical fields, Qwen candidates, suggested tags/folders, and metadata JSON. It assigns correspondent, document type, tags, and storage path unless the corresponding assignment is manually sourced or metadata is locked. Admin endpoints can now create, update, list, and delete these metadata profiles.


## Automatic Profile Bootstrap Slice
Profile rules are tuning, not a prerequisite for automatic metadata assignment. When Qwen/canonical metadata provides safe values, Dok OCR automatically creates or reuses Paperless-style profiles:

- canonical sender/recipient -> correspondent profile
- Qwen/canonical document type -> document type profile
- safe Qwen suggested tags -> tag profiles
- safe Qwen suggested folder -> storage path profile

Safety filters reject empty values, `NA`, numeric-only years, invoice-like IDs, legal identifiers, and unsafe folder paths. Manually sourced assignments and metadata locks still take precedence.
