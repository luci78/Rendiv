# Raport Rendiv — Checkpoint 6B.2C: aplicarea deciziilor privind certitudinea efectelor

Data: 2026-10-11

## Subiect și domeniu

Au fost aplicate deciziile operatorului din checkpointul 6B.2C adaptorului Understory simulat și workerului local Rendiv. Auditul complet și matricea pentru cele trei operații sunt în `docs/design/04-EFFECT-CERTAINTY-AUDIT.md`.

Lucrul a fost local, cu transport fake/in-memory și SQLite temporar. Nu s-a folosit Docker, transport HTTP/MCP/stdio real, Understory, Pithagoras, Home Assistant, llama.cpp sau servicii active. Nu s-au accesat secrete.

## Decizii aplicate și efect

- `changed_paths` este succes raportat de Understory, nu dovadă de durabilitate și nici read-back Rendiv. Adaptorul îl lasă `unknown/unknown`, cu eveniment audit `worker_uncertain` și `reason_code=reported_success_unverified`. Jobul blochează FIFO; read-back-ul suplimentar nu este prezentat ca garanție tranzacțională.
- Workerul convertește `FAILED_NO_EFFECT` fără dovadă structurată și verificabilă în `unknown/unknown`, cu `reason_code=no_effect_unproven`. Simpla valoare enum nu produce `failed/none`. Interfața și contractul local nu conțin acum format sau verificator de proof; nicio dovadă ipotetică nu a fost introdusă.
- Healthy no-op pentru `memory_maintain` poate fi succes terminal `succeeded/complete` doar pe baza unui răspuns explicit, neambiguu și validabil care confirmă finalizarea fără modificări. Contractul local descrie calea no-op, dar nu oferă un marker textual stabil pentru adaptor. Răspunsul actual fără căi rămâne `unknown/unknown`, cu `reason_code=maintain_response_unverified`, și blochează FIFO.
- ID-ul UUID per apel JSON-RPC este păstrat numai pentru corelarea răspunsului, nu ca idempotency.

## Compatibilitate arhitecturală și impact

Modelul existent poate exprima aceste rezultate fără migrare sau schimbare API: starea `unknown` păstrează incertitudinea, iar `job_events.reason_code` păstrează cauza fără date de payload. Nu s-au schimbat schema, migrațiile, endpointurile publice, enum-ul stărilor sau Compose.

Impactul de disponibilitate este intenționat și verificat: succesul doar raportat, un no-op fără marker verificabil și orice `FAILED_NO_EFFECT` fără proof blochează coada; nu există retry automat. În consecință, integrarea reală va necesita un proces de reconciliere/operator pentru aceste rezultate, marker no-op validabil și format/verificator de dovadă no-effect înainte de a putea elibera gate-ul în mod sigur.

## Modificări

- `src/rendiv_api/understory_adapter.py`: `changed_paths` nu mai este clasificat drept succes complet; produce rezultat necunoscut cu reason code static. Răspunsul `memory_maintain` fără căi păstrează reason dedicat și nu este promovat la succes.
- `src/rendiv_api/worker.py`: rezultatul `FAILED_NO_EFFECT` fără proof devine unknown și blochează coada; codul motivului este validat dintr-o listă fixă înainte de audit.
- Teste adaptor, worker și audit: verifică matricea fake, job unknown și blocarea FIFO, reason code, lipsa retryului și execuția fără socket.
- Documentația `docs/design/04-EFFECT-CERTAINTY-AUDIT.md`, `docs/design/01-ARCHITECTURE.md`, `docs/design/01-DATABASE.md`, `docs/design/02-DECISIONS.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md` și acest raport au fost aliniate la deciziile aplicate.

## Verificări

- Suita completă în venv temporar Python 3.12, cu SQLite temporar și transport fake: **141 passed**.
- `pip check` în mediul temporar: PASS.
- `git diff --check`: PASS.
- Nu s-au modificat infrastructura, serviciile sau contractul Understory; nu s-a început integrarea reală.

## Limitări înainte de integrarea reală

Contractul Understory inspectat nu oferă receipt durabil, status lookup, idempotency, marker textual stabil pentru no-op ori dovadă verificabilă no-effect. `changed_paths` și read-back-ul nu garantează împreună atomicitate multi-fișier sau persistență durabilă după crash. Până la un contract/proces aprobat, rezultatele ambigue rămân unknown și opresc procesarea.

Checkpointul 6B.2C este finalizat în repository; nu începe integrarea reală sau etapa următoare.
