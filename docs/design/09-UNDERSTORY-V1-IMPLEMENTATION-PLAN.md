# Plan minim de implementare Understory MCP V1

Data: 2026-10-12
Stare: plan actualizat după deciziile aprobate în 6B.2K-A; codul rămâne neimplementat. Aprobarea acoperă exclusiv implementarea și testarea offline, nu producția.

## Proveniență și domeniu

- Rendiv: checkout `main`, commit `05945eb65f115fbc683d48b39bf2bf2c45f78e84`, curat la preflight.
- Understory local: checkout `main`, commit exact `f6c342332f390a444a8669636b1cf8f9669dd995`, curat la preflight.
- Versiunea codului din containerul Understory activ nu este legată de checkout prin provenance verificată; concluziile despre implementare sunt confirmate pentru sursa locală de la commitul de mai sus, nu pentru runtime.
- S-au inspectat numai documente și cod local. Fără Docker, endpointuri, MCP, LLM, baze active, secrete, instalări sau teste.

## Constatări principale

1. Cele trei tool-uri MCP locale întorc `content` text-only. Nu au `structuredContent`, `operation_id` sau envelope V1 (`packages/server/src/mcp/server.ts:67-93,95-144,184-239`). SDK 1.29.0 oferă callbackului `extra.requestId`; V1 îl poate echo fără un argument nou, dar handler-ele Understory nu îl primesc/utilizează explicit în sursa actuală. Confirmarea SDK este în `docs/design/08-MCP-SDK-129-RUNTIME-TEST.md`.
2. `runMutation()` poate întoarce `ok: true` dacă `generateText()` s-a încheiat chiar dacă `filesChanged` este gol; succesul modelului nu dovedește că s-a făcut o scriere ori că instrucțiunea a fost satisfăcută. Cu căi nevid, acestea sunt căi de concepte raportate de tool-uri, nu manifest exhaustiv sau receipt durabil (`packages/core/src/agent/agent.ts:145-188`; `packages/core/src/agent/tools.ts:85-159`).
3. Scrierile de concept/index/log sunt apeluri filesystem independente. Nu există rollback sau boundary atomic multi-fișier observat în traseul inspectat. Persistența nu face `fsync`; nu s-a găsit journal de operație, idempotency key sau status lookup în sursele inspectate.
4. Căile canonice Understory sunt bundle-relative cu slash sentinel inițial (`packages/core/src/okf/bundle.ts:22-55`), iar V1 cere căi POSIX-relative. Decizia aprobată este eliminarea unui singur sentinel numai dintr-un path bundle-relativ valid, apoi validare/sortare/uniqueness; nu se ating paths interne ori textul legacy. Aceasta nu dovedește efect sau persistență.
5. Decizia `isError` este închisă pentru offline: handlerul păstrează `isError: true` și textul actual la `MutationOutcome.failed` (`server.ts:89-92`); V1 poate atașa outcome `unknown` fără să schimbe indicatorul legacy. Contractul spune explicit că `isError` nu dovedește no-effect. Validatorul Rendiv actual respinge `isError=true` cu orice outcome diferit de rejected (`mcp_contract_v1.py:315-316`); această diferență de cod este documentată pentru o etapă Rendiv ulterioară și nu se schimbă aici.
6. `memory_maintain` are o ramură healthy explicită: `kb.lint()` determinist citește graful, iar `before.healthy` întoarce mesajul no-op înainte de `runMutation()` (`server.ts:192-203`; `packages/core/src/okf/lint.ts:28-45`). Aceasta este dovadă de ramură fără mutație în checkout-ul local, nu dovadă de build/runtime activ și nu aprobă o tranziție Rendiv terminală.

## Traseele reale din sursa locală

### `memory_add`

