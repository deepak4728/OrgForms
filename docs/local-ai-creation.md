# Local organization and form drafting

Updated 28 October 2026. These are reviewed text-based creation proposals, not autonomous commands.

## Use

- Dashboard → **New organization**: describe the organization in text. Choose **Draft organization**, review the editable details and optional first-form questions, then create it.
- Organization → **Create form**: describe the form in a short prompt, generate a draft, review the fields, then save it in the builder. The organization’s default Ollama model is used automatically.

The prompt dialog is intentionally limited to the request, a draft action, and manual builder entry. Microphone recording, audio uploads, browser speech recognition, and Whisper transcription are not supported.

## Runtime and context

Start Ollama in AI Hub and install a supported text/chat model. Organization creation lists installed models; form creation uses the organization’s current default. The drafting endpoints call Ollama directly regardless of cloud provider configuration. They inspect the selected model’s advertised capabilities and enable thinking when supported. If a model spends its initial budget on reasoning without returning JSON, a second local call uses its temporary planning output to produce the structured draft. The planning output is neither returned to the browser nor saved. There is no cloud fallback or template substitution on failure.

Organization drafts receive only the submitted prompt and a fixed output contract. Form drafts receive the prompt, workspace name/purpose/short description, permitted organization catalog names and available item names, and, when suggesting additions, the current question descriptions supplied by the editor. Catalog item cards use the selected catalog’s available items; the AI does not create catalog items. Drafts receive no chat history, account memory, private documents, submissions, or dataset records.

Authentication, session CSRF checks and chat throttling apply to creation endpoints. Form drafting requires an admin/manager or an explicitly authorized editor for additional questions. All generated structures pass server-side type/schema and length validation. Submitted initial-form JSON is revalidated at the write boundary; organization, owner membership and initial draft commit in one transaction. Model proposals cannot assign members, permissions, dataset bindings or organization ownership.

Dictation-based response capture, durable AI jobs, cloud inference consent and arbitrary voice control remain outside the current implementation.
