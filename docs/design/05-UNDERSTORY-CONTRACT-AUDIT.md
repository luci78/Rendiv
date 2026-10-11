# Audit read-only al contractului Understory

- **Checkpoint:** 6B.2D
- **Data:** 2026-10-11
- **Sursă locală inspectată:** `/home/luci78/ai-stack/understory`, commit `f6c342332f390a444a8669636b1cf8f9669dd995`; working tree curat la verificare.
- **Metodă:** citire statică a surselor locale, fără build, teste, servicii, Docker, HTTP, MCP, stdio sau acces la bundle/DB. Nu s-au citit fișiere `.env`, secrete sau date din memorie.
- **Limită:** commitul local nu dovedește că aceeași versiune/configurație rulează în Understory activ.

## 1. Rezumat executiv

1. `memory_add` și `memory_update` întorc text MCP generat de aplicație. `ok: true` înseamnă că `generateText` s-a încheiat fără excepție; `Files changed` conține căi adăugate de callback-urile tool-urilor după ce operațiile `KnowledgeBase` s-au rezolvat. Acesta este **succes raportat**. Nu există receipt cu operation ID, revision, hash sau read-back, iar lista nu include fișierele index/log regenerate.
2. `memory_maintain` are în sursă o cale deterministă healthy no-op: rulează lint, nu apelează `runMutation`, apoi răspunde cu forma exactă `Memory is healthy — N concepts, N links, no orphans, no broken links. Nothing to repair.` Pentru checkout-ul inspectat, potrivirea exactă a acestui răspuns corelat este o dovadă explicită la nivelul aplicației că acel apel s-a încheiat fără mutație. Rendiv nu o recunoaște încă și o lasă `unknown`; nu s-a schimbat adaptorul.
3. `failed`/`isError` nu demonstrează absența efectului. `Bundle.writeConcept()` scrie fișierul concept înainte ca `KnowledgeBase.afterMutation()` să regenereze indexurile și logul. `filesChanged.add()` se execută numai după ce întreaga metodă KB se rezolvă. O eroare după scrierea conceptului, dar înainte de completarea pașilor ulteriori, poate produce răspuns `failed` cu listă goală, deși a existat efect.
4. Nu există tranzacție multi-fișier, manifest durabil, rollback ori `fsync`/receipt de commit în traseul inspectat. `GIT_AUTOCOMMIT` este opțional și commitul este best-effort.
5. Nu există idempotency key, status durabil al unei mutații ori revision per operație. `traceId` este intern pentru `MutationOutcome`, nu este inclus în răspunsul MCP; TraceStore este best-effort și își limitează retenția.
6. Codul nu configurează un timeout explicit pentru `runMutation` sau handlerul MCP și nu propagă un `AbortSignal` la generarea textului. Există fallback de model la erori retryable; pentru 429 este opt-in. Retry-urile interne/default ale versiunii AI SDK și setările runtime nu sunt confirmate numai de citirea sursei.
7. Sursa definește endpointuri browse cu operații KB deterministe și read-only, inclusiv read-back de concept. Nu s-au apelat: configurația runtime, auth-ul, bundle-ul și corespondenta commitului local cu serviciul activ nu sunt confirmate, iar aceste API-uri pot expune conținutul memoriei.

## 2. Proveniență și niveluri de certitudine

### Confirmat în codul local inspectat

- Checkout Understory la commitul și starea Git de mai sus; nu s-a executat codul checkout-ului.
- Schemele celor trei tool-uri, forma textuală a răspunsurilor, traseul `runMutation` → write tools → `KnowledgeBase` → `Bundle`, healthy no-op-ul și rutele browse descrise mai jos.
- Codul la `packages/server/src/index.ts` montează `/mcp` și `/api`; middleware-ul bearer este activat condițional de `AUTH_TOKEN`.
- `packages/server/package.json` declară `ai: ^5.0.0` și `@modelcontextprotocol/sdk: ^1.12.0`; lockfile-ul local rezolvă `ai@5.0.210` și `@modelcontextprotocol/sdk@1.29.0`. Aceste valori descriu checkout-ul, nu dependențele runtime confirmate.

### Inferență limitată din cod

- Un răspuns MCP valid, cu ID JSON-RPC care corespunde cererii curente și exact markerul healthy no-op descris mai jos, indică execuția ramurii de lint sănătos din acest cod și lipsa apelului la `runMutation` în acea ramură.
- Un read-back prin `/api/concept` poate observa conținutul curent al unui fișier. Nu poate demonstra singur ce operație l-a produs, dacă nu a fost ulterior suprascris sau dacă toate scrierile aferente au fost comise durabil.

