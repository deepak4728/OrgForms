# Library-backed menu ordering

The `item_cards` form field now renders a searchable menu with category filters, list/grid views, an item customization dialog and a sticky cart. Existing forms using this field receive the component automatically. Display content is supplied by the organization's Library; respondents supply quantity, option choices and optional item instructions.

## Set up

1. Add Library items with a category, base price, optional HTTPS image and availability/stock.
2. Add choice groups such as Size or Spice. Choices remain single-selection per group. An optional price addition can be configured for a named choice, e.g. `Large = 30`. The base price plus each selected addition gives the unit price. Use distinct items for variants requiring independent stock.
3. Insert Library item cards into a form and choose the relevant catalog/items.
4. Respondents add configurations to their cart, review/edit/remove them, then submit the containing form.

A separate sample catalog and `/org/open-shelf/ordering-demo/` form were created locally for review. These contain explicitly marked sample items, not a real restaurant menu.

## Server authority

The submitted line contains an item ID, whole quantity, selected choices and notes (up to 500 characters). Client-supplied prices are ignored. Django validates tenant/catalog scope, availability, allowed choices, required choices and aggregate quantity across configurations. It computes the unit price from current Library values and snapshots it in SelectionLine. Item instructions are stored in SelectionLine.notes. Existing catalog tax/discount rules calculate the persisted selection totals; the browser displays an items subtotal, not a final payable amount.

## Current boundaries

- Availability refreshes when the form loads and is checked again at submission. No live push, stock reservation or stock deduction is implemented.
- Cart state is page-local and resets on reload or “Submit another response.”
- Extras use single-choice groups; multi-select priced add-ons and variant-specific inventory are not implemented.
- Payment, kitchen routing, customer order tracking and bill requests are not part of this slice.
- Local AI drafts choices; base prices and price additions require creator review/entry.