1. Handlerul MCP validează prin schema tool-ului `content: string` și `suggested_path?: string`, construiește o instrucțiune pentru agent și apelează `runMutation()` (`packages/server/src/mcp/server.ts:95-127`).
2. `runMutation()` pregătește contextul, rezolvă modelul, cheamă `generateText()` cu read/write tools și maximum 12 pași; dacă generatorul se încheie, întoarce `ok: true`, chiar dacă lista de căi e goală (`packages/core/src/agent/agent.ts:14,145-175`).
3. Primul efect de bundle pentru un `write_concept` este `fs.mkdir(..., recursive)` și apoi `fs.writeFile()` pentru concept (`packages/core/src/okf/bundle.ts:101-121`). Agentul poate folosi și `patch_concept` sau `delete_concept`; acestea sunt tool-uri interne, nu operații MCP publice distincte (`packages/core/src/agent/tools.ts:85-159`).
4. După operația principală, `KnowledgeBase.afterMutation()` execută pe rând prune de directoare goale, regenerarea indexurilor, append/update în `log.md`, apoi opțional `git add`/commit best-effort (`packages/core/src/okf/knowledge-base.ts:76-139`). Indexurile și logul folosesc fiecare `fs.writeFile()` direct (`indexer.ts:12-55`; `logger.ts:12-53`).
5. Abia după rezolvarea întregii metode KnowledgeBase, `buildWriteTools` adaugă calea conceptului în `filesChanged` (`tools.ts:96-101,128-143,153-159`). Dacă fișierul concept a fost scris și o operație ulterioară din `afterMutation` aruncă înainte ca metoda să se rezolve, calea nu intră în set.
6. După generare, `runMutation()` salvează trace-ul best-effort în `.traces/<id>.json`; eroarea de trace este prinsă și nu eșuează operația (`agent.ts:165-175`; `trace.ts:123-149`). Handlerul reîmprospătează seed-ul înainte de a răspunde (`server.ts:123-125`).

**Dovezi:** `ok: true` este raportul de finalizare a apelului de agent; `filesChanged` poate confirma că unele metode KnowledgeBase au revenit cu succes. Nu confirmă satisfacerea semantică, exhaustivitatea efectelor derivate, commit-ul Git, atomicitatea ori durability. O listă goală nu distinge lipsa unui write de o execuție fără rezultat util.

### `memory_update`

1. Handlerul validează `instruction: string`, îl transmite la același `runMutation()` și apoi reîmprospătează seed-ul (`server.ts:129-144`).
2. Agentul primește același toolset intern ca add: `write_concept`, `patch_concept`, `delete_concept`. Nu există transaction boundary pentru întregul apel de agent; `KnowledgeBase.enqueue()` serializează individual apelurile de mutație într-un `Promise` queue local instanței (`knowledge-base.ts:30-37,76-115`).
3. `patchConcept()` citește conceptul, aplică modificările în memorie și delegă scrierea directă lui `writeConcept()` (`bundle.ts:128-149`). Ștergerea face `fs.unlink()` înainte de index/log (`bundle.ts:151-159`).

**Dovezi:** aceleași limite ca add. `MutationOutcome.failed` fără căi în set nu demonstrează zero efecte; o scriere poate preceda eșecul `afterMutation` înainte ca tool-ul să adauge path-ul în set.

### `memory_maintain`

1. Handlerul face un lint înainte de a invoca agentul (`server.ts:184-203`). `lintBundle()` derivă rezultatul din `scanGraph()` și nu are scrieri în traseul inspectat (`packages/core/src/okf/lint.ts:28-45`).
2. Dacă `before.healthy` este true, răspunde cu text “Nothing to repair” și se întoarce înainte de `runMutation()`. Nu există modificare de bundle în acea ramură. Rezultatul nu include câmpuri structurate.
3. Dacă graful nu este healthy, construiește instrucțiune cu orphans/broken links, execută același `runMutation()`, reîmprospătează seed-ul și, la succes, face încă un lint înainte de răspuns (`server.ts:205-239`). O eroare la lintul post-mutație poate împiedica răspunsul chiar după efecte; rezultatul clientului devine incert.

**Dovezi:** branch-ul healthy este un candidat pentru `outcome=no_op`, `execution=completed`, `execution_path=healthy_no_op`, `effect=reported_none`, `changed_paths=[]`. Dacă va fi expus ca V1, trebuie legați handlerul, request ID și buildul testat. Rendiv păstrează `unknown/unknown` până la gate-urile contractuale și aprobarea operatorului.

## Matricea outcome-urilor V1

În coloana “Raport posibil” este descris ce poate fi extras din sursa locală sau ce ar însemna un envelope V1 viitor. Sursa locală nu emite în prezent aceste outcome-uri structurate. În toate cazurile, clasificarea Rendiv curentă rămâne `unknown/unknown`, FIFO blocat și fără retry automat.

### `memory_add`