### Necunoscut despre runtime

- Dacă serviciul activ folosește commitul local, schema exactă de răspuns MCP instalată, credentialul/auth-ul activ, model/providerul efectiv, timeouturi externe și retry-urile implicite SDK/provider.
- Dacă există proxy-uri, retry de client, alte procese de scriere, filesystem cu garanții speciale sau backup/versionare externe.
- Nicio rută read-only nu a fost apelată; raportul nu afirmă valori observate prin runtime.

## 3. Contractul operațiilor

### `memory_add`

Sursa: `packages/server/src/mcp/server.ts`, `buildMcpServer`, schema și handlerul de la liniile 95–127.

- Argumente MCP: `content: string` obligatoriu și `suggested_path?: string` opțional. `suggested_path` este un indiciu transmis în prompt, nu o promisiune că va fi ales.
- Handlerul construiește instrucțiunea și apelează `runMutation`; agentul poate face zero, unul sau mai multe tool calls interne (`packages/core/src/agent/agent.ts:145–188`, `packages/core/src/agent/tools.ts:85–160`).
- Răspuns `ok`: rezumat text plus lista `Files changed` sau `- none`; nu conține traceId/receipt/version.
- `partial`: text cu numărul și căile înregistrate și eroarea, fără `isError: true` în helperul MCP.
- `failed`: text `Mutation failed: …` cu `isError: true`; nu certifică no-effect.
- No-op-ul nu este un rezultat contractual distinct pentru add. Răspuns fără căi rămâne ambiguu.

### `memory_update`

Sursa: `packages/server/src/mcp/server.ts`, schema și handlerul de la liniile 129–144.

- Argument MCP: `instruction: string` obligatoriu; editările efective sunt tool calls interne ale agentului.
- Răspunsurile `ok`/`partial`/`failed` sunt construite prin același `mutationOutcomeResponse` ca la add.
- Textul de succes fără căi nu distinge între instrucțiune satisfăcută fără schimbare, neexecutarea unui write tool și rezultat incomplet; nu există status `no_op`.

### `memory_maintain`

Sursa: `packages/server/src/mcp/server.ts`, schema și handlerul de la liniile 184–237; `packages/core/src/okf/knowledge-base.ts:66–69`; `packages/core/src/okf/lint.ts:28–45`; `packages/core/src/okf/graph.ts:38–90`.

- Argumente: obiect gol `{}`.
- Handlerul apelează `kb.lint()`. Acesta derivă graful prin enumerarea și citirea conceptelor; implementarea lint/graph inspectată nu scrie bundle-ul și nu invocă LLM.
- Când `before.healthy` este true, handlerul revine imediat fără `runMutation`, fără `refreshSeed` și fără al doilea lint. Markerul textual exact este: `Memory is healthy — ${conceptCount} concepts, ${linkCount} links, no orphans, no broken links. Nothing to repair.` (`server.ts:193–203`). Numerele sunt valori dinamice din rezultatul lint, nu identificator de operație.
- Dacă graful nu este sănătos, construiește instrucțiunea de reparare și apelează `runMutation`; la succes rulează `refreshSeed` și un lint după mutație, apoi returnează rezumat, comparația stării grafului și `Files changed` (`server.ts:205–237`). Acesta nu este un rezultat tranzacțional și numărul de căi nu este manifestul tuturor fișierelor scrise.
- Markerul no-op este dovadă de rezultat pentru checkout-ul local numai dacă se potrivește integral răspunsul, operația este `memory_maintain`, envelope-ul MCP este valid/correlat și se știe că versiunea locală corespunde serviciului. Altfel rămâne unknown. Adaptorul Rendiv actual nu parsează markerul și păstrează `unknown`.

## 4. Răspunsuri, identitate, versionare și read-back

### Forma răspunsului

`mutationOutcomeResponse()` (`server/src/mcp/server.ts:67–93`) expune text, nu un rezultat structurat versionat:

