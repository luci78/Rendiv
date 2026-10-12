# Raport Rendiv — Checkpoint 6B.2J: audit read-only Understory și plan MCP V1

Data: 2026-10-12

## Domeniu și proveniență

Auditul a acoperit checkout-ul Rendiv `/home/luci78/Rendiv-project` și sursa locală Understory `/home/luci78/ai-stack/understory`. La preflight, Rendiv era curat pe `main` la `05945eb65f115fbc683d48b39bf2bf2c45f78e84`, iar Understory era curat pe `main` la commitul exact `f6c342332f390a444a8669636b1cf8f9669dd995`. Concluziile despre implementare se referă numai la acel checkout local. Identitatea buildului Understory activ nu este legată verificabil de commit.

S-au citit documentația cerută și codul local relevant pentru MCP, agent, write tools, KnowledgeBase, bundle, indexer, logger, lint și trace. Nu s-au accesat servicii, API-uri, MCP, Docker, configurații cu secrete, baze sau conținutul memoriei. Nu s-au rulat teste sau instalări.

## Constatări confirmate în codul local

- **Răspuns MCP:** `packages/server/src/mcp/server.ts:67-93` construiește rezultate text-only; failed setează `isError: true`. Handlerele `memory_add` (`:95-127`), `memory_update` (`:129-144`) și `memory_maintain` (`:184-239`) nu emit `structuredContent` și nu propagă `extra.requestId`. SDK 1.29.0 poate furniza `extra.requestId` handlerului conform probei documentate în [08](design/08-MCP-SDK-129-RUNTIME-TEST.md), dar integrarea nu există în sursa inspectată.
- **memory_add/update:** `packages/core/src/agent/agent.ts:145-188` returnează `ok` la încheierea generatorului chiar și cu lista de paths goală. `packages/core/src/agent/tools.ts:85-159` adaugă path-ul în `filesChanged` numai după ce apelul KB revine. Un concept poate fi scris înainte ca un pas ulterior să eșueze, iar path-ul lui să nu fie înregistrat. Prin urmare paths goale sau eșecul nu demonstrează zero efecte.
- **Scrieri și efecte secundare:** `packages/core/src/okf/bundle.ts:101-159` folosește scrieri/unlink filesystem directe pentru concepte. `packages/core/src/okf/knowledge-base.ts:76-139` serializează promisiunile în memoria unei instanțe și apoi efectuează prune, regenerare index, append/update log și Git autocommit opțional. Indexerul și loggerul fac operații filesystem distincte (`indexer.ts:12-77`, `logger.ts:12-53`). Traseul inspectat nu arată staging+rename pentru o operație, rollback multi-fișier sau fsync explicit. Git autocommit e best-effort și configurația runtime nu a fost inspectată.
- **memory_maintain:** `packages/server/src/mcp/server.ts:192-203` verifică lint și, pe ramura healthy, răspunde înainte de `runMutation`; `packages/core/src/okf/lint.ts:28-45` construiește raportul din scanare. Aceasta confirmă ramura fără mutație în checkout-ul local. Nu produce însă răspuns V1 structurat și nu dovedește versiunea runtime activă.
- **Jurnal și reluare:** traseul inspectat nu oferă operation journal durabil, idempotency pentru apelul logic, status lookup sau recovery/rollback al efectelor. Trace-ul din `packages/core/src/agent/trace.ts:123-149` este best-effort/telemetrie, nu ledger de operații. Timeout, deconectare sau crash pot lăsa efecte parțiale; codul examinat nu permite concluzia că agentul a fost oprit.
- **Compatibilitate V1:** path-urile canonice din bundle au slash inițial (`bundle.ts:22-55`), pe când contractul V1 cere căi POSIX relative fără slash inițial (`docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md:78`; validatorul Rendiv `src/rendiv_api/mcp_contract_v1.py:119-130`). Este necesară normalizare și validare înainte de emitere. Există și conflictul explicit dintre `isError: true` al failed curent și regula V1 `unknown` cu `isError: false` (`06-UNDERSTORY-MCP-CONTRACT-V1.md:294`); decizia de protocol rămâne pendinte.

## Matricea efectelor și politica Rendiv

Documentul [09 — planul minim de implementare](design/09-UNDERSTORY-V1-IMPLEMENTATION-PLAN.md) conține matrice separată pentru `memory_add`, `memory_update` și `memory_maintain`, pentru `applied`, `no_op`, `partial`, `rejected_before_write` și `unknown`, cu dovezile actuale și limitele lor.

Politica nu se schimbă: toate rezultatele rămân `unknown/unknown`, FIFO blocat și fără retry automat. `applied` și `changed_paths` sunt raport upstream, nu efect complet/durabil demonstrat. `no_op` pentru `memory_maintain` identifică o ramură locală fără mutație, dar nu primește automat `succeeded/complete`. `failed`, `isError`, excepția, timeoutul, lipsa răspunsului ori lista goală nu justifică `failed/none`; `rejected_before_write` necesită o garanție upstream verificabilă că niciun write nu a început.

## Plan minim și decizii

Planul din documentul 09 separă:

1. **Protocol fără schimbarea persistenței:** helper MCP comun în `packages/server/src/mcp/server.ts`, echo exact al `extra.requestId`, `structuredContent` V1 alături de text, operation ID per încercare fără pretenție de durabilitate, normalizarea căilor și teste pentru erori după fiecare boundary de scriere. Rendiv ar necesita separat decodarea structuredContent, validare fail-closed și test fake end-to-end.
2. **Necesită arhitectură persistentă distinctă:** journal append-only, idempotency stabilă, status/replay după restart, transaction/staging pentru scrieri multi-fișier și fencing pentru operații care ar putea continua după timeout. Un envelope MCP singur nu furnizează aceste garanții.
3. **Imposibil de demonstrat acum:** lipsa efectului după eroare/timeout; exhaustivitatea paths; semantic-complete, atomicitate sau durability; încetarea agentului după disconnect; deduplicare/reconciliere după restart; proveniența buildului activ.

Înainte de orice implementare rămân pendinte aprobarea contractului V1 și conflictul `isError`, politica de normalizare a paths, tranzițiile terminale și orice lucrare de journal/idempotency/transaction. Documentul 09 nu modifică și nu aprobă contractul V1.

## Fișiere și verificări

Au fost modificate exclusiv documentația cerută:

- `docs/design/09-UNDERSTORY-V1-IMPLEMENTATION-PLAN.md` — trasee cu referințe la surse, matrici per operație, limite și plan în secțiunile A/B/C.
- `docs/DEVELOPMENT.md` — progresul 6B.2J și avertismentul că V1 rămâne propus.
- `docs/LATEST-REPORT.md` — acest raport, înlocuind raportul anterior.

Verificările cerute sunt `git diff --check` și linkuri Markdown locale. Nu s-au rulat teste, servicii sau operații externe.

## Publicare și limite

Instrucțiunea checkpointului interzice accesul la rețea. În consecință nu se execută push, fetch sau altă operație de rețea; dacă verificările trec, se poate crea numai commit local pentru cele trei documente. Commit local creat numai pentru cele trei documente. Worktree-ul este curat; `HEAD` este cu un commit înaintea `origin/main` (`05945eb65f115fbc683d48b39bf2bf2c45f78e84`). Prin interdicția de rețea, push-ul nu a fost executat și `HEAD=origin/main` nu este confirmat.

Nu începe checkpointul 6B.2K și nu începe integrarea reală.
