# OrgForms

OrgForms is a Django application for organization workspaces, dynamic forms, public submissions, and AI-assisted work. SQLite stores application data. Ollama and optional cloud APIs provide inference.

The primary product plan is [Universal Platform Architecture v3](docs/universal-platform-architecture-v3.md), with [Local and Cloud Architecture](docs/local-cloud-architecture.md) as deployment guidance. [Implementation status](docs/implementation-status.md) distinguishes delivered dataset/capture features from proposed workflows, wallet, installer, and cloud capabilities.

## Project structure

`orgforms/` contains settings and top-level routing. The six Django apps are:

| App | Owns |
| --- | --- |
| `accounts` | Authentication, personal profiles, portfolios, personal documents |
| `organizations` | Workspaces, dashboard, categories, memberships, departments, organization documents |
| `forms` | Builder, field library, sharing, public forms, submissions, attachments, catalogs, item selections |
| `datasets` | Reusable schemas, records/revisions, independent read/write/lookup grants, collection mappings |
| `chat` | AI Hub, conversations, messages, memory, permission-scoped insights |
| `ai_gateway` | AI settings, model profiles, Ollama/cloud adapters, classification |

Shared layouts and browser assets live in `templates/` and `static/`. Feature-specific templates and assets live in their app. There are no `org`, `api`, or `restaurant` apps. Restaurant and cafe are organization categories; item cards and ratings are reusable fields for every category.

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
DJANGO_DEBUG=true python manage.py runserver 127.0.0.1:8000
```

For a database created before the five-app reorganization, **use the import procedure below instead of running these new migrations on the old database**.

### Windows: double-click to start the prototype

After one-time setup, double-click **Start OrgForms.bat**. It starts Django, waits
until the homepage responds, and opens the app in the default browser. Keep the
server window open; press **Ctrl+C** to stop. Closing the browser does not stop
the server. A second launch reports that the port is already in use.

You can right-click the batch file and create a desktop shortcut pointing to it;
keep the actual batch file in the project folder. This is a manual launcher, not
a Windows boot service or a standalone installer.

One-time setup by the person preparing the Windows computer, using Python 3.12+:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
```

Configure `.env`, then initialize a **new** installation with
`.venv\Scripts\python.exe manage.py migrate`. For an older database, follow the
legacy import instructions instead. A Windows virtual environment must be
created on Windows; do not copy the macOS/Linux `.venv` folder.

The launcher uses development mode on `127.0.0.1:8000` for this computer only. It
does not modify `.env`, install packages, or run migrations automatically. It
does not enable phone/Wi-Fi access or internet exposure. Those deployment modes
require separate configuration; do not port-forward this development launcher.
The production installer remains a later step.

| Page | URL |
| --- | --- |
| Home | `/` |
| Signup / login | `/accounts/signup/`, `/accounts/login/` |
| Personal profile | `/accounts/profile/` |
| Dashboard | `/dashboard/` |
| Organization | `/org/<organization-slug>/` |
| People / settings | `/org/<organization-slug>/people/`, `/org/<organization-slug>/settings/` |
| Submissions | `/org/<organization-slug>/submissions/` |
| Form builder | `/org/<organization-slug>/forms/new/` |
| Public form | `/org/<organization-slug>/<form-slug>/` |
| Item catalog | `/org/<organization-slug>/menu/` |
| AI Hub | `/_chat/?org=<organization-slug>` |

Existing URLs and public links are retained. The legacy menu URL now manages a reusable item catalog.

## Forms and catalogs

### Versioned collection capture

Form definitions now have immutable `CollectionRevision` snapshots. Responses reference the definition used to capture them; edits retain earlier `SubmissionRevision` snapshots, including private attachment references and item-price snapshots. Response lists and CSV exports identify both definition revision and response version. Migration creates a marked legacy baseline for existing data; it cannot recover schemas overwritten before revision tracking existed.

Create forms manually or use optional AI suggestions. The same builder and capture service work across organization categories. Admins/managers can set an optional **Response limit** (for example, 100 survey responses); new captures consume places, while edits and retries do not. Current membership/audience rules are checked on every capture and receipt replay.

Public browser forms provide revision IDs, optimistic edit versions, and request IDs automatically. Session-authenticated API clients may POST to `/api/forms/<form-id>/submissions/` with:

```json
{
  "revision_id": "<definition UUID from the form API>",
  "request_id": "<unique key for this capture attempt, reused for retries>",
  "data": {"name": "Asha"}
}
```