| Outcome intern | MCP text/flag în sursă | Semnificație justificată |
|---|---|---|
| `ok: true` | Rezumat agent + `Files changed`/`none`; `isError` absent | Agentul s-a încheiat fără excepție; căile reprezintă tool calls KB care s-au rezolvat. Nu este dovadă de durabilitate sau completitudine semantică. |
| `status: partial` | Avertizare, număr/căi și eroare; `isError` absent | Cel puțin un tool call complet KB a fost înregistrat înaintea erorii. Alte efecte parțiale pot lipsi din set. |
| `status: failed` | `Mutation failed: …`; `isError: true` | Eroare observată; nu există dovadă generală de no-effect. |
| Healthy no-op maintain | Marker determinist cu numere, fără `runMutation` | Finalizare a verificării și absența mutației în ramura inspectată; nu este un receipt durabil. |

### Identitate și versiuni

- JSON-RPC `id` este corelare request/response; nu este operation ID stabil al serverului și nu deduplică retransmiterea logică.
- `MutationResult.traceId` există intern (`agent.ts:23–29, 167–174`), dar `mutationOutcomeResponse()` nu îl trimite clientului.
- `TraceRecorder` derivă ID-ul din timp și `Math.random`; `TraceStore.save()` scrie best-effort sub `.traces`, loghează eșecul și prunează la maximum 50 (`agent/trace.ts:129–149`). Nu este jurnal tranzacțional, status API sau cheie de idempotency.
- Nu s-au găsit operation ID, idempotency key, revision, ETag, hash al conținutului rezultat ori endpoint de status pentru mutație în codul local căutat. `okf_version: "0.1"` din indexul rădăcinii (`okf/indexer.ts:42–54`) este versiunea formatului OKF, nu revision a unei operații.
- `filesChanged` este adăugat de callbacks după rezolvarea completă a metodelor `kb.writeConcept`/`patchConcept`/`deleteConcept` (`agent/tools.ts:96–158`). `KnowledgeBase.afterMutation()` mai poate modifica indexuri și `log.md` (`knowledge-base.ts:118–138`), dar callback-ul adaugă numai calea conceptului. Lista raportată nu este un manifest exhaustiv al tuturor fișierelor efectiv atinse.

### Read-back

`packages/server/src/api/browse.ts:10–48, 78–80` definește `/api/tree`, `/api/concept`, `/api/search`, `/api/log`, `/api/validate`, `/api/graph` și `/api/types`; handler-ele apelează metodele deterministe `KnowledgeBase` de citire (`knowledge-base.ts:40–74`). `Bundle.readConcept()` folosește `fs.readFile` (`bundle.ts:79–99`). Comentariul routerului declară browse-ul fără LLM.

Aceste rute pot observa conținutul curent în checkout-ul cu API activ, dar nu oferă revision/ETag legat de operația inițială și nu demonstrează atomicitate sau durabilitate. Există și alte rute `/api` cu comportament diferit; fiecare trebuie evaluată separat. `index.ts:64–76` arată că bearer auth este condițională; starea runtime nu a fost verificată. Nu am apelat niciun endpoint: nu am putut demonstra identitatea buildului și a bundle-ului active ori politica de acces, iar datele citite ar putea expune memoria reală.

`memory_query` nu este un read-back pur: handlerul apelează `runQueryCached()` (`server/mcp/server.ts:38–52`), care poate porni agentul LLM. Nu a fost apelat. `/api/trace` poate expune inputuri/rezumate și nu este recomandat ca dovadă de efect.

## 5. Atomicitate, durabilitate, erori și retry

### Scrieri și efecte parțiale

- `Bundle.writeConcept()` serializează documentul și execută `fs.writeFile` (`bundle.ts:101–122`); patch-ul ajunge tot la această scriere (`bundle.ts:128–149`); delete folosește `fs.unlink` (`bundle.ts:151–160`).
- După document, `KnowledgeBase.afterMutation()` prunează directoare, regenerează indexul/strămoșii și adaugă intrare în `log.md`; fiecare este efect FS separat (`knowledge-base.ts:118–138`, `indexer.ts:35–75`, `logger.ts:12–53`). Nu există commit comun multi-fișier sau rollback.
- `buildWriteTools` adaugă concept path în `filesChanged` numai după await-ul complet al metodei KB. Dacă documentul a fost scris, apoi indexarea/logarea eșuează, `runMutation()` poate prinde excepția cu set gol și produce `failed` (`agent.ts:176–187`), deși efectul conceptului s-a produs. Deci `FAILED_NO_EFFECT` nu poate fi demonstrat din `isError`, `failed` ori listă goală.
- Dacă `GIT_AUTOCOMMIT` este activ, `afterMutation()` încearcă `git add` și `git commit` după scrieri; excepțiile sunt doar logate (`knowledge-base.ts:130–137`). Acest lucru nu oferă receipt stabil ori garanție de durabilitate pentru client.

