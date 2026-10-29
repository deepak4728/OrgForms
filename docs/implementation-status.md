# Architecture reconciliation and implementation status

Updated: 26 October 2026. This file distinguishes running code from the target design.

## Plan precedence

1. `universal-platform-architecture-v3.md` defines the product and shared collection contracts.
2. `local-cloud-architecture.md` defines data placement, authority, inference, and deployment sequencing.
3. `installed-server-experience.md` specifies a future production installer/runtime.
4. `product-architecture-v2.md` retains useful optional operations/ordering/billing requirements. Its cafe-first stage ordering does not override v3's generic foundation. Branches, departments, queues, ordering, and payments are not prerequisites for a survey or internal collection.

## Department foundation — 26 October 2026

People → Departments now supports optional flat departments, multi-department staff assignments, collection stewardship, and archive/restore. Admins manage them; organization members can view the directory, with collection names filtered through existing visibility checks. Groups have been converted to departments. Staff assignments and stewardship alone do not grant access; a restricted form can explicitly grant its department access, which also allows its members to view that form’s response records. Department grants do not grant form editing. Removing a membership removes its staff assignments. Archived departments retain their assignments and stewardship; editing requires restoration. Names are unique within an organization, including archived departments.

The browser and standard form POST actions are available on the existing People page. Dedicated department APIs, branches, scoped operational grants, approval/work queues, routing, and their active-work archive restrictions remain future work. No department is required for a survey. These relationships share the installation's authoritative database and do not provision another data home.

AI Hub additionally supports private account memory, bounded context compaction, unsaved chats, and owner-scoped confirmed single/bulk chat deletion. Deleting chats preserves separately saved memory notes. This does not implement the production inference queue or device wallet.

## Reviewed local AI creation — 26 October 2026

Organization creation accepts a typed request and an optional first form. Proposals are generated with an installed Ollama model and reviewed before the organization, owner membership and unpublished first form are committed atomically. The form builder uses the same explicit local drafting path. Microphone recording, audio uploads, and Whisper transcription were removed on 28 October 2026; creation is text-only. Limits, context disclosure and authorization are documented in [local AI creation](local-ai-creation.md).

This is creation assistance, not the later voice capture/normalization workflow, durable AI queue or production microphone/TLS acceptance.

## Repository assessment

Before this work, the five-app Django monolith already had organizations, membership roles, per-form audiences, JSON-defined fields, private files, public form URLs, catalog selection, response views/CSV, and local/cloud AI adapters. It lacked immutable definition versions, response history, replay protection, and a concurrent response quota. Those were the next dependencies for reliable capture, before reusable datasets or operational capabilities.

## Completed stage: versioned collection and capture foundation

- Keep `DynamicForm` as the collection adapter and existing public URLs. Saving changes to title, description, purpose, or schema creates an immutable `CollectionRevision`; changing audience/status/response limit uses current policy without rewriting historical definitions.
- Each response references its captured definition. An edit validates against that original definition and increments the response version. An explicit stale definition or edit version returns a conflict instead of silently reinterpreting input.
- One transaction service handles browser and authenticated API capture, typed validation, current permission checks, optional catalog selections, private uploads, response snapshots, and receipts. Successful capture requires a committed local database transaction. AI and cloud services are not involved in acceptance.
- Immutable `SubmissionRevision` entries record the answer snapshot, respondent metadata, actor/source, status, attachment identifiers, and catalog names/prices/totals. Replacement files remain private and retained for earlier versions. Ordinary views list only current files; existing permission-checked download routes protect historical files too.
- Optional `response_limit` is a generic collection policy. New submissions consume a place; edits and retries do not. A first transactional database write serializes quota/receipt/edit decisions on SQLite; lock/commit failures return an actionable 503 without a successful receipt.
- Caller-scoped `request_id`/`Idempotency-Key` receipts replay a committed capture. Reusing a key with a different payload conflicts. Permission revocation is checked before replay. Guests must retain their session cookie; identities are not joined by email/name.
- Public pages include definition IDs, optimistic edit versions, and stable retry keys. Manual creation and capture work while AI is unavailable. The builder uses generic fields, audiences, item catalogs, and optional AI suggestions across organization categories.
- Response views, CSV, and history APIs expose captured revision/version metadata and original question labels. Cross-organization transfers of forms with responses are blocked; duplicate/archive instead.
- Additive migrations preserve current definitions and responses as explicitly marked legacy baselines. Earlier overwritten schemas cannot be reconstructed. The legacy importer also creates baselines transactionally; existing documents are not moved to a device wallet.

The supported schema dialect is `orgforms-fields-v1`: the existing `{fields: [...]}` representation, optionally declaring `dialect`. It is a documented application format, not arbitrary JSON Schema support. Stable IDs, supported types, bounds, required flags, options, and acyclic `visibleWhen` dependencies are validated server-side.

## Completed stage: reusable dataset foundation

