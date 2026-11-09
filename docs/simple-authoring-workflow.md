# Simple authoring workflow

OrgForms uses three everyday concepts:

- A **form** collects responses.
- A **section** keeps related questions and information together.
- The **Library** holds items people can choose and saved sections an organization reuses.

## Build a form

Start with a description, a local template (order, registration, appointment, feedback), or manual authoring. Templates work without an LLM.

The builder has Details (name, link, instructions), Content (sections and questions), and Settings (audience, status, response limits). One Add menu offers questions, choices, information, items, and saved sections. Written answers can use a single line or paragraph; choose-one questions can use visible choices or a dropdown through Appearance.

Each section can be renamed, reordered, nested, added to, removed, or saved to Library. Heading/border and layout controls live under Options. New sections use automatic responsive layout. Existing nested groups retain their stored IDs, layout, visibility and order.

## Reuse a section

Save to Library copies a section and its nested content. Add → Use a saved section inserts an independent editable copy with fresh IDs and remapped conditional field references. Editing or deleting a saved section does not change previously inserted fields.

Prebuilt question types are available in Add rather than duplicated as Library records. Ready-made section templates remain available under Saved sections. Internal model and route names remain compatible with existing UIElement data.

## Offer items

Library → Items supports create/edit popups with names, categories, prices, descriptions, photos, availability, stock, and structured choices with optional extra prices.

Add → Show items offers all organization items, a category, or specific items. New item lists use the organization Library; older catalog-scoped lists retain an explicit Existing catalog selection until changed. Availability, stock and prices are read from Library, checked again on submission, and snapshots are saved with the response. Stock is validated across selections; submission does not deduct or reserve stock.

Respondents select quantity/options; they do not enter item names, images or prices. A single list may contain items from multiple owned catalogs. Per-item catalog tax/discount rules are applied when calculating totals. Foreign-organization items and out-of-category selections are rejected by the server.

## Advanced records

Records & datasets are under Library → More. Form-to-record mapping and schema import remain under Settings. They are optional for a normal form.

## Implementation

The change uses Django templates and small JavaScript modules with the existing JSON schema. It does not require database migrations. Legacy field types, saved sections, grouped previews and public form rendering continue to work.

### Ready-made page sections

Library → Saved sections now includes a searchable catalog grouped into Page
content, Contact & requests, Orders & collection, and Events & feedback. Choose
Use section, customize the copy and fields, then save. In a form, use Add → Saved
section to insert a copy. Compose a welcome, service explanation, request fields,
FAQ and closing instructions into one collection page. Replace instructional
sample copy before publishing. Display sections do not collect answers; pickup
and appointment sections collect preferences rather than reserve availability.

Complete page starters combine existing sections for surveys, service enquiries,
reception and pickup orders. Each group keeps its own layout and unique field
IDs. Expand Preview content in the Library to inspect copy, required questions
and choices before opening the editor. Previews use a six-column CSS grid with
container queries: half/third widths expand when space permits and stack in
narrow containers. Library actions use wrapping Flexbox on mobile. No external
component runtime or CDN is required.