### Timeout, deconectare și retry

- Nu am găsit timeout explicit în handlerul MCP sau în apelul `generateText` al `runMutation()` (`agent.ts:145–188`, `mcp/http.ts:16–35`). La `res.close`, transportul și serverul MCP sunt închise, dar sursa nu transmite `AbortSignal` la `runMutation`; efectul anulării asupra inference/providerului rămâne necunoscut.
- Codul Understory nu retrimite automat requestul MCP. `withFallback()` poate încerca modelul fallback pentru erori provider/transport recunoscute (408, 5xx, erori de transport și erori marcate `isRetryable`); 429 este retryable numai dacă `LLM_FALLBACK_RETRY_429=true`; 401/403 și AbortError nu sunt retryable (`providers/fallback.ts:12–55, 58–91`). Aceasta este reluare a unui pas de generare către fallback, nu idempotency pentru tool call.
- `generateText` nu setează explicit `maxRetries` în codul inspectat. Comportamentul implicit al AI SDK/providerului nu poate fi stabilit numai din acest apel; dependența declarată este semver, iar versiunile lockfile nu confirmă ce rulează în container.
- Nu există idempotency/status upstream. Un client care retransmite după timeout poate porni o a doua operație; contractul nu distinge acea cerere de prima. Răspunsul lipsă, invalid sau timeout trebuie tratat `unknown`.

## 6. Matrici de clasificare

„Actual Rendiv” indică implementarea adaptorului din `src/rendiv_api/understory_adapter.py` și regula workerului 6B.2C. „Justificat” indică ce ar putea fi clasificat pe baza codului local, numai dacă răspunsul aparține serviciului/versiunii așteptate. Niciuna dintre acestea nu confirmă runtime-ul activ.

### `memory_add`

| Rezultat Understory | Dovezi disponibile | Clasificare Rendiv justificată / actuală | Informații lipsă | Modificare minimă de contract |
|---|---|---|---|---|
| `ok`, `changed_paths` nevid | `runMutation` fără excepție și paths ale tool-urilor KB completate; paths omit index/log | Raportat, nu durable/semantic-complete; unknown / actual unknown | Receipt legat de request, conținut/revision observat, manifest complet | Outcome structurat cu operation ID, revision și lista completă de efecte raportate; nu eticheta drept durable fără dovadă separată |
| `ok`, paths goale/none | Agentul s-a încheiat fără excepție, fără write KB în set | Ambiguu: nu se distinge solicitare satisfăcută fără schimbări de agent fără write; unknown / actual unknown | Outcome explicit `no_op` vs. `applied`, motiv validabil | Câmp outcome structurat, fără inferență din rezumat liber |
| `failed` / MCP `isError` | Excepție în run; set gol nu acoperă scrierea conceptului urmată de eșecul index/log | No-effect nedemonstrat; unknown / actual unknown | Journal al fiecărui efect sau refuz garantat înainte de orice write | Status `rejected_before_write` doar dacă upstream poate verifica că niciun write nu a început; altfel `unknown` |
| `partial` | Setul conține numai KB calls complet rezolvate; efectele ulterioare incomplete pot lipsi | Efect parțial; unknown / actual unknown | Manifest durabil al tuturor fișierelor și status terminal al agentului | Outcome parțial structurat, operation ID, manifest și indicator explicit dacă executorul mai poate rula |
| Timeout, disconnect, crash | Fără receipt/status; handlerul poate fi încă activ sau poate fi terminat după efecte | Unknown; fără retry / actual unknown | Lookup durabil, status terminal, fencing la anulare | Endpoint status per operation ID și garanție de anulare/terminalitate; retry doar cu idempotency |
| Replay/duplicat | Niciun idempotency key sau operation ID în schema MCP | Nu se poate dovedi același job; unknown la răspuns pierdut / actual unknown | Identitate logical request și deduplicare upstream | Idempotency key persistată, unică per request logic, status returnat la replay |
| No-op | Nu este definit pentru add | Nu deduce no-op din `Files changed: none`; unknown / actual unknown | No-op semantic specific operației, dacă este permis | Outcome distinct explicit doar dacă operația chiar îl suportă |

### `memory_update`

