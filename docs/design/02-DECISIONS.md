# Rendiv — decizii pentru prima implementare izolată

- **Secțiune:** 02 — Decizii arhitecturale Rendiv
- **Stare:** propuneri pentru aprobare; nimic din acest document nu este implementat
- **Data:** 2026-10-11
- **Baseline runtime:** [`../baselines/BASELINE-2026-10-11.md`](../baselines/BASELINE-2026-10-11.md)
- **Proiectare anterioară:** [`01-ARCHITECTURE.md`](01-ARCHITECTURE.md), [`01-DATABASE.md`](01-DATABASE.md), [`01-INTEGRATION.md`](01-INTEGRATION.md), [`01-CODEX-ADMIN.md`](01-CODEX-ADMIN.md)

## 1. Domeniu MVP și convenția de statut

Documentul stabilește propuneri concrete pentru o primă implementare izolată. Baseline-ul descrie containerele existente și câteva fluxuri externe, dar nu confirmă un runtime Rendiv, resursele disponibile ale VM-ului, locația de deploy, domeniul/reverse proxy-ul, autentificarea internă ori standardele operaționale locale. Nicio propunere de mai jos nu trebuie citită ca valoare runtime observată.

| Marcaj | Înțeles |
|---|---|
| **CONFIRMAT** | Susținut direct de baseline sau de documentația proiectului existentă; nu înseamnă că o propunere este deja implementată. |
| **PROPUS** | Recomandarea concretă pentru MVP, încă neaprobată și neimplementată. |
| **NECESITĂ APROBARE** | Operatorul trebuie să confirme valoarea/politica înainte de implementarea sau activarea relevantă. |

### Delimitare obligatorie MVP

MVP-ul conține numai:

- bază SQLite persistentă, cu migrații versionate și audit al acceptării;
- API autentificat pentru enqueue și status;
- validare, idempotency, stocare durabilă și răspuns asincron;
- stare inițială `queued` și citire status; fără componentă care să revendice sau să execute joburi.

MVP-ul **nu** conține dispatch/worker, gateway LLM, integrare Pithagoras sau Home Assistant, modificări Pithagoras/Understory, acces la `/mcp`, `/api/chat` sau bundle-ul Understory, acces la memoria reală ori administrator Codex activ. Nu este deployment de producție până când aprobările și criteriile de acceptare de mai jos nu sunt îndeplinite.

- **CONFIRMAT:** la baseline nu există cod Rendiv urmărit pentru coadă, worker sau API de enqueue; Pithagoras/Understory au căi de scriere în afara Rendiv descrise în baseline.
- **PROPUS:** API-ul primește intenții și le păstrează, dar nu le transmite nicăieri în MVP. Nu se pretinde că jobul a fost procesat semantic.
- **NECESITĂ APROBARE:** orice extindere de domeniu, inclusiv un endpoint de reconciliere sau acces administrativ la date.

## 2. Stack tehnologic API + SQLite

### Decizia propusă

- **PROPUS:** Python 3.12, FastAPI pentru API HTTP și `sqlite3` din biblioteca standard Python pentru DB; Pydantic pentru validarea DTO-urilor deja folosită de FastAPI. În implementare, API-ul va folosi endpoint-uri sincrone/DB calls scurte sau un executor dedicat, nu va rula operații SQLite blocante direct în event loop asincron.
- Un singur proces API și un singur fișier DB pe filesystem local. Pentru MVP nu există worker, broker, Redis sau serviciu de procesare.
- Container Linux fără privilegii, construit din imagine de bază pin-uită după verificarea suportului și a politicii de securitate. Versiunile Python, FastAPI și Pydantic se fixează într-un lockfile; imaginea se pin-uiește la digest în livrarea efectivă.

### Motiv și alternative

Acest stack oferă validare HTTP clară, cod compact pentru API-ul mic și driver SQLite inclus în Python, fără serviciu separat de broker. Un singur proces simplifică serializarea scrierilor și administrarea WAL pentru prima etapă. Cererile de enqueue/status nu trebuie să aștepte Understory, care nici nu este apelat în MVP.