| Outcome V1 | Raport/evidență disponibilă | Efect durabil demonstrat? | Clasificare Rendiv actuală |
|---|---|---:|---|
| `applied` | `runMutation ok` și una sau mai multe căi din metodele KB terminate; căile sunt raport Understory și nu includ index/log ca manifest exhaustiv | Nu. Nici semantic-complete, nici atomic/durable | `unknown/unknown` |
| `no_op` | Nu este outcome permis de V1 pentru add. `ok` cu `filesChanged=[]` nu dovedește no-op | Nu | Envelope invalid/absent → `unknown/unknown` |
| `partial` | `MutationOutcome.status=partial` doar când setul conține cel puțin o cale a unei metode KB deja rezolvate; lista poate omite write-ul metodei care a eșuat în `afterMutation` | Nu; poate exista efect parțial suplimentar neînregistrat | `unknown/unknown` |
| `rejected_before_write` | Nu există rezultat V1 pentru reject în handler. `failed` sau `isError=true` nu arată momentul erorii față de primul write | Nu | `unknown/unknown`; fără `failed/none` |
| `unknown` | Eroare fără set de căi, timeout/disconnect/crash, rezultat absent sau rezultat nevalid; efectul poate să fi început | Nu | `unknown/unknown` |

### `memory_update`

| Outcome V1 | Raport/evidență disponibilă | Efect durabil demonstrat? | Clasificare Rendiv actuală |
|---|---|---:|---|
| `applied` | `runMutation ok` cu căi ale metodelor write/patch/delete terminate; sunt căi bundle-relative raportate, nu revision/receipt | Nu. Index/log și alte efecte nu sunt manifest complet; nicio confirmare durability | `unknown/unknown` |
| `no_op` | V1 nu permite no-op pentru update. Lipsa căilor nu arată dacă agentul nu a editat ori a omis acțiunea cerută | Nu | Envelope invalid/absent → `unknown/unknown` |
| `partial` | `status=partial` confirmă că run-ul a eșuat după cel puțin o metodă internă care a revenit; manifestul poate fi incomplet | Nu; fără rollback | `unknown/unknown` |
| `rejected_before_write` | Nici `MutationOutcome.failed`, nici MCP `isError` nu probează că toate efectele au fost evitate | Nu | `unknown/unknown`; fără `failed/none` |
| `unknown` | Răspuns absent/invalid, timeout/disconnect/crash sau eroare în orice punct al secvenței | Nu | `unknown/unknown` |

### `memory_maintain`

| Outcome V1 | Raport/evidență disponibilă | Efect durabil demonstrat? | Clasificare Rendiv actuală |
|---|---|---:|---|
| `applied` | Calea unhealthy apelează `runMutation()`; căile de concept raportate nu dovedesc că graful a fost reparat complet | Nu; lint după mutație este observație curentă, nu receipt de commit | `unknown/unknown` |
| `no_op` | Calea `before.healthy` este deterministă în sursa locală și nu apelează mutații; răspunsul actual este numai text | Nu se aplică unei mutații; lipsesc totuși structuredContent, build/runtime identity și aprobarea cerută | `unknown/unknown` până la gate și aprobare |
| `partial` | În ramura unhealthy, aceleași căi limitate de `runMutation`; răspunsul partial actual este text și indică paths raportate | Nu; efecte parțiale, fără rollback | `unknown/unknown` |
| `rejected_before_write` | Nu există marker structured pentru reject. O eroare în lint-ul de dinainte poate preceda agentul; o eroare după run poate urma efectului | Nu se poate demonstra generic zero write doar din eroare | `unknown/unknown`; fără `failed/none` |
| `unknown` | Poate fi orice întrerupere în lint inițial, agent, refreshSeed ori lint final; nu există operation status durabil | Nu | `unknown/unknown` |

`changed_paths` V1 trebuie să fie POSIX-relative, unice și sortate. Path-urile canonice Understory încep cu `/`; conversia unui singur sentinel bundle-relative este aprobată. Deoarece `filesChanged` adaugă numai path-ul conceptului după terminarea întregii metode KnowledgeBase, output-ul trebuie să declare `effect_scope=reported_paths_only`, nu `operation_scope`. Nu se poate adăuga index/log ca și cum ar fi parte din setul actual.

## Atomicitate, durability și recuperare

