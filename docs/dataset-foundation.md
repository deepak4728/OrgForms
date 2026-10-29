# Dataset foundation

Implemented 25 October 2026 against the generic foundation in architecture v3. Deployment remains the existing organization-scoped SQLite data home.

## Configure a reusable collection

1. Open an organization and choose **Data → New dataset**. Define a name and fields. Keep field IDs stable when changing labels. An optional lookup-label field determines the single value disclosed alongside record IDs in permitted lookups.
2. Open **Dataset access** to grant current members Read, Write and/or Lookup. These permissions are independent. Admins and managers manage datasets and inherit all three. Lookup grants do not grant full-record, history or export access. Write grants permit record commands; they expose the field definition required to construct a command, not result rows.
3. In a form’s builder, select **Record destination** and its dataset schema version. Explicitly select a source collection question for each destination field. Required dataset fields must be mapped; each destination accepts one source of the same type. References must point at the same lookup dataset. Choosing **Responses only** keeps a standalone collection.
4. Accept a response. A single local transaction creates its submission/history, mapped record/history and retry receipt. No AI call is required. A second response creates another record, even when names match.
5. Open **Data → dataset → record** for its current values and immutable history. To update through a collection, select a connected collection on that page. This uses the record’s explicit ID/version and requires read and write access. Editing one’s original response uses its existing record link; it cannot choose a different record.

Several collections can use the same writable dataset. Each owns its question IDs, mapping and captured definition. Fields outside a collection’s mapping are preserved when it updates a record. A form audience authorizes collection capture, not browsing the destination dataset.

## Schema and conflict rules

Datasets use `orgforms-fields-v1`, the existing application field dialect, not arbitrary JSON Schema. Initial supported dataset values are text, textarea, email, tel, number, rating, select, radio, date, checkbox and `record_reference`. Collection-only files and item cards retain their private-file and typed-catalog behavior.

Changing a schema creates a new immutable schema version. Existing records/revisions retain their captured version and labels. Record editing reviews the current schema before saving an upgrade; it does not bulk-rewrite old records. Collection mappings remain pinned until explicitly reviewed and republished. Capture against an old destination schema conflicts rather than silently changing the record interpretation.

New records use the current schema ID. Updating a record requires its expected version. A stale version, archived dataset, invalid reference, changed binding or stale destination schema rolls back the entire mapped capture, including quota use, record changes and new attachment files. An unchanged reference on a direct record edit can be retained without a new lookup; choosing a reference requires current lookup access.

Schema/record immutability is enforced by application models/managers, not against a database administrator using raw SQL. Only authorized organization deletion removes the owned history. There is no physical per-form table, name/email identity join, automatic dataset export, or newly added AI retrieval source.

## API

Session-authenticated unsafe requests retain CSRF protection. Dataset IDs, schema-version IDs and record IDs are UUIDs. URL scope and current organization membership/grants are always checked.

| Endpoint | Behavior |
|---|---|
| `GET/POST /api/orgs/<org-slug>/datasets/` | List permitted datasets; admins/managers create definitions |
| `GET/PATCH /api/datasets/<dataset-id>/` | Read allowed metadata; managers update with `base_schema` containing the current schema-version UUID |
| `GET /api/datasets/<dataset-id>/schemas/` | Read-granted schema history, latest 100 |
| `GET/POST /api/datasets/<dataset-id>/records/` | Read results in pages of 50 (`?page=2`); create a record command |
| `GET/PATCH /api/datasets/<dataset-id>/records/<record-id>/` | Read/replace one record using explicit grants |
| `GET /api/datasets/<dataset-id>/records/<record-id>/history/` | Read-granted history with each version’s schema and provenance, latest 200 |
| `GET /api/datasets/<dataset-id>/lookup/?q=<label>` | Lookup-granted IDs/approved labels, at most 50; a blank label configuration uses exact UUID search |
| `GET/PUT /api/datasets/<dataset-id>/grants/` | Managers inspect/replace explicit membership grants atomically |

Example record command; replace UUID placeholders with actual IDs:

```json
{
  "request_id": "client-command-001",
  "schema_version_id": "<current-schema-version-uuid>",
  "expected_version": 1,
  "data": {"name": "Workshop participant"},
  "is_archived": false
}
```

Omit `expected_version` for creation. PATCH replaces the record’s validated values, rather than merging an arbitrary JSON object. Use a fresh request ID for a changed command. Repeating an identical committed command returns its original record/version with `replayed: true`; reusing the key for different content conflicts. Permissions are checked before replay. Revoking a grant or organization membership stops subsequent commands and replay.

Collection browser/API capture additionally accepts `record_id` and `record_version` for explicit updates. Supplying an existing record ID requires dataset write access; browser prefill also requires read access. Captures return record identifiers/versions, not the record’s other fields. A response’s edit token is scoped to the original caller/session, as before.

## Prototype limits and follow-on work

The HTML viewer shows the latest 100 records, up to three values per row and full detail on the record page. Its table scrolls internally at narrow widths. CSV exports at most 5,000 records. Dataset lists cap at 100; lookup selects show an initial bounded result set (browser 50, staff record editor 200); larger directories need a paginated searchable picker. These bounds prevent unbounded prototype responses; they are not a production reporting solution.

The foundation is organization-neutral. It does not complete department approvals, granular process/field grants, voice adapters, resource allocation, a device wallet, an AI job queue, production HTTPS/backup restoration, the installer or hosted services. Those remain explicit stages in `implementation-status.md`. Existing data is preserved as legacy collection responses until a deliberate import/mapping feature is implemented; it is not guessed into datasets.
