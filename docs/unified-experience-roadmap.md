# Unified collection experiences

Updated 4 November 2026. Complements architecture v3; this is not a claim that all workflows are implemented.

An organization owns collections. A form is a configurable single-page experience over a versioned collection contract. Library supplies reusable fields and sections; inserting a section makes an independent copy with fresh field IDs. Industry examples are configurations, never separate tenant models.

## Available building blocks

Text, numbers, choices, dates/times, files, ratings, quantities, headings, instructions, images, item cards and nested sections compose the page. Existing layout and visibility settings control presentation. Library starters now include surveys, journey requests and reception check-in alongside contact, delivery, appointments and menu orders. They capture requests; a booking is not confirmed merely because a response was saved.

## Next implementation sequence

1. A unified Library browser in the builder: search fields and saved sections, preview their content and responsive layout, insert, then edit in place. Preserve existing IDs when editing and generate new IDs only when copying. Keep manual creation usable without AI.
2. A page composition model using the existing group schema: explicit stack/grid layouts, bounded nesting, reusable content blocks and consistent field properties. Validate the same schema for browser and API capture. Do not execute user-authored scripts.
3. Optional workflow capabilities: statuses, assigned queues, authorized transitions and append-only events. A kitchen queue or hospital reception staff screen reads permission-scoped records; it must not expose all responses because someone can submit a form.
4. Booking capability: available resources and time slots, atomic reservations, expiry, cancellation and idempotent confirmation. A cab journey request additionally needs dispatch/driver assignment; pickup/destination fields alone do not provide dispatch.
5. Safe embedding: deliberate publication, permitted origins, private attachment handling, consent and scoped public projections. Existing internal editor iframes are not public embeddable form authorization.

## Acceptance

Demonstrate survey, equipment request, reception intake and item ordering using the same builder and capture pipeline. Verify mobile and keyboard use, theme consistency, required and conditional validation, retry safety, history, cross-organization isolation and manual fallback. Then test each enabled operational capability separately. “Any UI” means composition from supported validated blocks, not arbitrary executable pages or automatic domain compliance.