`Idempotency-Key` may supply the request key instead. A committed retry returns the same receipt; a reused key with different input returns 409. Edits include the returned `edit_token` and `expected_version` and must retain the same authenticated/session identity. New captures with stale definition IDs conflict; edits validate against their original definition. Legacy clients can omit these controls for compatibility but cannot receive their concurrency/retry guarantees. Database failures return 503 without a successful receipt.

Current-authorized workspace members can read `/api/forms/<form-id>/revisions/` and `/api/submissions/<submission-id>/history/`. A public response link grants no results/history access. Answers use the supported `orgforms-fields-v1` schema format, not arbitrary JSON Schema. Catalog price/ownership checks and file validation run on the server for browser and API capture without an AI dependency.

Run `python manage.py migrate` after updating an existing five-app installation. Historical definitions/files are retained; this migration does not move personal files to a device wallet. Forms with responses must be archived or duplicated rather than transferred to another organization.

### Reusable datasets and records

The **Data** workspace tab separates reusable business records from collection responses. An organization admin or manager can create a dataset, edit its fields visually or as `orgforms-fields-v1` JSON, choose one field as the approved lookup label, and grant members independent **Read**, **Write**, and **Lookup** permissions. Admins/managers retain all three. A form audience does not grant dataset results access.

In the form builder, select **Record destination**, choose the dataset schema version, and explicitly map collection fields to compatible dataset field IDs. One collection writes to at most one dataset; several collections may share that destination. Leaving it at **Responses only** preserves standalone form behavior. Existing forms and historical submissions are not automatically reinterpreted as dataset records.

Each accepted mapped response commits the submission, current record, immutable record revision, and retry receipt in one transaction. A normal response creates a new record, even when its name/email matches another response. To update an existing record, open its Data detail page and select a connected collection, or use its record ID and expected version through the API. Conflicting versions and outdated schema mappings return a conflict before accepting the capture. Existing record values outside the mapping remain unchanged.

Dataset schema changes create immutable versions. They do not rewrite earlier records or silently upgrade active collection mappings. Review and republish each collection against the new dataset schema. The Data screens show captured schema labels, current values, schema history, record history, search, and CSV export. `record_reference` fields use an explicitly configured same-organization lookup dataset; lookup access exposes only IDs and the configured label. Files and catalog selection remain collection capabilities. No generic dataset data is automatically added to AI context or exported to cloud services.

See [dataset commands and a walkthrough](docs/dataset-foundation.md) for permissions, endpoints, concurrency rules, and current limits. Apply migrations with `python manage.py migrate`; they add dataset tables and nullable collection/response links.

### Reusable item catalogs

Each `item_cards` field has an organization-owned `catalog_id`. If omitted, the organization's default catalog is assigned. Multiple fields can use separate catalogs through the advanced form schema. The existing catalog-management page edits the default catalog.

Responses accept `catalog_item_id` or the historical `menu_item_id`, plus a whole quantity from 1 to 50. Prices come from the server. Submissions retain item names and price snapshots, with quantities and totals recorded in `forms.ItemSelection` and `forms.SelectionLine`. Historical discounts, tax rules, IDs, and processing/payment states are preserved. The existing tax calculation applies tax to subtotal before discount.

Historical `restaurant_order`, `items_field_id`, and `order_id` values remain readable. An `order_id` stored in a submission refers to a migrated item selection. Respondents cannot attach arbitrary historical selections. Existing selections that have started processing or payment cannot be edited.

Organization admins can reassign a form to another admin or manager in the same organization. Cross-organization form moves are unavailable with the one-organization-per-account model; public and individually shared forms remain accessible according to their audience settings.

## Access and files

Workspaces require organization membership. Admins and managers manage organization forms; members only see forms they may access. Form audiences are public links, organization members, or selected accounts/departments. Public form access never grants workspace, file, chat, or response-list access. Installation API keys do not bypass organization membership.

Authenticated application APIs use Django sessions; no installation API key is required.

Signup uses Django's existing user model and email-as-login convention. An installation administrator can claim an unowned legacy organization with:

```bash
python manage.py claim_legacy_organization <organization-slug> <existing-account-email>
```

At signup, choose a personal account, an account to create an organization, or an
account to join one. Creating an organization continues directly to the existing
AI-assisted setup wizard; joining requires an organization admin to add
the account's email. Each organization account belongs to at most one
organization; separate organizations and personal use require separate accounts
and email addresses. Organization owners can transfer ownership to another
member in organization settings. The personal portfolio and files belong to
personal accounts.

