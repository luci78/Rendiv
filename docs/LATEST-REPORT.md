# Raport runtime Rendiv: Pithagoras–Understory

- **Data:** 2026-10-11
- **Subiect:** Verificarea runtime-ului, a căilor de scriere, a prioritizării inferenței și a recuperării după restart
- **Domeniu:** Inspecție read-only a documentației și codului Pithagoras/Understory; endpointuri llama.cpp numai GET pentru health/status. Nicio inferență, mutație MCP, repornire sau test cu efect asupra memoriei nu a fost declanșat.
- **Limitare:** Docker API a răspuns `permission denied` la `docker ps`, astfel nu a fost posibil `docker inspect` pentru configurația curentă a containerelor.

## Rezumat

Endpointul llama.cpp răspunde la verificările GET. Statusul routerului a raportat Qwen3.6-35B-A3B-Q5_K_M încărcat, iar verificarea slotului pentru acel model a raportat un slot inactiv în momentul interogării. Aceste rezultate descriu serverul la acel moment; nu demonstrează ce configurație au selectat fiecare dintre clienți.

Codul arată mai multe căi de scriere către Understory, dintre care apelurile MCP directe nu sunt serializate de coada internă Pithagoras pentru operațiile pornite de portal. Nu am putut enumera clienții activi din runtime. Pithagoras are SQLite persistent și recuperare pentru run-urile routines întrerupte; acestea nu constituie coada persistentă Rendiv.

## CONFIRMAT

### Runtime llama.cpp și configurația aplicațiilor

