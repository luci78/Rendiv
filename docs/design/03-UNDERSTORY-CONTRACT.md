# Understory — contract tehnic observat în sursa locală

- **Etapă:** 6B.2A — investigare read-only
- **Data:** 2026-10-11
- **Checkout:** `/home/luci78/ai-stack/understory`, commit `f6c342332f390a444a8669636b1cf8f9669dd995`; `git status --short` era curat.
- **Dovadă:** citire statică a codului local. Nu s-au apelat servicii, endpointuri sau tool-uri MCP; nu s-au citit fișiere `.env` sau valori de credentiale.

## Rezumat și limită runtime

Checkout-ul definește tool-uri MCP `memory_add`, `memory_update` și `memory_maintain`. Primele două apelează un agent LLM cu tool-uri interne de citire/scriere; `memory_maintain` verifică graful și poate delega reparația agentului. Persistența este realizată în fișiere Markdown, indexuri și log.

Acestea sunt fapte despre commitul local inspectat, nu despre serviciul activ. Nu am verificat dacă acest commit corespunde deploymentului, ce transport/client este conectat, dacă autentificarea este activă, ce bundle este montat sau valorile runtime ale timeouturilor.

## Schemele MCP confirmate în cod

Sursa: `packages/server/src/mcp/server.ts`, `buildMcpServer`, `server.registerTool`.

### `memory_add`

| Câmp | Schema Zod | Limitări observate |
|---|---|---|
| `content` | `z.string()`, obligatoriu | Fără limită `min`/lungime declarată aici. |
| `suggested_path` | `z.string().optional()` | Fără validare de path în schema MCP; este transmis agentului drept indiciu. |

Handlerul înfășoară conținutul într-o instrucțiune pentru agent: caută concepte asociate, completează un concept existent când potrivit și creează unul nou când este distinct. Nu este garantat de cod că sugestia de path va fi folosită.

### `memory_update`

| Câmp | Schema Zod | Limitări observate |
|---|---|---|
| `instruction` | `z.string()`, obligatoriu | Fără limită `min`/lungime declarată. |

Handlerul transmite textul la `runMutation`. Argumentele de editare efective sunt apeluri separate ale tool-urilor agentului, nu câmpuri directe ale acestui tool.

### `memory_maintain`

Schema este obiect gol `{}`. Handlerul rulează `kb.lint()`. Dacă graful este sănătos, întoarce un mesaj no-op fără a apela `runMutation`. Dacă găsește orfani sau linkuri invalide, construiește o instrucțiune de reparare și pornește agentul.

### Tool-urile interne ale agentului

Sursa: `packages/core/src/agent/tools.ts`, `buildWriteTools`.

- `write_concept`: `path` string; `frontmatter` cu `type` string nevid obligatoriu, `title`/`description`/`resource` string opționale, `tags` array de stringuri opțional și proprietăți suplimentare permise; `body`, `log_summary` stringuri obligatorii.
- `patch_concept`: `path`, `log_summary`; opțional `frontmatter` map de valori necunoscute, `replace_section` (`heading` string nevid, `content` string) și/sau `replace_body` string. Codul nu impune exact una dintre opțiunile de editare.
- `delete_concept`: `path`, `log_summary` stringuri obligatorii.
- Câmpurile `path` folosesc un Zod string descris ca relativ la bundle și terminat `.md`. `Bundle.resolve()` respinge escape-ul din rădăcina bundle-ului; `assertConceptPath()` cere `.md` și interzice numele rezervate `index.md` și `log.md`.

Acestea sunt scheme ale tool-urilor AI interne, nu schema directă MCP pentru cele trei operații. O singură mutație poate executa zero sau mai multe tool-uri interne.

## Transport și autentificare

Surse: `packages/server/src/mcp/http.ts` (`mcpRouter`), `packages/server/src/mcp/stdio.ts`, `packages/server/src/index.ts`, `packages/server/src/auth.ts` (`bearerAuth`).

- HTTP folosește `StreamableHTTPServerTransport` la `/mcp`. Creează server MCP și transport noi pentru fiecare request; `sessionIdGenerator: undefined` configurează transport stateless. JSON response este activat. Routerul atașează handlerul la GET/POST/DELETE. La `res.close`, închide transportul și serverul.
- Aplicația Express montează `/mcp`; parserul JSON are limită de 4 MB. Codul face bind la `0.0.0.0`, fapt care nu confirmă expunerea efectivă în rețeaua runtime.
- Procesul stdio folosește `StdioServerTransport`; bearer auth HTTP nu se aplică acelui proces local.
- `AUTH_TOKEN` activează middleware bearer pentru `/mcp` și `/api`; comparația folosește SHA-256 și `timingSafeEqual`. Dacă variabila nu este setată, codul lasă rutele fără această autentificare. Valoarea runtime și activarea ei nu au fost verificate.
- Dependența MCP este declarată cu interval semver în `packages/server/package.json`; versiunea instalată efectiv nu a fost verificată. Nu s-au rulat builduri sau teste.