| Proprietate căutată | Ce confirmă sursa locală | Concluzie permisă |
|---|---|---|
| Serializare | `KnowledgeBase.enqueue()` pune promisiunile de write/patch/delete într-un queue în memorie al instanței (`knowledge-base.ts:30-37,112-115`) | Serializare locală per instanță pentru apelurile KB, nu exclusivitate cross-process și nu batch transaction pentru întregul runMutation |
| Atomicitate per concept | `fs.writeFile()` direct după `mkdir`, fără staging + rename în metoda inspectată (`bundle.ts:101-121`) | Nu este demonstrată atomicitate de fișier sau de operație |
| Atomicitate multi-fișier | Concept, prune, index-uri, log și opțional Git sunt pași asincroni separați (`knowledge-base.ts:118-139`) | Nu există rollback/transaction observat; crash-ul poate lăsa un subset |
| Durability | Nu s-a găsit apel explicit `fsync`/`FileHandle.sync` în traseele inspectate | Confirmarea după `writeFile` nu este receipt de durabilitate după crash de host |
| Journal/status | `MutationOutcome` și trace-ul nu sunt un journal operațional lookup-able; trace-ul e telemetry best-effort, cu retenție, nu status API (`agent.ts:33-36,165-187`; `trace.ts:123-149`) | Fără starea persistentă necesară reconcilierii deterministe |
| Idempotency | Tool schemas nu au idempotency key; request ID MCP este doar corelare | Nu există deduplicare logică demonstrată |
| Recovery/rollback | Nu a fost găsit recovery de operație sau undo în traseul inspectat | După crash/timeout, efectul rămâne unknown; nu se reexecută automat |
| Git autocommit | Opțional prin `GIT_AUTOCOMMIT === "true"`; eșecurile commit sunt prinse și logate (`knowledge-base.ts:130-137`; `server/index.ts:19-21`) | Setarea runtime nu a fost citită; commit-ul best-effort nu este rollback/journal de operație și nu dovedește fsync |

## Plan minim, fișier cu fișier

Implementarea offline de mai jos este APROBATĂ în 6B.2K-A. Acest plan nu autorizează modificarea persistenței, codului Rendiv, serviciilor sau integrarea producției.

### A. Protocol V1 fără schimbarea persistenței

1. **`packages/server/src/mcp/server.ts`** — helper/constructor pentru envelope care primește numele operației și `extra.requestId`; returnează atât structuredContent cât și textul legacy neschimbat. Callbackurile folosesc API-ul public SDK 1.29.0 și păstrează exact tipul/valoarea request ID-ului. Creează un UUIDv7 real per apel pentru `operation_id`; nu îl prezintă ca idempotency sau status persistent.
2. Pentru `memory_add` și `memory_update`, precum și ramura mutativă `memory_maintain`, rezultatul normal al agentului, paths sau absența excepției NU justifică `applied`; emite `unknown` cu reason code V1 disponibil, fără a inventa dovadă durabilă. Dacă `MutationOutcome.status === "partial"` și paths confirmate sunt prezente, emite `partial`, paths normalizate cu scope `reported_paths_only`; în caz contrar unknown. `rejected_before_write` nu se emite: codul actual nu oferă proof structurat de zero scrieri. `memory_maintain` emite `no_op` numai în branch-ul `before.healthy`, care se întoarce înaintea agentului și a mutațiilor.
3. Pentru `MutationOutcome.failed`, păstrează textul exact și `isError: true` legacy, dar adaugă structuredContent `unknown`; nu transforma eroarea MCP în dovadă de no-effect. Pentru success/partial/no-op se păstrează conținutul text actual, fără a-l folosi ca probă.
4. Path serializer convertește numai bundle paths canonice cu un slash sentinel inițial în POSIX-relative, apoi respinge absolute, traversal, separator/backslash, NUL/newline, path-uri goale și duplicates; sortează listă. Nici paths interne, nici stringurile `content` legacy nu se schimbă. `atomicity`/`durability` rămân `not_asserted`.
5. **`packages/server/test/mcp/`** — teste fake pentru tool handlers și MCP `InMemoryTransport` cu SDK-ul lockat la 1.29.0. Acoperiți toate trei operațiile, UUIDv7, request ID string/number corelat, content păstrat, structuredContent valid, failed cu isError legacy, partial numai cu efect explicit, healthy no-op, invalid/inconsistent result, timeout/disconnect fără reîncercare și zero acces la rețea/bundle real. Testați că API-ul nu schimbă argumentele tool-urilor.
6. **Verificare validator Rendiv numai offline** — validați fixtures prin `src/rendiv_api/mcp_contract_v1.py` fără integrare cu worker/adaptor. Implementarea actuală respinge `isError=true` cu outcome `unknown` (`src/rendiv_api/mcp_contract_v1.py:315-316`); acesta este mismatch cunoscut. Paritatea validatorului cere o schimbare Rendiv ulterioară înainte de integrarea reală; acest checkpoint nu modifică Python/tests.