- GET `/health` a răspuns HTTP 200.
- GET `/v1/models` a listat Qwen3.6-35B-A3B-Q5_K_M printre modelele disponibile.
- GET `/models` a raportat Qwen3.6-35B-A3B-Q5_K_M cu status `loaded`.
- GET `/slots?model=Qwen3.6-35B-A3B-Q5_K_M` a raportat un slot și niciun slot `is_processing=true` la acel moment. Interogarea fără parametrul `model` a răspuns HTTP 400 cu mesajul că lipsește numele modelului.
- Contextul utilizatorului/documentația Rendiv consemnează o verificare anterioară `docker inspect` pentru Understory cu modelul Qwen3.6-35B-A3B-Q5_K_M și endpointul llama.cpp comun. Contextul anterior spune că Pithagoras folosește aceeași configurație, dar Pithagoras nu a fost reverificat atunci.
- Codul Pithagoras fixează `pi-mcp-adapter@2.18.0`. Configurația poate specifica timeout MCP global sau per server; documentația versiunii spune că, dacă `requestTimeoutMs` lipsește sau este `<= 0`, se folosește timeoutul implicit al MCP SDK. Contextul de proiect indică 60 s pentru acest implicit. [README pi-mcp-adapter v2.18.0](https://github.com/nicobailon/pi-mcp-adapter/blob/v2.18.0/README.md#server-options)
- Codul Pithagoras poate selecta modelul conversației care a inițiat cererea Understory și are fallback la modelul implicit. Configurația Understory suportă modurile auto/provider/custom. Prin urmare, codul singur nu fixează configurația runtime a fiecărei cereri.

### Clienți și căi de scriere găsite în cod

- **Pithagoras, tool-uri MCP directe:** integrarea creează serverul Understory cu `directTools: true`. Tool-urile de scriere Understory includ `memory_add`, `memory_update` și `memory_maintain`. Apelurile directe nu trec prin coada `exclusive` din `understory-service.ts`.
- **Pithagoras, API-ul portalului:** `PUT` și `DELETE /api/memory/concept`, plus `POST /api/memory/reindex`, `/repair`, `/clear-log` și `/wipe`. Serviciul portalului aplică aceste modificări prin propriul script/ruta de scriere în containerul Understory gestionat. Coada `exclusive` serializează anumite operații portal, nu toate apelurile MCP.
- **Understory, MCP:** codul oferă MCP streamable HTTP la `/mcp` și transport stdio. `memory_add`, `memory_update` și `memory_maintain` folosesc agentul intern și instrumentele sale de scriere.
- **Understory, chat web:** `POST /api/chat` folosește același agent cu tool-urile de citire și scriere; este deci o cale capabilă să modifice bundle-ul.
- **Understory, CLI:** README-ul documentează `pnpm agent:mutate` ca intrare CLI. Existența intrării nu dovedește că este folosită în runtime.
- `memory_status` raportează statistici/conformitate/health, nu starea unui job de mutație. API-urile GET de browse sunt de citire.

### Timeout și comportamentul codului la închidere

- `requestTimeoutMs` poate avea suprascriere globală sau per server; valoarea efectivă nu a putut fi inspectată fără configurația runtime, care nu a fost accesibilă prin Docker.
- Handlerul MCP HTTP Understory creează serverul/transportul pentru fiecare cerere și apelează `transport.close()` și `server.close()` când răspunsul HTTP se închide.
- Handlerele `memory_add`/`memory_update` apelează `runMutation()` fără un `AbortSignal` explicit în acest apel. Codul de transport observat nu demonstrează că expirarea clientului anulează operația internă.
- `runMutation()` poate întoarce un rezultat `partial` cu lista fișierelor schimbate. Aceasta confirmă că o mutație poate avea efecte parțiale raportate, nu că timeoutul produce întotdeauna un anumit rezultat.

### Detectarea activității llama.cpp

- Pithagoras are un proxy de progres pentru solicitările care trec prin el: poate citi progresul/timingurile streamului și starea de încărcare a modelului pentru sesiuni. Aceasta nu este un contor global al tuturor clienților care folosesc serverul comun.
- `session-manager.ts` urmărește intervalul unui run Pithagoras (`agent_start` până la `agent_settled`), nu fiecare inferență către llama.cpp; această stare nu trebuie tratată ca echivalent exact al slotului activ.
- Endpointul llama.cpp `GET /slots` oferă stare pe slot și câmpul `is_processing`; endpointul a răspuns cu un slot inactiv când a fost interogat cu modelul. Documentația upstream îl descrie ca endpoint de stare curentă a sloturilor. [llama.cpp server README: GET /slots](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#get-slots)

### Status, idempotency, persistență și restart

- `memory_status` este statusul bundle-ului/health-ului semantic, nu status de job.
- Understory persistă traces sub `.traces/`, iar rezultatul unei mutații poate conține `traceId`; acestea sunt urme de execuție după rulare, nu un contract de job durabil cu polling și nici o cheie de idempotency.
- Căutarea read-only în codul Understory nu a găsit un mecanism/contract de idempotency pentru mutații. Nu s-a identificat un endpoint de status pentru o mutație în curs.
- Pithagoras deschide `portal.db` cu `better-sqlite3`, activează `journal_mode = WAL` și aplică schema/migrațiile tranzacțional. Tabelul de events și starea routines sunt persistente.
- La pornire, `RoutineSupervisor` marchează run-urile rămase `running` drept `interrupted`; un one-off este dezactivat pentru a evita rerularea unei operații cu efect posibil parțial, iar programările sunt recalculate. Aceasta este recuperare specifică routines, nu recuperare generală a joburilor de memorie.
- Codul Understory descrie memoria ca bundle Markdown și traces ca fișiere. Montarea efectivă a volumului containerului și durabilitatea lui după restart nu au putut fi reverificate.

## NECONFIRMAT

- Valorile efective din environment pentru containerele Pithagoras și Understory în acest audit. Docker API local a refuzat accesul; configurațiile pot conține credențiale și nu au fost citite direct.
- Modelul/endpointul efectiv selectat de Pithagoras pentru toate sesiunile și de Understory la runtime. Statusul serverului spune că modelul este încărcat, nu care client îl folosește.
- Timeoutul MCP efectiv și orice override global/per server. 60 s este valoarea implicită indicată în contextul proiectului, nu o măsurătoare a configurației curente.
- Dacă o expirare MCP doar închide așteptarea clientului, anulează cererea serverului sau lasă agentul Understory să continue; nu a fost provocată o expirare pentru a testa acest lucru.
- Inventarul exhaustiv al clienților activi și al configurațiilor lor. Codul enumeră suprafețe posibile; Docker nu a permis enumerarea containerelor. Căutarea limitată în sursele Agentbox pentru referințe Understory/tool-uri nu a găsit potriviri, dar aceasta nu acoperă configurații ori clienți externi.
- Dacă `/slots` poate atribui o cerere unui client sau poate garanta acces prioritar; răspunsul observat este un instantaneu, nu o rezervare atomică.
- Orice coadă persistentă Rendiv: repository-ul conține documentație, nu implementarea unui worker sau storage de joburi.

## RISC

- Dacă clientul expiră după ce Understory a aplicat o parte sau toată mutația, retry-ul orb poate duplica efecte. Nu există garanție observată de idempotency la destinație.
- Apelurile MCP directe, chat-ul web Understory și alți clienți pot ocoli serializarea operațiilor portal Pithagoras și orice viitoare coadă Rendiv, dacă nu sunt rutate/restricționate explicit.
- Polling-ul `/slots` poate indica activitate, dar un slot inactiv poate deveni ocupat imediat după citire; endpointul nu acordă prioritate și nu atribuie activitatea unui client. Nu poate singur garanta că inferența conversațională Pithagoras nu așteaptă.
- Întreruperea brutală a unei operații Understory deja pornite poate lăsa scrieri parțiale; politica cerută este să nu fie întreruptă brutal pentru a aplica prioritatea conversațională.
- Politica de prioritate între loturile bufferului rămâne o decizie separată și nedecisă.

## Recomandare: arhitectura minimă Rendiv

1. Folosiți o coadă persistentă locală Rendiv, de exemplu SQLite cu tranzacții și lease/claim unic. Păstrați un identificator/idempotency key stabil, hash-ul lotului și stările `queued`, `running`, `succeeded`, `failed`, `unknown`.
2. Un singur worker trimite mutații către Understory. După restart, transformați `running` în `unknown`; după timeout nu relansați automat. Faceți read-back/reconciliere prin statusul disponibil sau verificarea efectului înainte de orice retry, iar dacă rezultatul nu poate fi stabilit păstrați-l pentru decizie explicită.
3. Rutați toate căile de scriere prin enqueue-ul Rendiv: Pithagoras MCP, API-ul portalului, chat-ul web Understory, CLI și orice client Home Assistant/extern. Înainte de a declara Rendiv singura poartă, inventariați configurile runtime fără a afișa credențiale și închideți bypass-urile.
4. Folosiți `GET /slots?model=...` ca semnal read-only pentru a amâna **pornirea** unui nou job cât timp sloturile sunt ocupate. Tratați-l doar ca semnal: prioritatea robustă cere coordonare la admiterea cererilor pe calea comună către llama.cpp. Nu întrerupeți brutal joburile Understory deja începute.
5. Nu deduceți prioritatea dintre loturi din prioritatea inferenței; păstrați ordinea lor configurabilă până la o decizie explicită.

## Dovezi și verificări efectuate

- Documente Rendiv citite: `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/LATEST-REPORT.md` și `docs/PITHAGORAS-UNDERSTORY-ANALYSIS.md`.
- Cod inspectat read-only: Pithagoras `features.ts`, `api/mcp.ts`, `api/memory.ts`, `memory-llm.ts`, `llama-progress.ts`, `extensions/understory-service.ts`, `db.ts`, `schema-version.ts`, `routines/supervisor.ts`; Understory `mcp/http.ts`, `mcp/stdio.ts`, `mcp/server.ts`, `api/chat.ts`, `api/browse.ts`, `core/agent.ts` și `core/trace.ts`.
- Endpointuri llama.cpp interogate numai prin GET: `/health` (200), `/v1/models`, `/models`, `/slots?model=...`. Răspunsurile au fost filtrate la ID/stare model și număr/stare slot; fără prompturi sau inferențe.
- `docker ps` a eșuat cu `permission denied` la socketul Docker. Nu s-au citit fișiere `.env`, `mcp.json`, secrete, bundle-uri de memorie sau baze de date.
- Nu s-au executat teste, apeluri MCP, scrieri, restarturi sau acțiuni de deployment.