Existing databases with accounts in multiple organizations must be backed up
and their conflicting memberships resolved before migration. The migration
stops rather than silently deleting memberships. Legacy imports also reject a
source with conflicting memberships; resolve those in a copy before import.

Uploaded files remain private under `MEDIA_ROOT`. Organization and personal documents and submission attachments are served by permission-checked endpoints. Do not expose a public `/media/` mapping. Back up both SQLite and the media directory.

## AI

The prompt model menu lists all available local models in one vertical column, with **Default** at the top. There are no model-family flyouts.

The Ollama panel’s **Context window** selector sets the shared token window for input and reply (`num_ctx`). Auto normally uses 4,096 tokens for discovered local models; choices are bounded by the model/profile and server limit. The preference is stored per organization/model in this browser and applies to both chat and starter suggestions. A larger window allows more context but uses more memory; it does not itself include more data sources.

The three starter questions use a temporary request with one instruction and the selected organization’s name. The context switches optionally add visible submission/item counts and totals, saved organization profile details, and up to three matching document excerpts (at most 1,800 characters each). There is no earlier chat, saved memory, personal portfolio, attachment, full form schema, member directory or dataset-record retrieval in the starter request. The instruction stays intact when earlier-chat sharing is off. **Context → About the three suggestions** explains this in the UI. With Context None, suggestions are general questions based on the name only. Selection of a cloud provider also applies to this request; temporary means unsaved conversation, not a different inference destination.

AI Hub combines local runtime controls under one Ollama header button: start/stop, live running models from `ollama ps`, an installed-model selector for the organization default, and the context-window preference. Running models show memory, processor and active context size; raw command output stays collapsed. Save changes the organization default through the existing permission-checked AI configuration API. Refresh updates status, installed models and running processes without background polling.

These controls require a loopback browser connection to Django and a local HTTP `OLLAMA_BASE_URL`. Current organization members can inspect status and running models; an organization admin, manager or installation superuser can start/stop the shared server from that computer. Stopping interrupts local AI across organizations. A server launched outside OrgForms is reported as externally managed and must be stopped from its app/service. Remote services are never terminated. Commands use fixed argument lists, timeouts and CSRF-protected requests, with no browser-supplied shell commands.

