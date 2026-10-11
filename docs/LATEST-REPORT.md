# Raport Rendiv — Checkpoint 6B.2G: validator MCP V1 exclusiv offline

Data: 2026-10-11

## Scop și modificări

A fost adăugat un validator strict pentru `structuredContent` MCP V1, păstrat independent de adaptorul Understory activ și de worker. Documentul 06 rămâne sursa contractuală; validatorul nu aprobă și nu implementează integrarea reală.

Fișiere modificate:

- `src/rendiv_api/mcp_contract_v1.py` — parser/validator strict, identificator de corelare distinct de operation ID, validare UUIDv7 și paths, duplicate-key detection pentru JSON brut, enums și invariants, erori statice fără conținutul respins; rezultat de policy fail-closed.
- `tests/test_mcp_contract_v1.py` — fixtures preluate din documentul 06, cazuri positive/negative, fake transport, răspunsuri duplicate/invalide/legacy, politică FIFO fake și interdicție de socket.
- `docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md` — precizează că validatorul este independent și neintegrat.
- `docs/DEVELOPMENT.md` și `docs/ARCHITECTURE.md` — progresul și separarea validatorului consemnate.
- `docs/LATEST-REPORT.md` — acest raport.

Nu s-au modificat adaptorul de producție, workerul, API, schema DB, migrații, autentificare sau deployment. Nu s-au accesat Docker, servicii, volume, secrete sau memorie.

## Comportament validat

- Request ID este corelat atât cu ID-ul JSON-RPC așteptat, cât și cu `request_id` din envelope; tipurile string/integer nu se pot substitui. Această corelare nu este idempotency.
- Operation ID trebuie să corespundă UUIDv7 lowercase, dar validatorul nu îi atribuie persistență ori deduplicare.
- Cheile duplicate sunt detectate la fiecare nivel când se parsează JSON brut. Pentru obiecte Python deja parsate, istoricul cheilor duplicate nu mai este disponibil.
- Paths absolute POSIX/Windows, traversal, delimitatori/backslash, NUL, newline, duplicate și ordine necanonică sunt respinse. Câmpurile și evidence se verifică strict.
- Validatorul nu interpretează textul MCP, `changed_paths` ori `isError` ca dovadă de succes. Toate outcome-urile acceptate produc în policy-ul curent `unknown/unknown`, FIFO blocat, fără retry. `rejected_before_write`, no-op maintain și `applied` nu primesc tranziții terminale noi.
- Răspunsurile legacy, lipsă, timeout, disconnect, necorelate, malformed sau ambigue sunt fail-closed. Mesajele erorilor validatorului nu reproduc valorile respinse.

## Teste și verificări

- Teste dedicate validatorului: **80 passed**.
- Suita completă: **221 passed** cu Python 3.12.3 și `PYTHONPATH=src`, în mediul virtual temporar existent.
- `pip check`: PASS (`No broken requirements found`).
- `git diff --check`: PASS.
- Linkuri locale din cele patru documente verificate: PASS.

Testele fake demonstrează parsing, validarea contractului propus și politica fail-closed simulată. Testele worker existente validează separat comportamentul workerului cu executori fictivi și SQLite temporar. Niciun test nu demonstrează contractul, buildul, efectele filesystem sau durability ale Understory runtime.

## Decizii și limitări rămase

Documentul V1 rămâne **PROPUS**, nu aprobat. Proveniența buildului Understory este neconfirmată. Semantica `succeeded/complete`, terminalizarea healthy no-op, garanția upstream zero-write pentru failed/none și suportul SDK pentru `structuredContent` rămân gate-uri operator. Journal durabil, idempotency/status, reconciliere și atomicitate/durability nu sunt implementate.

Nu începe checkpointul 6B.2H și nu porni integrarea reală.