| Rezultat Understory | Dovezi disponibile | Clasificare Rendiv justificată / actuală | Informații lipsă | Modificare minimă de contract |
|---|---|---|---|---|
| `ok`, `changed_paths` nevid | Agent completat fără excepție; paths ale KB calls rezolvate, fără index/log exhaustiv | Raportat, nu durable/semantic-complete; unknown / actual unknown | Receipt/revision și read-back legat de request | Outcome structurat cu operation ID/revision și paths raportate |
| `ok`, paths goale/none | Agent completat, dar nicio cale în set | Nu dovedește instrucțiunea satisfăcută sau no-op; unknown / actual unknown | Distincție explicită între no-op, instrucțiune fără write și eșec semantic | `outcome` structurat, nu rezumat generat de agent |
| `failed` / MCP `isError` | Eroare de generare sau tool; o scriere a conceptului poate preceda eșecul `afterMutation` fără a intra în set | No-effect nedemonstrat; unknown / actual unknown | Dovadă no-effect, status terminal și write journal | No-effect terminal numai cu proof verificabil; altfel unknown |
| `partial` | Paths ale metodelor KB încheiate; pot lipsi efectele FS parțiale din metoda care a eșuat | Partial/unknown; fără retry / actual unknown | Manifest complet și dacă alte writes mai rulează | Outcome structurat și manifest asociat operation ID |
| Timeout, disconnect, crash | Răspuns absent; fără status sau idempotency | Unknown; actual unknown | Status terminal/fencing și read-back comparabil | Status API + idempotency; retry numai după outcome demonstrat |
| Replay/duplicat | JSON-RPC id doar corelează mesaje; nu este cheie de operație | Nu se poate garanta deduplicarea; actual unknown | Logical operation ID stabil | Key upstream și returnarea rezultatului original |
| No-op | Nu există no-op marker specific update în sursă | Text fără paths rămâne ambiguu; actual unknown | Outcome explicit de operație terminată fără modificări | Contract structurat pentru `no_op` numai dacă semantics sunt confirmate |

### `memory_maintain`

| Rezultat Understory | Dovezi disponibile | Clasificare Rendiv justificată / actuală | Informații lipsă | Modificare minimă de contract |
|---|---|---|---|---|
| Healthy no-op exact | Ramura `before.healthy` după lint read-only; răspuns cu prefix și sufix exact și count-uri; `runMutation` nu este chemat | `succeeded/complete` este justificat ca task terminal fără mutație dacă markerul complet este verificat și versiunea/ID-ul response sunt corelate; actual Rendiv rămâne unknown | Contract versionat, marker stabil independent de prose și corelare receipt/operation ID | Cel mai mic pas: rezultat structurat `outcome=no_op`, counts și operation ID; păstrați textul doar pentru display |
| Răspuns fără căi, dar fără markerul exact | Poate fi no-op trunchiat/alterat sau alt rezultat | Unknown / actual unknown | Marker valid sau outcome structurat | Nu clasifica din substring ori cuvinte aproximative; adăugați marker de protocol |
| `ok`, paths nevid | `runMutation` fără excepție, apoi lint după; căi concept, index/log pot lipsi | Succes raportat, nu confirmă efect complet/durabil; unknown / actual unknown | Outcome terminal/version/revision și manifest | Outcome structurat; revision/read-back poate adăuga observare, nu promite tranzacție |
| `failed` / `partial` | Aceleași limite ca `runMutation`; health lint de după nu rulează pe ramura failed | No-effect nu este demonstrat; partial/unknown; actual unknown | Operation journal și rezultat terminal | Outcome structurat și proof no-effect numai când este verificabil |
| Timeout, disconnect, crash | Apelul poate fi în ramura lint sau agent; clientul nu știe care | Unknown; actual unknown | Etapa/status durabilă și operation ID | Status per operation și fencing la anulare |
| Replay/duplicat | No-op poate fi re-lintat fără mutație, dar un replay al variantei repair poate repeta mutații | Nu se poate trata uniform ca harmless; actual unknown | Idempotency și status-ul requestului original | Dedupe upstream; nu folosi doar textul markerului ca cheie |

## 7. Opțiuni de îmbunătățire a contractului

