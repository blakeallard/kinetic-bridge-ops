# Zoho/Deluge Parser Draft

## Scope

[`deluge/parse_meeting_summary.deluge`](../deluge/parse_meeting_summary.deluge) is a dry-run parser draft for a future Zoho Flow or WorkDrive custom function. It accepts already-fetched text and returns candidate action-item data. It contains no file fetch, `invokeurl`, OAuth, Zoho Projects task creation, registry mutation, or other live integration code.

The Python parser in [`scripts/parse_summary.py`](../scripts/parse_summary.py) remains the source of truth. The checked-in files under `samples/` and `samples/expected/` define the validated behavior. Deluge output should not be treated as equivalent until the draft is pasted into the selected Zoho product's sandbox/editor and its output is compared with every Python fixture.

## Expected Input

The custom function receives one map named `flow_input`:

| Key | Type | Required | Meaning |
| --- | --- | --- | --- |
| `file_id` | Text | Preferred | Stable WorkDrive file ID for future traceability/idempotency |
| `file_name` | Text | Yes | Source filename; must end in `_summary.txt` |
| `file_path` | Text | No | WorkDrive display/audit path |
| `file_text` | Text | Yes | Summary content fetched by the caller |

Fetching content is deliberately outside this draft. A future Flow/WorkDrive wrapper will provide the four values only after its trigger and file-fetch behavior are separately designed and approved.

## Return Shape

The function returns a map:

```text
{
  dry_run: true,
  parser_version: "deluge-draft-v1",
  file_id: "...",
  file_name: "..._summary.txt",
  file_path: "...",
  items: [ ...parsed item maps... ],
  item_count: 2,
  errors: []
}
```

Each item maps directly to the Python fields:

| Deluge field | Python reference | Rule |
| --- | --- | --- |
| `action_text` | `action_text` | Explicit top-level bullet text with inline metadata removed |
| `owner_raw` | `owner_raw` | Explicit owner values joined with `; `, or null |
| `owner_resolution` | `owner_resolution` | `matched`, `unresolved`, `multiple`, or `missing` |
| `owner_id` | `owner_id` | Set only for one known distinct owner; otherwise null |
| `detected_owners` | `detected_owners` | All distinct explicit owner identities and individual resolutions |
| `due_date_text` | `due_date_text` | Explicit due text preserved; never converted to a date |
| `source_file_name` | `source_file_name` | Input filename |
| `action_hash` | `action_hash` | SHA-256 canonical action identity |
| `fallback_idempotency_key` | Deluge-only safety field | Canonical composite for runtimes without SHA-256 |

Multiple detected people always produce `owner_resolution: "multiple"` and `owner_id: null`, even when every person is known. One unknown person produces `unresolved`; no explicit person produces `missing`. Positional `Action — Name` syntax is recognized only when every positional owner token matches the known owner map. This prevents arbitrary trailing action text from being inferred as a person.

## Parsing Equivalence

The draft follows the Python parser in two passes:

1. Normalize line endings and tabs.
2. Enter only `Action Items`, `Action Item`, `Next Actions`, or `Next Steps` sections.
3. Stop at Markdown headings, the named major headings, or conservative short Title Case headings.
4. Collect only top-level `-`, `*`, `•`, or numbered bullets.
5. Treat nested `Owner`, `Owners`, `Assignee`, `Assignees`, `Due`, and `Due Date` lines as metadata.
6. Ignore metadata that has no preceding action and nested non-metadata bullets.
7. Split inline em-dash/en-dash metadata and labeled ASCII-hyphen metadata.
8. Resolve only the configured aliases and preserve all unknown/multiple-owner evidence.
9. Preserve due-date text without interpretation.
10. Return item maps; perform no writes.

The alias map and canonical IDs match the Python reference exactly. They are included here as parser configuration and are not credentials.

## Known Deluge Differences

Deluge does not expose Python's Unicode NFKC normalization in the documented text functions. The draft therefore uses `trim`, lowercase conversion, and whitespace collapse for hash canonicalization. This produces the same SHA-256 hashes for the current ASCII fixtures, but non-ASCII action text needs explicit cross-runtime fixture testing.

The conservative plain-heading regex approximates Python's title-style heading detection. Product-specific regex behavior and editor escaping must be checked in the chosen Zoho runtime. Function declaration syntax also varies: some editors configure the function name, arguments, and return type in the UI and accept only the body.

The Deluge draft includes one extra item field, `fallback_idempotency_key`, so a missing SHA implementation does not force task-name deduplication.

## Hash and Fallback Strategy

Zoho's Deluge documentation provides `zoho.encryption.sha256(data)`, returning hexadecimal SHA-256 by default. The draft hashes:

```text
normalized(file_name) + "\n" + normalized(action_text)
```

This mirrors the Python reference for the current fixtures. If the selected Flow or WorkDrive runtime does not support `zoho.encryption.sha256`, remove that unsupported line during sandbox adaptation, set `action_hash` to null, and enforce uniqueness on the complete `fallback_idempotency_key`:

```text
(file_id when present, otherwise normalized file_name) + "::" + normalized action_text
```

The full composite must be stored and compared exactly. It is an idempotency key, not a cryptographic digest. Do not shorten it and do not fall back to task-name matching.

## Validation Procedure

No live integration is needed for parser validation:

1. Run the Python fixture test locally: `python3 -m unittest discover -s tests -v`.
2. Configure a sandbox custom function with a map input and map return value.
3. Paste the draft, adapting only the outer signature if the editor supplies it.
4. Pass each sample's filename and full text as `flow_input`; use inert placeholder values for `file_id` and `file_path`.
5. Compare `items` field-by-field with the corresponding `samples/expected/*.json`, ignoring only `fallback_idempotency_key`.
6. Record any regex, Unicode, or product-runtime difference before changing the draft or advancing to Flow wiring.

Do not add a WorkDrive fetch, registry write, or Projects task action during this validation.

## Deluge References

- [SHA-256 encryption task](https://www.zoho.com/deluge/help/encryption/sha256.html)
- [Text `toList` function](https://www.zoho.com/deluge/help/functions/string/tolist.html)
- [Map `put` function](https://www.zoho.com/deluge/help/functions/map/put.html)
- [List `add` function](https://www.zoho.com/deluge/help/functions/list/add.html)
- [Deluge text functions](https://www.zoho.com/deluge/help/functions/text.html)