- Node.js/TypeScript + Fastify + driver SQLite: alternativă rezonabilă dacă echipa are deja standarde de build/operare Node; driverul nativ și operarea asincronă a DB trebuie validate.
- Go + router HTTP + driver SQLite: alternativă potrivită pentru binar compact, dar introduce alegerea și mentenanța driverului SQLite în afara bibliotecii standard.
- PostgreSQL/Redis/broker extern: amânate, fiindcă adaugă servicii și operational burden fără cerință confirmată de debit/distribuție.

- **CONFIRMAT:** baseline-ul arată containere Docker existente, dar nu stabilește stack-ul sau imaginea pentru Rendiv și nici resursele VM.
- **PROPUS:** Python/FastAPI/sqlite3, un proces API inițial și fără dependențe de infrastructură suplimentare.
- **NECESITĂ APROBARE:** acceptarea Python ca standard, versiunea minoră suportată de imagine, politica de imagini/dependințe și resursele minime. Acestea se verifică fără a citi secrete și înainte de implementare.

## 3. Amplasarea, stocarea și izolarea

### Decizia propusă

- **PROPUS:** rulează serviciul Rendiv ca proiect/container separat pe VM-ul Docker existent numai dacă operatorul confirmă capacitatea, backupul și compatibilitatea de securitate. Separarea logică nu presupune că VM-ul are spațiu/resurse suficiente.
- Creează un director dedicat de date, de exemplu `/srv/rendiv/data`, proprietate a UID/GID non-root al serviciului, montat în container la `/var/lib/rendiv`. Acesta este nume de cale propus, nu constatare despre filesystem-ul VM-ului. DB, `-wal`, `-shm` și metadatele de backup rămân împreună pe același volum local.
- Nu monta directoare Pithagoras (`/data`, `/workspaces`), Understory (`/bundle`), workspace-ul rendiv-studio ori socket-ul Docker. Nu folosi volumele lor și nu modifica rețelele/proiectele Docker existente.
- Rețea proprie Rendiv, fără atașare la `ai-stack_default`, `rendiv-config_default` sau host network. În MVP API-ul este accesibil numai din interfața locală/loopback ori printr-un proxy privat aprobat; nu se publică port pe `0.0.0.0` implicit. Nu există egress spre Understory/llama.cpp.
- Serviciul are read/write doar pe propriul director DB și acces de rețea minim pentru callerii MVP. Identitățile viitoare Pithagoras/HA nu se adaugă înainte de integrarea aprobată.

### Motiv și alternative

VM-ul Docker deja existent este o destinație cu overhead redus, dar co-locarea nu trebuie să creeze legături de rețea, filesystem sau privilegiu cu serviciile AI. Directorul persistent dedicat permite backup independent și reduce riscul de atingere accidentală a bundle-ului. Alternativa unei VM separate oferă izolare mai bună și trebuie aleasă dacă nu se poate demonstra suficientă separare sau capacitate pe VM-ul actual.

- **CONFIRMAT:** Pithagoras folosește host network, Understory este într-un bridge și are bundle RW, iar rendiv-studio este într-o rețea separată. Aceste observații nu confirmă topologia serviciului viitor Rendiv.
- **PROPUS:** proiect/container Rendiv separat, director dedicat și rețea proprie; fallback la VM dedicată dacă izolarea nu poate fi asigurată.
- **NECESITĂ APROBARE:** VM-ul/host-ul concret, capacitatea CPU/RAM/disk, calea reală persistentă, backup target, bind address, TLS/proxy și ACL-urile firewall. Nu se aplică nicio schimbare de infrastructură în această etapă.

## 4. SQLite MVP, migrații, tranzacții și backup

### Tabele MVP

Schema MVP are trei tabele. Nu conține `worker_gate` sau `job_attempts`, deoarece în MVP nu există dispatch; acestea intră prin migrație înaintea workerului. Schema este propunere, nu DDL executat.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000; -- propunere inițială, de validat în acceptanță

CREATE TABLE schema_migrations (
  version       INTEGER PRIMARY KEY,
  applied_at_ms INTEGER NOT NULL,
  checksum      TEXT NOT NULL
);