### B. Ce cere journal durabil, idempotency sau tranzacții

Nu face parte din transport-only V1 și nu poate fi obținut prin adăugarea câtorva câmpuri la răspuns.

- Pentru status/replay după restart: storage upstream durabil cu cheie logică de idempotency, `operation_id` persistent, rezultate returnate la replay și endpoint/status read-only.
- Pentru recuperare și dovada etapelor: journal append-only înainte/după efecte, cu commit/fsync definit și manifest corelat cu operation ID. Fără o ordine atomică între journal și fișiere există tot o fereastră de incertitudine.
- Pentru rollback/atomicitate multi-file: staging de generație și publicare atomică a bundle-ului sau backend tranzacțional echivalent; fișierele concept, index, log și delete trebuie să participe în aceeași boundary.
- Pentru `rejected_before_write -> failed/none`: enforcement verificabil care respinge înainte să înceapă orice write și răspuns V1 legat de acea verificare. `MutationOutcome.failed`, MCP `isError`, set gol sau mesajul unei excepții nu ajung.
- Pentru anulare sigură: fencing/status care dovedește că workerul Understory nu mai execută și nu mai poate scrie înaintea unei reconcilieri. Timeout-ul singur nu întrerupe și nu finalizează agentul.

### C. Garanții imposibil de demonstrat cu implementarea inspectată

- Semantica completă a cererii `memory_add`/`memory_update` din textul generat de model.
- Că răspunsul `ok` sau `Files changed` înseamnă efect complet, durabil ori semantic satisfăcător.
- Absența oricărui efect după `failed`, `isError`, paths goale, timeout sau disconnect.
- Manifest complet al tuturor efectelor (concept, index-uri, `log.md`, directoare prune, trace/Git) și rollback după o eroare.
- Că un proces/agent întrerupt nu va continua să scrie după timeout-ul clientului.
- Deduplicarea unui retry logic sau găsirea rezultatului după restart fără journal/status.
- Durabilitate hardware/filesystem fără un protocol și garanții explicite de sync/storage.
- Că runtime-ul activ folosește exact checkout-ul Understory `f6c342...`; proveniența containerului rămâne neconfirmată.

## Criterii de acceptare pentru implementarea offline aprobată

1. Cele trei tool-uri întorc un singur envelope V1 valid plus text legacy neschimbat și nu schimbă inputSchema. `request_id` este exact `extra.requestId`; `operation_id` este UUIDv7 real, dar nu este idempotency/status.
2. Nicio cale mutativă nu emite `applied` fără dovadă durabilă. V1 curent nu poate codifica dovada, deci add/update și maintain mutativ emit unknown. `partial` apare numai pentru `MutationOutcome.partial` cu paths confirmate. Healthy `memory_maintain` emite no_op numai pe ramura read-only exactă. Nicio ramură curentă nu emite rejected_before_write.
3. `MutationOutcome.failed` păstrează `content` și `isError=true`; structured result poate avea outcome unknown. Timeout, disconnect, crash și ambiguitate nu declanșează retry.
4. Paths structurate sunt relative fără slash inițial, validate/sortate și distincte de paths/text legacy; conversia nu este probă de persistență.
5. Fake/server-client MCP offline confirmă coexistenta content/structuredContent, corelarea și compatibilitatea clientului text-only, fără acces la bundle, rețea sau LLM. Validatorul Rendiv se verifică separat; mismatch-ul `isError=true` actual este consemnat și necesită etapă de cod Rendiv înainte de integrare.
6. `git diff --check` și toate testele de server relevante trec. Niciun test nu pornește serverul de producție sau accesează memorie reală.

## Decizii rămase / limite de producție

- Aprobarea V1 pentru deployment și orice mapare `no_op -> succeeded/complete` ori `rejected_before_write -> failed/none` rămâne separată și neacordată.
- Nu există proof schema pentru durable applied sau no-effect verificabil independent; niciunul nu este emis.
- Identitatea/provenance buildului activ Understory rămâne NECONFIRMATĂ.
- Clientul Rendiv, validatorul său, workerul și FIFO nu se schimbă aici; integrarea reală este etapă separată.
- Journal, idempotency, status, recovery, atomicitate, durability și exactly-once nu sunt implementate.

Nu începe integrarea reală sau etapa următoare.