- Add the sixth app, `datasets`, with organization-scoped `Dataset`, immutable `DatasetSchemaVersion`, current `Record`, immutable `RecordRevision`, explicit member `DatasetGrant`, and caller-scoped `RecordCommandReceipt`.
- The Data workspace supports visual schema editing, record creation/editing, original-schema labels, schema/record history, search and CSV. Admins and managers manage definitions/grants; members receive independent read, write and lookup access. Lookup-only access exposes record IDs and a manager-selected label, never full values or record history. Write-only access permits commands and current field definitions without reading result rows.
- Collections pin one writable dataset schema version and an explicit source-to-destination mapping in their immutable collection revision. Same-type fields and required targets are validated. Multiple collections can write to the same dataset with different question IDs. Standalone collections remain supported.
- Capture commits submissions, mapped records/revisions and receipts atomically. Existing records are addressed only by an explicit record ID and expected version (or a response’s existing link), never by matching a name/email. Mapped edits retain unmapped record values. Stale records/schema mappings and archived destinations reject acceptance without consuming response quota or keeping partial uploads.
- Dataset commands require request IDs and current schema IDs; updates also require expected record versions. First-write serialization protects SQLite commands and schema edits. Replaying identical committed commands does not create additional records/revisions, and current permissions are checked before replay.
- Same-organization `record_reference` fields enforce independent lookup permission. Scalar fields and references are the initial dataset dialect; files and item cards retain their existing typed collection/capture path. No industry-specific records are prerequisites for Data.
- Additive migrations create the new tables and optional binding/record links. Existing response/history counts and contents remain unchanged. There is no speculative conversion of legacy data, new tenant hierarchy, automatic AI-context expansion, cloud export, or replicated database.

## Remaining stages, in dependency order

| Stage | Status and scope |
|---|---|
| Capture/permission expansion | Separate submit/edit/results/process/field grants, department approval as an optional capability, durable adapter commands, generic audit events beyond capture, and equivalent manual/voice/API validation. Existing role-based permissions remain the current baseline. |
| Operational reference scenarios | Complete and test the survey, internal equipment request with asset lookup/approval, and cafe configuration with voice/queues/resources in the same release. Current shared capture tests across categories do not establish those complete workflows. |
| Wallet and task-policy AI | Independent customer device vault, explicit disclosure receipts, encrypted wallet export/import, per-task cloud approval/payload budgets, and a bounded persistent local AI queue. Current personal profiles/documents remain server-stored; provider choice is still coarse. |
| Production local runtime | Production ASGI process, HTTPS proxy, protected data paths, worker, verified backup/restore, boot services and a signed installer. The existing Windows launcher is a loopback development convenience. No production service, public listener, cloud account, or hosted database was provisioned here. |
| Optional cloud services | Distribution/registration/templates, encrypted backup transport and approved read-only projections, then hosted workspaces and separately enabled remote access. No automatic database synchronization or failover. |

Native billing follows the optional ordering capability and must use typed financial records and its own issuer/calculation acceptance gates. Neither belongs in the base capture path.

## Compatibility and limitations

Older clients may omit revision IDs, request keys, and optimistic edit versions. They use the latest definition for new responses and the original definition for edits; without a key/version they do not gain retry deduplication or stale-client detection. New browser requests always supply these controls. The submission API accepts session-authenticated POSTs and retains its permission-checked GET behavior.

Definition snapshots preserve the currently available schema at migration time; `is_legacy_baseline` and `legacy_baseline` history entries explicitly mark that provenance. Historical files are now retained until the organization's authorized deletion/retention process removes them; storage planning must include them. Model/manager immutability protects application writes, not a database administrator with direct SQL access. Backup/restore, retention policy administration, field-level authorization, offline phone capture, and production deployment acceptance remain open work.

## Verification for this stage

- Full Django suite: 151 tests passing, including 34 dataset/record/permission/mapping/concurrency tests and the existing 25 capture/history/migration tests. Older AI test fixtures now include the workspace membership required by the existing provider endpoints.
- Five contention/quota tests also pass using a file-backed SQLite database, in addition to the default test database. Record updates accept one expected version and concurrent retries create one record; capture checks cover last-place competition, simultaneous receipt retries, and the 100-response survey without order records.
- Dataset migrations applied after a second consistent SQLite backup (`backups/pre-datasets-20261025.sqlite3`). Existing row counts are unchanged, definitions/responses have baseline links, and foreign-key/integrity checks pass.
- An isolated browser database verified manual creation without AI, public submission, editing, preserved history, and quota feedback at desktop and 390px widths. Temporary review services were stopped afterward. Anonymous respondents and creator-less legacy forms render correctly.
- Dataset browser review in a disposable database verified visual schema creation, manual record entry, embedded form mapping, collection capture, response editing, explicit record selection, and version history; layouts were checked at 390px, 768px and desktop widths.
- Django checks, migration-drift checks, JavaScript syntax checks and diff whitespace checks pass. No production phone/TLS, installer, hosted service, voice, or backup-restore acceptance is implied by these checks.
