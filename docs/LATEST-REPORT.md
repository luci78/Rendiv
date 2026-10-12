# Raport Rendiv — Checkpoint 6B.2K-A: finalizare documentară MCP V1

Data: 2026-10-12

## Domeniu și starea inițială

Rendiv era curat pe `main` la `3d18d7ce74255ff8b881339c8d342b7bde689f88`. Checkout-ul Understory consultat read-only era curat la `f6c342332f390a444a8669636b1cf8f9669dd995`; nu a fost modificat. Nu s-au accesat servicii, Docker, MCP, LLM, memorie, volume sau credentiale.

Au fost revizuite instrucțiunile Rendiv și documentele de contract/compatibilitate/plan, precum și sursa locală necesară pentru confirmarea fluxurilor existente. Subsecțiunea `isError` din codul validatorului Rendiv a fost verificată read-only. Nu s-au rulat teste runtime sau instalări.

## Decizii documentate ca aprobate pentru implementare offline

- `MutationOutcome.failed` păstrează textul și `isError=true` legacy. Un `structuredContent` V1 `unknown` poate coexista cu acest flag; `isError` nu demonstrează lipsa efectelor.
- `changed_paths` V1 sunt relative POSIX fără slash inițial. Serializarea poate elimina exact un sentinel numai de la un path bundle-relative canonic confirmat; nu schimbă paths interne sau textul legacy și nu pretinde că dovedește persistența.
- Un rezultat mutativ nu este `applied` fără proof durabil. V1 are `durability=not_asserted` și nu poate transporta acel proof, astfel sursa actuală trebuie să emită `unknown` pentru mutațiile insufficiently demonstrated.
- `partial` necesită confirmarea explicită a sursei. `rejected_before_write` cere dovadă verificabilă că zero scrieri au început; sursa existentă nu oferă această dovadă și nu trebuie să emită acel outcome.
- `memory_maintain no_op` este permis numai pe ramura healthy demonstrabilă care revine înaintea agentului și a mutațiilor. Acest envelope nu terminalizează singur un job Rendiv.
- Timeout, disconnect, crash și rezultate ambigue rămân unknown, fără retry. `request_id` corelează un exchange; nu este idempotency key. `structuredContent` nu este receipt durabil sau garanție exactly-once.

Aprobarea este exclusiv pentru implementare/testare offline. Nu aprobă producția, deploymentul, `succeeded/complete`, `failed/none`, un retry, sau deblocarea FIFO.

## Contradicții corectate și limitări identificate

Contractul 06 cerea anterior `isError=false` pentru outcome `unknown`, în conflict cu păstrarea compatibilității legacy la `MutationOutcome.failed`. Documentația permite acum explicit combinația V1 `unknown` plus `isError=true`, fără a o folosi ca probă de no-effect. Exemplele 1 și 2 nu mai prezintă `applied` pentru rezultate fără dovadă durabilă. Regulile paths, tabelele de rezultate, criteriile și planul 09 au fost aliniate.

**Mismatch de integrare cunoscut:** validatorul actual `src/rendiv_api/mcp_contract_v1.py:315-316` respinge `isError=true` dacă outcome-ul nu este `rejected_before_write`. Codul nu a fost modificat la acest checkpoint; alinierea validatorului este necesară separat înainte de integrarea reală. Nu este un blocaj pentru actualizarea documentară.

V1 nu are mecanism verificabil de durable applied sau proof independent de zero writes. Prin urmare outcome-urile respective nu sunt emise de sursa actuală. Identitatea/provenance buildului Understory activ rămâne neconfirmată. Journal, idempotency, status, recovery, tranzacții, atomicitate și exactly-once sunt în afara acestui contract/checkpoint.

## Fișiere modificate

- `docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md`
- `docs/design/09-UNDERSTORY-V1-IMPLEMENTATION-PLAN.md`
- `docs/DEVELOPMENT.md`
- `docs/LATEST-REPORT.md`

Nu s-au modificat surse Python/TypeScript, teste, migrații, Docker/Compose ori fișiere din Understory.

## Verificări

Se execută `git diff --check`, revizuirea exactă a listei fișierelor și o verificare textuală a contradicțiilor cunoscute. Nu se execută teste, servicii sau verificări runtime, conform scope-ului.

Contractul este țintă aprobată numai pentru implementare offline. Nu începe implementarea 6B.2K-B sau integrarea reală.