| Opțiune | Schimbare | Avantaje | Riscuri/limite |
|---|---|---|---|
| 1. Rezultat MCP structurat și versionat | În locul clasificării textului, întoarce un obiect cu contract version, operation ID, outcome explicit (`applied`, `no_op`, `partial`, `rejected_before_write`, `unknown`), paths și câmpuri de observare disponibile. Păstrează rezumatul separat pentru display. | Elimină parsarea prosei; no-op-ul maintain poate fi clasificat explicit; reduce false positive/negative. | Fără journal durabil, receipt și idempotency nu rezolvă timeoutul, replay-ul sau dovada durabilității; `paths` tot nu demonstrează atomicitate. |
| 2. Journal durabil + idempotency + status | Acceptă operation/idempotency key, persistă începutul/pașii/rezultatul și expune status read-only; replay-ul returnează aceeași operație, nu pornește alta. Include manifest/evidence pentru no-effect și partial. | Reconciliere după timeout/restart; reduce duplicările; poate lega read-back-ul de operația inițială. | Necesită stare persistentă și tranzacții upstream; efectele filesystem existente rămân multi-file și pot preceda journalul dacă nu sunt integrate. |
| 3. Generație de bundle cu commit verificabil | Scrie într-o generație staging, validează, apoi publică prin schimbare atomică de pointer/manifest; receipt-ul identifică generația și verificările de persistare efectuate. | Poate da boundary de publicare clar și revision comparabil pentru read-back; oferă bază pentru atomicitate la nivel de generație. | Schimbare structurală costisitoare, compatibilitate cu readerii/CLI și recuperare; nu trebuie pretinsă durabilitate hardware fără fsync/FS contract confirmat. |

**Recomandare:** începeți cu opțiunea 1 pentru rezultat explicit, inclusiv markerul no-op, dar păstrați `unknown` la timeout, disconnect, `failed` și partial neclar. Pentru retry/reconciliere sigură adăugați opțiunea 2; nu activați retry numai pentru că există un read-back. Luați opțiunea 3 dacă cerința devine atomicitate/durabilitate a mai multor fișiere. Nu presupuneți că doar `changed_paths` ori read-back-ul satisfac aceste niveluri.

## 8. API-uri read-only și acțiuni neefectuate

- Codul local arată că browse endpoints și `kb.lint()`/`readConcept()` nu apelează LLM și nu scriu bundle-ul în handler-ele inspectate.
- Nu am apelat API-uri. Nu pot demonstra că serviciul activ corespunde checkout-ului, că bearer auth este activ, care bundle este montat sau că accesul nu expune memoria reală.
- Nu au fost apelate `memory_add`, `memory_update`, `memory_maintain`, `/api/chat`, `/api/trace`, Docker, bazele de date sau alte servicii; nu s-au executat teste.
- Documentul 03 este un audit static precedent și nu consemnează șirul exact healthy no-op. Documentul 04 a concluzionat că markerul nu era stabil cunoscut la momentul auditului; citirea directă a commitului local găsește acum template-ul deterministic din `server.ts:193–203`. Aceasta actualizează dovada pentru checkout, dar nu confirmă versiunea runtime.

## 9. Referințe inspectate

Toate referințele de mai jos sunt din checkout-ul local Understory la commitul indicat în antet:

- `packages/server/src/mcp/server.ts`: `mutationOutcomeResponse` (67–93), scheme/handler `memory_add` (95–127), `memory_update` (129–144), `memory_maintain` (184–237).
- `packages/server/src/mcp/http.ts`: `mcpRouter` și închiderea transportului la close (13–35).
- `packages/server/src/index.ts`: pornirea dreamer, bearer opțional și mount-urile `/mcp`, `/api` (19–24, 64–76).
- `packages/server/src/api/browse.ts`: handler-ele browse deterministe (10–48, 78–80).
- `packages/core/src/agent/agent.ts`: `MutationOutcome`, `resolveAgentModel`, `runMutation` (33–36, 45–73, 145–188).
- `packages/core/src/providers/fallback.ts`: retry/fallback și erorile retryable (12–91).
- `packages/core/src/agent/tools.ts`: callbacks write/patch/delete și `filesChanged` (85–160).
- `packages/core/src/okf/knowledge-base.ts`: metode read-only (40–74), serializare in-process și `afterMutation` (76–139).
- `packages/core/src/okf/bundle.ts`: read-back `readConcept` (79–99), scriere/patch/delete (101–160).
- `packages/core/src/okf/lint.ts`: `lintBundle` fără scrieri (28–45); `packages/core/src/okf/graph.ts`: `scanGraph` prin listare/citire (38–90).
- `packages/core/src/okf/indexer.ts`: regenerarea indexurilor (35–75); `packages/core/src/okf/logger.ts`: actualizarea logului (12–53).
- `packages/core/src/agent/trace.ts`: ID, save best-effort, retenție și read (123–149).
- `packages/server/package.json`, `packages/core/package.json`, `pnpm-lock.yaml`: intervale declarate și rezoluții locale SDK, nu versiuni runtime verificate.