CREATE TABLE jobs (
  job_id            TEXT PRIMARY KEY, -- UUIDv7 generat de API
  source_principal  TEXT NOT NULL,
  operation         TEXT NOT NULL CHECK (
    operation IN ('memory_add', 'memory_update', 'memory_maintain')
  ),
  idempotency_key   TEXT NOT NULL,
  payload_format    TEXT NOT NULL,
  payload_json      TEXT NOT NULL,
  payload_sha256    BLOB NOT NULL CHECK (length(payload_sha256) = 32),
  state             TEXT NOT NULL CHECK (
    state IN ('queued', 'running', 'succeeded', 'failed', 'unknown')
  ),
  effect_certainty  TEXT NOT NULL CHECK (
    effect_certainty IN ('none', 'partial', 'complete', 'unknown')
  ),
  queue_seq         INTEGER NOT NULL UNIQUE,
  created_at_ms     INTEGER NOT NULL,
  updated_at_ms     INTEGER NOT NULL,
  finished_at_ms    INTEGER,
  error_code        TEXT,
  UNIQUE (source_principal, operation, idempotency_key)
);

CREATE INDEX jobs_queued_fifo ON jobs(state, queue_seq);
CREATE INDEX jobs_source_created ON jobs(source_principal, created_at_ms);