The server’s verified PID/start identity and log live under ignored `.runtime/ollama/`, so control survives Django reloads. The child binds loopback and remains running until explicitly stopped, independently of the Django development server. CLI discovery uses the Django process PATH. Local lifecycle/ps was verified on macOS; Windows/Linux service packaging is not established by this development control. Command meanings follow the [Ollama CLI reference](https://docs.ollama.com/cli).

All model calls use `ai_gateway`. Configure `OLLAMA_BASE_URL` and `OLLAMA_DEFAULT_MODEL` for local inference. Cloud adapters support OpenAI-compatible APIs using server-side `CLOUD_API_KEY` and `CLOUD_API_BASE_URL`. AI settings are independent of catalogs and are available at `/api/ai/configuration/`, scoped with `X-Organization` or `?org=`; only managers/admins may change their organization's settings. Shared model profiles require an installation superuser to modify.

### M1 Air local model reference

These are local measurements supplied by the project owner. They are useful for choosing a model on this MacBook Air; performance and memory usage can vary with context length, Ollama version, other running apps, and model quantization. “Think used” records the setting during the speed run. “Think available” records whether the published Ollama model family exposes thinking support; the AI Hub’s live toggle uses the capability reported by the installed Ollama model (or its configured model profile).

| Model | Think used | Think available | Active memory (Activity Monitor) | Speed (eval rate) | File size |
| --- | --- | --- | ---: | ---: | ---: |
| `gemma3:1b` | Off | No | 158 MB | 52.87 tok/s | 815 MB |
| `llama3.2:1b` | Off | No | 230 MB | 42.58 tok/s | 1.3 GB |
| `qwen3.5:0.8b` | Off | Yes | 600 MB | 41.92 tok/s | 1.32 GB |
| `qwen3.5:2b` | Off | Yes | 860 MB | 25.88 tok/s | 2.7 GB |
| `gemma4:e2b` | Off | Yes | 3.20 GB | 31.43 tok/s | 7.2 GB |
| `qwen3.5:4b` | Off | Yes | 4.17 GB | 17.61 tok/s | 3.4 GB |

Ollama lists `qwen3.5:0.8b` at 1.2–1.3 GB; the installed model manifest totals 1.322 GB, rounded to 1.32 GB above. The 600 MB figure is the recorded active memory during inference. [Ollama model tags](https://ollama.com/library/qwen3.5/tags)

Ollama publishes thinking capability for the Qwen 3.5 and Gemma 4 families; Gemma 3 and Llama 3.2 do not list that capability on their model pages ([Qwen 3.5](https://ollama.com/library/qwen3.5), [Gemma 4](https://ollama.com/library/gemma4), [Gemma 3](https://ollama.com/library/gemma3), [Llama 3.2](https://ollama.com/library/llama3.2)). The installed local model metadata is authoritative for the app toggle.

Quick selection guide from these measurements:

| Need | Suggested model | Why |
| --- | --- | --- |
| Fast replies and lowest observed memory | `gemma3:1b` | Fastest measured at 52.87 tok/s and 158 MB active memory. |
| Lightweight general chat | `llama3.2:1b` | 42.58 tok/s at 230 MB active memory. |
| Compact Qwen option | `qwen3.5:0.8b` | 41.92 tok/s at 600 MB active memory, with Think off during the run. |
| Try Think mode without the largest measured footprint | `qwen3.5:2b` | Think capable, 25.88 tok/s, and 860 MB active memory. |
| More capable local reasoning | `gemma4:e2b` | Think capable and measured at 31.43 tok/s; it used 3.20 GB active memory. |
| Larger Qwen option | `qwen3.5:4b` | Think capable, with the slowest measured speed and highest active memory in this set. |

To install these Ollama models, run `ollama pull <model-name>` for each desired tag. Start Ollama, set `OLLAMA_DEFAULT_MODEL=<model-name>` in `.env` if you want a default, then run OrgForms. The AI Hub discovers installed models from `/api/models/`, lets you select one for a message, and shows this M1 Air reference under **Model guide**.

Organization APIs remain at `/api/orgs/`, form APIs at `/api/forms/`, and chat APIs at `/api/chat/`. Model discovery remains at `/api/models/`. Chat retrieval uses permission-scoped form/submission summaries and uploaded UTF-8 text, Markdown, and CSV documents; it never runs model-generated SQL. Unlinked historical item selections are excluded from chat summaries.

The local System 1 classifier handles public quick-fill without sending respondent text to a third party. Authenticated classification integrations can optionally use `JEV_API_URL` / `JEV_API_KEY` or `SCALEDOWN_API_URL` / `SCALEDOWN_API_KEY`.

## Import an older database

Stop the development server and other writers. Make a SQLite backup, preserve the existing code version, and copy `media/` before beginning. Run the following with an absolute path to a **new, nonexistent** destination database:

```bash
DJANGO_DB_NAME=/absolute/path/orgforms-next.sqlite3 python manage.py migrate --noinput
DJANGO_DB_NAME=/absolute/path/orgforms-next.sqlite3 python manage.py import_legacy_orgforms --source /absolute/path/legacy-backup.sqlite3
```

The importer reads the source in a consistent, read-only transaction and refuses a nonempty destination. It preserves retained records and timestamps, binds historical item selections to submissions, separates catalogs from AI settings, remaps model permissions, and verifies copied values, counts, and SQLite integrity before committing. Failed imports roll back. The source must include the latest historical migrations through submission attachments and chat message references.

After successful import and checks, replace `db.sqlite3` with the new file while all writers remain stopped, then restart the server. Keep the original database and original code together for rollback. Do not run the old code against the new schema. Removed payment, kitchen, inventory, and operations data remains in the archived original database.


## Checks and deployment

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --noinput
```

For deployment, configure a unique `DJANGO_SECRET_KEY`, exact `DJANGO_ALLOWED_HOSTS`, `DJANGO_DEBUG=false`, HTTPS, and collected static files. Do not expose the development server or an unauthenticated Ollama port to the internet.

### Local AI creation

Dashboard → **New organization** can draft organization details and an optional unpublished first form from a text prompt. **Create form** opens a compact text prompt and uses the organization’s default local Ollama model automatically. Every proposal is reviewed before saving. Voice recording, audio uploads, and Whisper transcription have been removed.

Start Ollama from AI Hub and install a supported text/chat model. See [local AI creation](docs/local-ai-creation.md) for model behavior, context disclosure, and authorization.