## Rezultate și certitudinea efectului

`packages/core/src/agent/agent.ts` definește `MutationOutcome`; `server.ts` convertește rezultatul în text MCP prin `mutationOutcomeResponse`:

- `ok: true`: rezumat text și căile `filesChanged` (sau `none`). Nu există job ID sau receipt persistent în răspunsul tool-ului.
- `status: "partial"`: text de avertizare cu fișiere raportate și eroarea; helperul nu setează `isError: true`. Clientul nu trebuie să considere terminarea apelului drept lipsă de efect.
- `status: "failed"`: text de eroare cu `isError: true`. `runMutation` produce acest status dacă excepția apare înainte ca setul `filesChanged` să fie populat; nu demonstrează universal că nicio scriere nu a avut loc.

### Succes

`runMutation` terminat fără excepție și cu `ok: true` este confirmare la nivelul codului că rularea agentului s-a terminat. Căile din `filesChanged` sunt adăugate de callback-urile tool-urilor după ce metodele KnowledgeBase se rezolvă. Un răspuns cu căi nevid este dovadă că metodele respective au raportat succes în procesul apelant. Rezumatul rămâne text generat de agent, fără receipt cu checksum sau rezultat structurat per operație. `ok: true` cu zero căi nu dovedește că efectul solicitat a fost aplicat. Pentru maintain, healthy no-op este o cale explicită diferită.

### Eșec fără efect și efect parțial

Nu există confirmare generală, durabilă, de `no effect`. `filesChanged` se actualizează în `buildWriteTools` după rezolvarea metodei KnowledgeBase. Însă `Bundle.writeConcept()` scrie documentul înainte de `KnowledgeBase.afterMutation()`, care ulterior prunează directoare, regenerează indexuri și adaugă log. O eroare în pașii ulteriori poate lăsa documentul schimbat înainte ca tool-ul să adauge calea în set. În consecință, `failed` plus set gol nu este suficient pentru `FAILED_NO_EFFECT`.

Outcome-ul `partial` indică cel puțin o cale înregistrată, dar nu oferă rollback, tranzacție multi-fișier sau manifest complet al efectelor. Indexul, logul și conceptele sunt fișiere distincte. Mutațiile succesive ale agentului nu sunt o tranzacție comună.

### Timeout, deconectare și crash

În handlerul MCP și `runMutation` inspectate nu apare un timeout per mutație, anulare explicită a agentului la disconnect, heartbeat sau rollback. Handlerul HTTP închide transportul la `res.close`, dar nu transmite `AbortSignal` către `runMutation`. Timeouturile SDK-urilor, proxy-ului, providerului LLM și runtime-ului nu au fost verificate și pot exista în afara codului citit. Nu se poate deduce dacă o cerere închisă oprește inferența ori scrierile deja pornite.

Scrierile sunt fișiere separate, fără tranzacție multi-fișier sau recovery journal. Crash-ul poate surveni între scrierea conceptului, reindexare și log sau între mai multe tool-uri interne. `GIT_AUTOCOMMIT === "true"` activează commit după scrieri; autocommit-ul este best-effort, iar eroarea este doar logată. Nu există status durabil per mutație pentru determinarea rezultatului după crash.

## Traseu până la persistență

1. MCP `memory_add`/`memory_update` sau `/api/chat` ajunge la `runMutation`/`streamChat` și construiește tool-urile interne.
2. Agentul LLM poate apela `write_concept`, `patch_concept`, `delete_concept` și tool-uri de citire.
3. `KnowledgeBase` (`packages/core/src/okf/knowledge-base.ts`) serializează metodele de mutație într-un `mutationQueue` din instanța curentă.
4. `Bundle` (`packages/core/src/okf/bundle.ts`) validează path-ul și scrie/patch-uiește/șterge Markdown.
5. `afterMutation` rulează `pruneEmptyDirs`, `regenerateIndexChain` și `appendLog`; apoi poate face Git autocommit.
6. Callback-ul agentului adaugă path-ul în `filesChanged` după rezolvarea metodei; `runMutation` salvează trace/outcome, iar serverul creează rezultatul MCP.

`memory_maintain` execută întâi `kb.lint()` și poate întoarce no-op; numai când găsește probleme pornește agentul.

Coada `mutationQueue` este numai in-process, în instanța `KnowledgeBase`; nu coordonează alte procese, CLI-uri sau editări directe ale bundle-ului.

## Idempotency, status, audit și reconciliere