CREATE TABLE job_events (
  event_seq       INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        TEXT NOT NULL UNIQUE,
  job_id          TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE RESTRICT,
  event_type      TEXT NOT NULL,
  from_state      TEXT,
  to_state        TEXT,
  actor_type      TEXT NOT NULL CHECK (
    actor_type IN ('caller', 'operator', 'recovery', 'system')
  ),
  actor_id        TEXT,
  occurred_at_ms  INTEGER NOT NULL,
  reason_code     TEXT,
  metadata_json   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX job_events_job_seq ON job_events(job_id, event_seq);

CREATE TRIGGER job_events_no_update BEFORE UPDATE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;
CREATE TRIGGER job_events_no_delete BEFORE DELETE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;
```

**Relații:** un job are unul sau mai multe evenimente; `job_id` este stabil și auditul are secvență append-only. Unicitatea principal+operație+idempotency key protejează acceptarea repetată. Nu se folosesc cascade delete. Payloadul este în `jobs`, niciodată duplicat în audit.

`running`, `succeeded`, `failed` și `unknown` sunt rezervate pentru viitorul worker/reconciliere; API-ul MVP creează numai `queued`. Nu există API public de schimbare a stării. `effect_certainty=none` la enqueue înseamnă că Rendiv nu a trimis jobul către o destinație mutativă; workerul nu există în MVP.

### Migrații și tranzacții

- **PROPUS:** migrații SQL numerotate, imutabile după publicare, executate la startup înainte ca API-ul să accepte trafic. `schema_migrations` înregistrează numărul și checksum-ul; checksum neașteptat oprește startup-ul fail-closed. O migrație incompatibilă necesită backup și procedură explicită, nu editarea în loc a unui migration aplicat.
- `foreign_keys=ON`, `journal_mode=WAL`, `synchronous=FULL`, `busy_timeout` limitat; verifică valorile efective la startup/log health fără a loga payloaduri. WAL este permis numai pe filesystem local cu locking SQLite corect, nu pe NFS/SMB sau volume de rețea fără validare dedicată.
- Enqueue: parse/validare/canonicalizare în afara tranzacției; apoi `BEGIN IMMEDIATE`, verificare idempotency, alocare `queue_seq`, inserare job + eveniment `enqueued`, COMMIT. Răspuns `202` numai după COMMIT.
- Replay cu aceeași cheie și hash întoarce același `job_id`; aceeași cheie cu alt hash răspunde `409` și nu schimbă jobul. Înainte de commit crash-ul nu acceptă jobul; după commit, dar înainte de răspuns, retry-ul cu aceeași cheie recuperează jobul.
- Status face o citire consistentă read-only și nu apelează sisteme externe. Nicio tranzacție nu rămâne deschisă pe durata unei cereri de rețea externe.

### Backup și restore

- **PROPUS:** backup consistent prin SQLite online backup API într-o destinație separată de volumul DB, cu acces restrâns și verificare checksum. Nu copia fișierul `.db` activ fără gestionarea WAL.
- MVP documentează și verifică procedura de backup/restore într-un director de test izolat. Politica de backup operată efectiv, criptare la rest, retenție off-host, RPO/RTO și alerte de backup nu sunt considerate implementate doar pentru că există cod pentru dump.
- Restore-ul MVP expune numai datele API; nu există worker care să execute joburile restaurate. În versiunea cu worker, orice job `running` la momentul backupului/restaurării devine `unknown`, nu se retrimite automat.
- **NECESITĂ APROBARE:** volumul și filesystem-ul real, metoda de criptare, retenția copiilor, locația independentă și obiectivele RPO/RTO.

## 5. API, autentificare, payload și idempotency

### Contract propus

`POST /v1/jobs` acceptă un singur job logic și nu execută mutația:

```http
POST /v1/jobs
Authorization: Bearer <credential serviciu cu scope>
Idempotency-Key: <cheie opacă stabilă>
Content-Type: application/json
```

```json
{
  "operation": "memory_add",
  "payload_format": "understory-v1",
  "payload": { "...": "document logic integral" }
}
```

Unicitatea idempotency este `(source_principal derivat din credential, operation, Idempotency-Key)`. Nu accepta principalul din body. Cheia este aceeași pentru retry de transport al aceleiași intenții, alta pentru o intenție nouă. Hash-ul SHA-256 intern acoperă versiunea formatului, operația și payloadul JSON canonicalizat conform unei implementări RFC 8785 verificate; nu se expune în API/log/metrică.

Răspuns nou sau replay identic:

```http
202 Accepted
```

```json
{
  "job_id": "<UUIDv7>",
  "state": "queued",
  "status_url": "/v1/jobs/<UUIDv7>",
  "created_at": "<UTC timestamp>"
}
```

`GET /v1/jobs/{job_id}` returnează numai starea, timestamps, operația, codul de eroare sigur și referințele de audit permise; nu returnează payload, hash, prompt, conținut de memorie sau credentiale. Callerul poate citi numai joburile principalului său; rolul operator se proiectează separat.

### Validare și limite

- **PROPUS:** `Content-Type` strict JSON, UTF-8 valid, schemă versionată, allowlist de operații, respingere câmpuri necunoscute, URL-uri/comenzi/tool names arbitrare și corpuri duplicate sau ambigue.
- **PROPUS, necesită aprobare:** plafon inițial `max_payload_bytes=262144` bytes UTF-8 după canonicalizare. Se măsoară în bytes, respinge oversize cu `413`, nu trunchiază și nu fragmentează batch logic HA. Limita trebuie validată cu exemple reale non-sensibile înainte de integrare.
- **PROPUS, necesită aprobare:** limita idempotency key de 128 caractere ASCII din setul `[A-Za-z0-9._:-]`; cheile nu conțin PII sau payload.
- Rate limit per principal și plafon global backlog sunt obligatorii; cifrele se configurează numai după evaluarea volumelor/discului. La saturație se răspunde documentat cu `429`/`503`; nu se confirmă job care nu a fost durabil înregistrat.
- Coduri: `400/422` input invalid, `401/403` identitate/scope, `409` reuse cheie cu hash diferit, `413` prea mare, `429` limitare, `503` indisponibil/saturat. Body-ul erorii nu conține payload ori detaliu secret.

### Autentificare și acces

- **PROPUS:** bearer tokens service-to-service diferite per caller, scope minim; TLS la proxy/reverse proxy privat când traficul iese din loopback. Tokenurile sunt furnizate din secret manager sau mecanism aprobat, nu din repo/DB/payload. API validează identitatea și ACL-ul server-side.
- API status nu dezvăluie existența joburilor altui principal. Endpointurile operatorului au rol separat și nu intră în MVP decât dacă sunt necesare pentru observarea joburilor tuturor.
- **NECESITĂ APROBARE:** mecanismul real de emitere/rotație/revocare, secret manager, TLS terminator și identitățile surselor. Nu se adaugă credentiale Pithagoras/HA în MVP.

## 6. FIFO și posibilitatea priorităților viitoare

- **PROPUS:** FIFO global strict pe `queue_seq` pentru viitorul worker, cu secvență alocată în aceeași tranzacție ca enqueue-ul. MVP păstrează `queue_seq` și îl afișează numai ca ordine de acceptare; nu revendică și nu procesează nimic.
- FIFO este ușor de explicat, auditat și testat pentru prima implementare. Nu adaugă prioritizare între callerii Pithagoras și Home Assistant. Nu există prioritate de inferență în schema de ordonare a joburilor.
- O schimbare ulterioară către clase/priorități necesită decizie aprobată, migrație explicită, reguli de fairness/starvation, metrici de așteptare și un test de stabilitate. Nu suprascrie retroactiv ordinea joburilor deja acceptate fără politică de migrare.
- Prioritatea inferenței conversaționale necesită gateway/admitere LLM comună și este separată: nu întrerupe mutații Understory active, nu se obține prin FIFO și nu se deduce din `GET /slots`.
- **CONFIRMAT:** prioritatea relativă a joburilor este nedecisă în proiectarea anterioară; Pithagoras/HA sunt surse distincte, HA trimite lot logic, Understory face organizarea semantică.
- **PROPUS:** FIFO global ca politică inițială, ulterior schimbabilă numai prin decizie/migrare.
- **NECESITĂ APROBARE:** acceptarea FIFO drept default pentru workerul post-MVP și orice excepție de fairness.

## 7. Stări, crashuri și rezultate necunoscute

API-ul MVP creează joburi numai în `queued`. Stările finale din proiectare rămân `queued`, `running`, `succeeded`, `failed`, `unknown`; numai workerul viitor le poate modifica prin tranziții autorizate.

| Situație | MVP (fără dispatch) | Comportament viitor propus |
|---|---|---|
| Crash înainte de commit enqueue | Niciun job confirmat; callerul retrimite cu aceeași cheie | Același |
| Crash după commit, înainte de răspuns | Jobul rămâne `queued`; replay returnează același ID | Același |
| Restart API cu joburi queued | Rămân queued; niciun efect extern | Workerul le poate revendica după startup/recovery aprobat |
| Crash după claim/intent de dispatch | Nu poate apărea în MVP | `running` devine `unknown`, gate-ul devine uncertain; fără retry automat |
| Timeout/deconectare după dispatch | Nu poate apărea în MVP | `unknown` dacă efectul/terminarea nu sunt demonstrate |
| Refuz demonstrat înainte de dispatch | Nu poate apărea în MVP | `failed`, `effect_certainty=none` și gate liber |
| Succes complet confirmat | Nu poate apărea în MVP | `succeeded`, `complete`; audit și eliberare gate numai după dovada terminării |
| Efect parțial sau răspuns ambiguu | Nu poate apărea în MVP | audit parțial/`unknown`; fără retry automat |

La pornire MVP-ul validează migrațiile și conectivitatea la DB, nu procesează joburi. Versiunea cu worker trebuie să marcheze prudent orice `running` recuperat ca `unknown`, să păstreze gate-ul uncertain și să aștepte reconciliere umană. Un lease expirat nu dovedește că upstream-ul a oprit mutația. `unknown` nu este sinonim cu eșec și nu autorizează retry.

- **CONFIRMAT:** Understory nu are în baseline status durabil per mutație sau idempotency confirmate; timeoutul nu dovedește anularea.
- **PROPUS:** fail-closed și fără dispatch MVP; pentru worker ulterior, recovery `running -> unknown` și reconciliere explicită.
- **NECESITĂ APROBARE:** contractele no-effect/partial cu Understory, persoanele autorizate la reconciliere și pragurile de intervenție.

## 8. Retenție, audit, metrici și verificare

### Retenție și audit

- **PROPUS pentru MVP:** păstrează payloadul cât timp jobul este pending și până există o politică aprobată; nu oferă ștergere implicită din API. Folosește limită de backlog/disk și refuz fail-closed la atingere. Această soluție temporară simplă poate păstra date mai mult decât este necesar, deci MVP-ul nu acceptă payloaduri cu date personale/sensibile până la aprobarea politicii.
- Tabelul `job_events` este append-only prin trigger DB; păstrează acceptare, replay/conflict, refuzuri sigure și intervenții administrative viitoare. Nu se scrie payload, hash, token, text de memorie, prompt sau date personale în audit/loguri.
- Nicio perioadă numerică de retenție nu este confirmată. **NECESITĂ APROBARE:** termenul payload, termenul idempotency tombstone după ștergerea payloadului, auditul, backup-urile și criptarea la rest. Retenția nu se implementază prin delete care rupe audit/idempotency.

### Metrici și verificare

MVP-ul expune health/status minim: readiness, livelock/capacitate DB, număr joburi per stare, cel mai vechi queued, rata enqueue acceptat/conflict/refuz și spațiul DB. Etichetele au cardinalitate limitată; fără caller arbitrar, `job_id`, hash sau payload ca label. `/metrics`, dacă este activat, e privat și nu conține date de job individuale.

Auditul SQLite este sursa de adevăr pentru acceptări; logurile includ request correlation ID, principal tehnic, rezultat/cod și durată, dar nu Authorization header sau body. Verificarea se face prin health check read-only, integritate SQLite la proceduri de mentenanță aprobate, backup checksum și restore periodic izolat. Nu se rulează `VACUUM`, checkpoint agresiv sau operație de mentenanță pe producție fără runbook/aprobare.

- **NECESITĂ APROBARE:** prag backlog/disk, SLO enqueue/status, retenția logurilor, endpointul de metrici, paging/owner, RPO/RTO și frecvența restore-ului.

## 9. Testare izolată, fără Understory real

Testele sunt planificate pentru implementarea ulterioară; nu sunt executate în această sarcină. Niciun test nu folosește endpointul real, tokenuri, bundle, memorie ori container Understory.

1. **Unitate — validare/API:** payload valid/invalid, UTF-8, operație nepermisă, cheie invalidă, limita bytes, response codes și redactarea erorilor.
2. **SQLite temporar:** migration fresh/upgrade, FK/CHECK/UNIQUE, append-only triggers, queue sequence și hash payload; folosește DB temporară într-un director de test, niciodată volumul persistent.
3. **Idempotency concurentă:** două enqueue-uri simultane cu aceeași principală/cheie/hash întorc același `job_id`; același key cu alt payload produce `409` și păstrează primul rând.
4. **Crash consistency:** fault injection înainte de commit nu lasă job acceptat; crash după commit înainte de răspuns permite replay. Verifică tranzacția job + event indivizibilă.
5. **Status și ACL:** principalul citește propriul job, nu poate enumera jobul altuia; endpoint status nu returnează payload/hash/secrete.
6. **Izolarea de rețea:** testul pornește API-ul într-un network namespace/container fără egress către Understory, MCP, llama.cpp ori internet (în afara endpointurilor strict aprobate pentru teste); dovedește că enqueue/status nu fac conexiuni externe. MVP-ul nu conține cod de dispatch.
7. **Backup/restore:** SQLite online backup către destinație temporară, verificare integritate și citire după restore; niciun serviciu extern conectat.
8. **Load și locking:** concurență realistă pentru API single-process, busy timeout, dimensiunea DB și răspunsul la disk/backlog; limitele sunt stabilite înainte de integrare pe baza VM-ului aprobat.
9. **Viitor worker (în etapă distinctă):** numai după aprobarea/implementarea workerului, folosește un fake MCP server local care simulează success/no-effect/partial/hang/close/crash. Testul verifică serializare, `unknown`, gate și lipsa retry-ului. Nu se testează pe Understory real.

Fiecare etapă de implementare are criteriile de acceptare, comenzile exacte de test și rezultatele în raportul acelei etape. Nici testele de acceptanță nu justifică scrieri în memoria reală.

## 10. Integrarea ulterioară

- **Pithagoras:** ulterior, schimbă doar scrierile pentru sursa pilot astfel încât să folosească enqueue și să primească `job_id`; citirea se decide separat. Dezactivează direct-write numai după verificarea endpointului, ACL-ului, statusului și rollback-ului. Configurația runtime a MCP Pithagoras rămâne de confirmat.
- **Home Assistant:** trimite fiecare lot logic ca un job și folosește o cheie stabilă per intenție. Rendiv validează/păstrează batch-ul integral; Understory păstrează organizarea semantică. Schema HA, event ID și limitele trebuie aprobate.
- **Worker:** etapa ulterioară adaugă `job_attempts`, `worker_gate`, dispatch MCP strict allowlist, un singur job mutativ activ, audit, recovery `unknown` și reconciliere. Workerul nu este parte din MVP-ul actual.
- **Gateway LLM:** etapă separată după inventarierea tuturor clienților modelului. Un gateway comun poate programa inferențele interactive Pithagoras înaintea noilor cereri background Understory, fără să oprească operații începute. `GET /slots` nu rezervă/admite atomic. Acest gateway nu schimbă ordinea FIFO a joburilor.
- **Administrator Codex:** ulterior, adaptor separat read-only cu sandbox și API administrativ redactat. Nu este worker, nu accesează MCP/memoria și nu este activ în MVP. Orice intervenție rămâne aprobată și auditată.
- **Bypass-uri:** Pithagoras MCP direct, `/mcp` accesibil din rețea, `/api/chat`, CLI/scripturi și acces la `/bundle` trebuie inventariate și controlate treptat înainte de a afirma că Rendiv este poarta unică.

Toate integrările se fac per sursă după pilot izolat, cu rollback fără fallback automat la o mutație directă pentru același job incert. Nu se presupune că `rendiv-studio` aparține proiectului sau este UI-ul Rendiv.

## 11. Riscuri și dependențe

| Risc/dependență | Consecință | Control/decizie |
|---|---|---|
| Capacitatea, filesystem-ul și backupul VM necunoscute | Disk plin, locking nesigur sau lipsă de recuperare | Confirmare operator înainte de calea persistentă și deployment |
| Păstrarea payloadului poate include PII | Expunere și retenție excesivă | Allowlist date, limită payload, criptare și retenție aprobate înainte de producție |
| SQLite single writer | Blocarea cererilor la concurență mare | Un proces API pentru MVP; măsurare izolată; reevaluare dacă debitul cere alt DB |
| Chei/ACL neproiectate la deployment | Acces caller neautorizat ori disclosure status | Bearer scoped, TLS privat și teste negative de ACL |
| Căi directe de scriere externe persistă | Worker ulterior nu garantează serializare globală | Inventar și cutover gradual înainte de activarea dispatch-ului |
| Timeout MCP/no-effect nedovedit | Mutație dublă sau rezultat ambiguu | Nu există dispatch în MVP; worker ulterior fail-closed și reconciliere |
| Aprobări pentru stack și stocare întârzie | MVP nu poate fi instalat în siguranță | Aceste aprobări sunt gate-uri, nu valori presupuse |
| Limite rate Codex/LLM necunoscute | Afectează numai viitoarele integrări | În afara MVP-ului; bugete și auth se confirmă separat |

## 12. Criterii de acceptare verificabile

MVP-ul este acceptat numai dacă toate sunt demonstrabile într-un mediu izolat:

1. API-ul pornește pe stack/versiuni pin-uite și refuză să pornească la migration checksum greșit ori config DB neconform.
2. SQLite este pe director dedicat local, cu owner non-root; containerul nu are Docker socket, mount Pithagoras/Understory/bundle sau acces la rețelele lor.
3. Enqueue valid răspunde `202` după commit și returnează un `job_id` stabil; aceeași cheie/hash întoarce același job; cheia cu hash diferit răspunde `409` fără overwrite.
4. În MVP toate joburile nou create rămân `queued`, iar codul/deploy-ul nu are worker, endpoint MCP sau rută de dispatch.
5. `GET /v1/jobs/{id}` respectă tenant/principal ACL și nu returnează payload, hash, token, prompt ori text de memorie.
6. Inputul peste limita aprobată este respins `413`, fără trunchiere; batch logic nu se fragmentează.
7. Jobul și evenimentul `enqueued` sunt atomice; crash-ul înainte/după commit are comportamentul stabilit în secțiunea 4.
8. Auditul append-only este protejat de constraint/trigger și nu conține corpul cererii ori credențiale; logurile și metricile sunt verificate pentru redacție.
9. API-ul rulează cu egress către Understory, MCP, llama.cpp și Docker absent; testele cu fake-uri dovedesc izolarea.
10. Backup-ul/restaurarea într-un director temporar păstrează jobs, chei/idempotency și audit și trece verificarea integrității.
11. Metricile nu folosesc `job_id`, hash sau principal arbitrar ca etichete și funcționează fără Codex.
12. Nicio integrare Pithagoras/HA, worker, gateway LLM ori administrator Codex activ nu este prezentă în pachetul MVP.

## 13. Pași mici și checkpoint-uri Git

Fiecare checkpoint este un commit separat numai pentru fișierele etapei; după etapă se rulează testele izolate desemnate, `git diff --check`, revizie de scope și confirmare manuală că nu există fișiere generate/secrete. Push-ul se face numai după acceptarea checkpoint-ului și conform aprobării operatorului; deployment-ul este o aprobare separată.

| Etapă | Livrabil | Teste/acceptare | Checkpoint propus |
|---|---|---|---|
| 0. Gate-uri și schemă | Decizii aprobate: stack, VM/path, auth, limite, retenție, backup | Revizie threat model și confirmare operator; fără runtime change | `docs: approve isolated MVP decisions` |
| 1. Schelet API | App FastAPI, config fără secrete, health/readiness, migrații versionate | Pornire locală/CI fără Docker extern; migration checksum; `diff --check` | `feat: add isolated Rendiv API skeleton` |
| 2. SQLite + enqueue | Schema jobs/events, canonicalizare, hash, FIFO sequence, tranzacții | Unit/SQLite temp, idempotency concurentă, failure injection commit | `feat: persist Rendiv enqueue requests` |
| 3. Status + auth | `GET` status, bearer per principal, ACL și rate/payload limits | Teste API negative ACL, redaction, 413/409/429 și status | `feat: add authenticated Rendiv job status API` |
| 4. Izolare container | Image non-root, compose/proiect izolat, volume propriu și firewall/egress deny | Scan/config review, test că nu există mount/network extern și API funcționează offline | `build: isolate Rendiv MVP runtime` |
| 5. Backup + observabilitate | SQLite backup/restore runbook, metrici/health, praguri aprobate | Backup + restore temporar, integrity check, log/metric redaction | `ops: document Rendiv MVP recovery and metrics` |
| 6. Acceptanță pre-integrare | Raport teste, limitări, inventory al bypass-urilor și aprobare MVP | Toate criteriile secțiunii 12; nicio conexiune Understory reală | `docs: record isolated MVP acceptance` |

Numele commiturilor sunt convenții propuse, nu operații efectuate. Utilizatorul/operatorul trebuie să aprobe implementarea și fiecare schimbare infrastructurală înainte de execuție. Workerul, gateway-ul LLM și Codex administrator sunt proiecte ulterioare cu propriile aprobări și checkpoint-uri.

## 14. Aprobări operator necesare înainte de implementare

1. Acceptarea Python/FastAPI/sqlite3 și a imaginii/versionării suportate.
2. Alegerea VM-ului sau a unei VM separate, calea persistentă reală, owner/permisiuni și rețeaua/bind address.
3. Capacitatea disk/backup, criptarea, retenția și RPO/RTO; mai ales dacă MVP poate accepta payloaduri cu PII.
4. Limita payload (propus 256 KiB), formatul strict, limita idempotency key și rate/backlog thresholds.
5. Bearer/token issuance, TLS/proxy și roluri pentru caller/operator.
6. Aprobarea politicii FIFO pentru etapa worker, separată de orice prioritate a inferenței.
7. Criteriile de restore, retenția auditului și proprietarul on-call.
8. Confirmarea că faza următoare rămâne izolată fără Understory real și că deployment-ul nu este inclus implicit în implementarea MVP.

Până la aceste aprobări, documentul este o propunere de decizii; nu implementează, nu schimbă infrastructura și nu autorizează conectarea la serviciile/memoria existente.