- Nu există cheie de idempotency în schemele MCP sau handler-ele operațiilor.
- Nu există job ID ori API de status al mutației. `traceId` intern nu este expus drept receipt stabil de `memory_add`/`memory_update`.
- `/api/trace` permite citirea unui trace după ID, dar trace-ul nu este jurnal complet al efectelor și nici mecanism de reconciliere.
- `TraceStore` scrie JSON în `.traces`; erorile de salvare sunt logate și ignorate. Trace-ul nu este transaction log.
- Nu a fost găsit lookup al unei mutații active sau endpoint de reconciliere.

Prin urmare, timeout, deconectare, rezultat parțial sau crash trebuie clasificate `unknown`. Nici `isError`/`failed` nu demonstrează singure no-effect.

## Alte căi mutative

- `packages/server/src/api/chat.ts`, `POST /api/chat`, folosește `streamChat` cu aceleași tool-uri de scriere.
- `packages/server/src/dreamer.ts` (`startDreamer`) poate apela periodic `runDream` dacă `DREAM_INTERVAL` este configurat; intervalul este clamped la minimum 5 minute. Nu s-a verificat dacă timerul este activ în runtime.
- `packages/core/src/agent/cli.ts` oferă un mod mutate local.
- Orice proces cu write access la bundle poate modifica fișierele fără KnowledgeBase, coada ori logul aplicativ.

## Necunoscute și riscuri

### Runtime neconfirmat

- Dacă commitul local corespunde imaginii/serviciului activ.
- Transportul și ruta efectiv folosite de client, autentificarea activă, bundle mount și permisiunile lui.
- Timeouturile efective la fiecare strat și dacă închiderea clientului anulează munca.
- Versiunile instalate ale MCP SDK, AI SDK, Zod și providerilor.
- Dacă timerul dreamer este activ.

### Riscuri confirmate din codul local

- `failed` fără căi în `filesChanged` nu dovedește no-effect pentru toate ferestrele de eșec.
- Outcome-ul parțial nu este atomic și nu poate fi rollback-uit de contractul MCP.
- Autocommit-ul Git este opțional și best-effort.
- Auth HTTP este opțional; stdio este suprafață separată.
- Serializarea KnowledgeBase nu asigură exclusivitate cross-process.

## Cerințe înainte de integrarea Rendiv reală

1. Confirmați commitul deployat și configurația non-secretă relevantă; verificați credentialul doar ca prezență/absență, fără a-i citi valoarea.
2. Definiți request/response versionat, receipt/correlation ID stabil și rezultat structurat, inclusiv căile efectiv schimbate.
3. Definiți idempotency și status lookup; fără ele nu se poate face retry sigur după rezultate ambigue.
4. Oferiți criteriu verificabil de no-effect care acoperă inclusiv eșecul dintre scrierea conceptului, index și log. MCP `isError` nu este suficient în codul curent.
5. Definiți efecte parțiale, crash recovery și reconciliere umană; unknown nu se reexecută automat.
6. Măsurați timeouturile și testarea disconnect/crash numai într-un bundle clonat aprobat.
7. Inventariați și coordonați toate bypass-urile: MCP direct, `/api/chat`, dreamer, CLI și scriere filesystem.
8. Doar apoi implementați transportul Rendiv și teste izolate. Această investigație nu implementează executorul și nu autorizează mutații.

## Fișiere și simboluri inspectate

- `packages/server/src/mcp/server.ts`: `buildMcpServer`, schemele MCP, `mutationOutcomeResponse`.
- `packages/server/src/mcp/http.ts`: `mcpRouter` și Streamable HTTP.
- `packages/server/src/mcp/stdio.ts`: transport stdio.
- `packages/server/src/auth.ts`: `bearerAuth`.
- `packages/server/src/index.ts`: middleware, wiring și limite Express.
- `packages/server/src/api/chat.ts`: `chatRouter` și `/api/chat`.
- `packages/server/src/dreamer.ts`: `startDreamer`.
- `packages/core/src/agent/agent.ts`: `runMutation`, `MutationOutcome`, `streamChat`.
- `packages/core/src/agent/tools.ts`: `buildWriteTools` și schemele interne.
- `packages/core/src/okf/knowledge-base.ts`: `KnowledgeBase`, `mutationQueue`, `afterMutation`.
- `packages/core/src/okf/bundle.ts`: path validation și persistență Markdown.
- `packages/core/src/okf/indexer.ts`: pruning și reindexare.
- `packages/core/src/okf/logger.ts`: `appendLog`.
- `packages/core/src/agent/trace.ts`: `TraceStore`.
- `packages/server/package.json`: intervalul semver declarat pentru MCP SDK.

**Metodă:** căutare și citire statică a surselor/testelor locale. Nu s-a executat cod Understory, MCP, HTTP, Docker/Compose sau teste și nu s-au citit fișiere ori valori secrete.
