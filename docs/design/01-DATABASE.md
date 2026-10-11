# Rendiv: schema SQLite și tranzacții

- **Secțiune:** 01 — Proiectare Rendiv
- **Stare:** propunere tehnică; neimplementată și neaprobată pentru implementare
- **Data:** 2026-10-11
- **Arhitectură:** [`01-ARCHITECTURE.md`](01-ARCHITECTURE.md)

## 1. Principii

SQLite din Rendiv este sursa de adevăr pentru acceptarea joburilor, stări, deduplicare și audit. API-ul nu confirmă un enqueue până când tranzacția durabilă nu face commit. Cererea Understory se execută în afara tranzacției, astfel încât un apel care durează mult să nu țină lock-ul SQLite deschis.

Baza trebuie găzduită pe filesystem local durabil, cu locking SQLite funcțional și backup verificat. Calea exactă, volumul, criptarea și retenția sunt decizii de deployment încă deschise. Nu presupunem că un container Rendiv existent sau o bază Pithagoras este proprietarul acestei cozi.

## 2. Identități și deduplicare

- `job_id` este UUIDv7 aleatoriu generat la prima inserare și păstrat neschimbat pentru întreaga viață a jobului.
- Fiecare caller autentificat trimite un `Idempotency-Key` opac și stabil pentru aceeași intenție de scriere. Unicitatea este în domeniul principalului autentificat și al operației.
- Payloadul validat este serializat canonic (de ex. JCS/RFC 8785) împreună cu versiunea formatului și operația. Rendiv calculează SHA-256 peste reprezentarea canonică și stochează digestul binar de 32 bytes în `payload_sha256`.
- Aceeași identitate `(source_principal, operation, idempotency_key)` și același hash returnează jobul deja existent. Aceeași identitate cu hash diferit primește conflict și nu înlocuiește conținutul.
- Hash-ul este intern: nu se expune în API, loguri sau metrici. Hash-ul simplu poate permite ghicirea payloadurilor cu entropie mică; dacă threat model-ul o cere, adoptați HMAC-SHA-256 cu versiune de cheie înainte de implementare. Nu schimbați algoritmul implicit fără o decizie de migrare.
- Payload identic cu o cheie diferită nu se unește automat cu alt job. Hash-ul oferă integritate și identifică replay-ul aceleiași chei, nu deduplicare semantică.

## 3. Tabele și relații

DDL-ul este schiță de proiectare, nu migrație executată. Tipurile de timestamp sunt milisecunde UTC Unix; identificatorii sunt opaque. Schema finală trebuie verificată contra versiunii SQLite din runtime-ul Rendiv, care nu este încă stabilit.

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

CREATE TABLE jobs (
  job_id              TEXT PRIMARY KEY,
  source_principal    TEXT NOT NULL,
  operation           TEXT NOT NULL CHECK (operation IN ('memory_add','memory_update','memory_maintain')),
  idempotency_key     TEXT NOT NULL,
  payload_format      TEXT NOT NULL,
  payload_json        TEXT NOT NULL,
  payload_sha256      BLOB NOT NULL CHECK (length(payload_sha256) = 32),
  state               TEXT NOT NULL CHECK (state IN ('queued','running','succeeded','failed','unknown')),
  effect_certainty    TEXT NOT NULL CHECK (effect_certainty IN ('none','partial','complete','unknown')),
  queue_seq           INTEGER NOT NULL UNIQUE,
  attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  created_at_ms       INTEGER NOT NULL,
  updated_at_ms       INTEGER NOT NULL,
  started_at_ms       INTEGER,
  finished_at_ms      INTEGER,
  error_code          TEXT,
  UNIQUE (source_principal, operation, idempotency_key)
);

CREATE INDEX jobs_queued_seq ON jobs(state, queue_seq);
CREATE INDEX jobs_source_created ON jobs(source_principal, created_at_ms);

CREATE TABLE job_attempts (
  attempt_id          TEXT PRIMARY KEY,
  job_id              TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE RESTRICT,
  attempt_no          INTEGER NOT NULL CHECK (attempt_no > 0),
  dispatch_intent_at_ms INTEGER NOT NULL,
  worker_id           TEXT NOT NULL,
  UNIQUE (job_id, attempt_no)
);

CREATE TABLE worker_gate (
  singleton_id        INTEGER PRIMARY KEY CHECK (singleton_id = 1),
  gate_state          TEXT NOT NULL CHECK (gate_state IN ('free','occupied','uncertain')),
  active_job_id       TEXT REFERENCES jobs(job_id) ON DELETE RESTRICT,
  worker_id           TEXT,
  acquired_at_ms      INTEGER,
  CHECK (
    (gate_state = 'free' AND active_job_id IS NULL AND worker_id IS NULL) OR
    (gate_state IN ('occupied','uncertain') AND active_job_id IS NOT NULL AND worker_id IS NOT NULL)
  )
);

INSERT INTO worker_gate(singleton_id, gate_state, active_job_id, worker_id, acquired_at_ms)
VALUES (1, 'free', NULL, NULL, NULL);

CREATE TABLE job_events (
  event_seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id            TEXT NOT NULL UNIQUE,
  job_id              TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE RESTRICT,
  event_type          TEXT NOT NULL,
  from_state          TEXT,
  to_state            TEXT,
  effect_certainty    TEXT,
  actor_type          TEXT NOT NULL CHECK (actor_type IN ('caller','worker','operator','recovery')),
  actor_id            TEXT,
  occurred_at_ms      INTEGER NOT NULL,
  reason_code         TEXT,
  metadata_json       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX job_events_job_seq ON job_events(job_id, event_seq);

CREATE TRIGGER job_events_no_update BEFORE UPDATE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;
CREATE TRIGGER job_events_no_delete BEFORE DELETE ON job_events
BEGIN SELECT RAISE(ABORT, 'job_events is append-only'); END;
CREATE TRIGGER job_attempts_no_update BEFORE UPDATE ON job_attempts
BEGIN SELECT RAISE(ABORT, 'job_attempts is append-only'); END;
CREATE TRIGGER job_attempts_no_delete BEFORE DELETE ON job_attempts
BEGIN SELECT RAISE(ABORT, 'job_attempts is append-only'); END;
```

### Relații

- `jobs` este rădăcina: un job are zero sau mai multe `job_attempts` și unul sau mai multe `job_events`.
- `worker_gate` este singleton-ul care rezervă mutația globală. Cât timp starea este `occupied` sau `uncertain`, alt job nu poate fi trimis la Understory.
- `job_attempts` este append-only: fiecare dispatch intenționat primește rând nou. Rezultatul/închiderea attempt-ului se consemnează ca eveniment nou, nu prin editarea istoricului.
- `job_events` este auditul append-only al acceptării, tranzițiilor, rezultatelor și reconciliărilor. JSON-ul metadata conține doar coduri și identificatori tehnici; nu payload, token, prompt sau textul memoriei.
- `jobs` conține payloadul necesar procesării. Payloadul poate include date personale; retenția și criptarea la rest trebuie decise. Nu copiați payloadul în tabelele de audit.
- `queue_seq` oferă o ordine stabilă de sosire. Politica ce o folosește (FIFO sau echitate/priorități între surse) este încă nedecisă; nu codificați prioritatea inferenței Pithagoras în această coloană.

Schema nu folosește `ON DELETE CASCADE`: eliminarea unui job nu trebuie să șteargă auditul. Retenția payloadurilor poate fi implementată ulterior prin separarea payloadului în tabel criptat/expirabil, păstrând tombstone-ul idempotency și hash-ul conform politicii aprobate. Nu există încă o perioadă de retenție decisă.

## 4. Claim atomic și commit

Workerul folosește un singur gate, tranzacții scurte și niciun await de rețea în tranzacție:

```text
BEGIN IMMEDIATE
  citește worker_gate(id=1)
  dacă gate_state != free: ROLLBACK și nu trimite job
  selectează un queued conform politicii aprobate
  dacă nu există: ROLLBACK
  actualizează job: queued -> running, attempt_count + 1, started_at
  setează gate_state=occupied, active_job_id, worker_id, acquired_at
  inserează job_attempts și event claimed/dispatch_intent
COMMIT
apelează Understory în afara tranzacției

BEGIN IMMEDIATE
  actualizează starea finală și certitudinea efectului
  inserează event rezultat
  eliberează gate numai dacă rezultatul dovedește că execuția s-a terminat
COMMIT
```

În implementare, claim-ul trebuie protejat și împotriva a două procese worker locale concurente. Se poate folosi singleton-ul SQLite plus lock de proces local; un lease cu expirare nu eliberează singur gate-ul Understory, pentru că requestul upstream poate continua după ce workerul a pierdut contactul. Toate procesele Rendiv care folosesc SQLite trebuie să ruleze pe același host/filesystem local. Distribuirea bazei pe share de rețea sau pe mai multe hosturi este în afara soluției v1 până la verificarea locking-ului.

## 5. Deduplicare tranzacțională la enqueue

```text
validează caller, operație, idempotency key și payload limit
canonical_payload = canonicalize(payload_format, operation, payload)
digest = SHA256(canonical_payload)

BEGIN IMMEDIATE
  caută UNIQUE(source_principal, operation, idempotency_key)
  dacă există și hash egal: citește job_id/state și returnează replay=true
  dacă există și hash diferit: ROLLBACK; răspunde 409
  altfel inserează jobs(state=queued, effect_certainty=none, ...)
  inserează job_events(event_type=enqueued, to_state=queued)
COMMIT
răspunde 202 cu job_id și status_url
```

`queue_seq` este alocat monoton în aceeași tranzacție `BEGIN IMMEDIATE`; alegerea jobului după secvență sau după o politică de echitate rămâne separată. Dacă procesul cade înainte de commit, nu există job acceptat și clientul poate retrimite aceeași cheie. Dacă cade după commit dar înainte de răspuns, replay-ul întoarce jobul existent. Nu folosiți `INSERT OR REPLACE`, care poate șterge și recrea rândul, schimbând identitatea/istoricul.

## 6. Crash, timeout și recuperare

### La pornire

Într-o tranzacție de recuperare, orice job rămas `running` se schimbă în `unknown`, primește un event `recovered_unknown`, iar gate-ul devine `uncertain` pentru acel job. Joburile `queued` rămân queued. Procesul nu convertește automat `unknown` în `queued` și nu eliberează gate-ul pe baza unui lease expirat.

Un crash între commit-ul de claim și trimiterea efectivă a requestului poate produce `unknown` deși Understory nu a văzut requestul. Această clasificare conservatoare evită overlap-ul; operatorul poate elibera gate-ul doar după ce dovedește `no_effect` și că nu mai există execuție upstream.

### Clasificarea rezultatului

| Dovezi la Rendiv | Stare propusă | `effect_certainty` | Gate |
|---|---|---|---|
| Validare/auth/refuz local înainte de dispatch | `failed` | `none` | liber |
| Understory dovedește eșec terminal fără efect | `failed` | `none` | liber |
| Understory confirmă succes complet | `succeeded` | `complete` | liber |
| Understory răspunde că unele fișiere au fost scrise înainte de eșec | `failed` (detaliu partial) | `partial` | liber numai dacă răspunsul confirmă că handlerul s-a încheiat |
| Timeout, conexiune pierdută, crash după intent sau răspuns imposibil de clasificat | `unknown` | `unknown` | incert/ocupat |
| Operatorul confirmă aplicarea completă după read-back | `succeeded` | `complete` | liber |
| Operatorul confirmă no-effect și lipsa unei execuții active | `failed` sau `queued` după decizie explicită | `none` | liber după audit |

Un eșec HTTP/MCP nu este implicit „fără efect”: doar un contract verificat care garantează lipsa efectului permite `effect_certainty=none`. Pentru răspunsul parțial Understory, state-ul terminal tehnic este `failed`, dar operatorul vede clar efectul `partial`; acel job nu se reia automat.

### Recuperare și reconciliere

- Operatorul verifică `job_id`, attempt-ul, timpul și semnalele disponibile fără a retrimite mutația.
- Dacă efectul se poate confirma printr-un read-back sigur, adaugă un eveniment de reconciliere cu actor, cod motiv și rezultat; nu modifică evenimente vechi.
- Dacă e demonstrat că efectul nu s-a aplicat și nu există request activ, operatorul poate requeue-ui același job cu același `job_id`, prin tranziție auditată. Se adaugă un attempt nou; payloadul/hashul rămân identice.
- Dacă rezultatul rămâne ambiguu sau parțial fără cale sigură de reconciliere, jobul rămâne `unknown` și workerul nu pornește altă mutație. Acest fail-closed poate necesita intervenție și reduce disponibilitatea.

## 7. Durabilitate, backup și retenție

- WAL permite cititori concurrenți cu writer; `synchronous=FULL` este recomandarea de durabilitate inițială. Configurația finală trebuie validată pe versiunea SQLite efectivă și filesystem-ul ales.
- Backup-ul se face cu SQLite online backup API ori snapshot coerent documentat; nu copiați fișierul DB activ fără procedură care gestionează WAL. Păstrați `jobs`, `worker_gate`, `job_attempts` și `job_events` într-un backup consistent.
- Restore-ul pornește în mod de verificare: nu execută automat joburi `running/unknown`; le păstrează/transformă în `unknown` și cere reconciliere.
- Definiți retenție pentru payloaduri terminale, cheile idempotency și audit înainte de implementare. Auditul logic este append-only; arhivarea trebuie păstreze proveniența și să fie auditată. Hash-ul poate rămâne o amprentă de date și necesită aceeași protecție ca metadata sensibilă.
- Restricționați accesul OS la fișier și copii backup; stabiliți criptarea la rest, rotația cheilor și testul periodic de restore. Aceste capabilități nu sunt confirmate pentru un runtime Rendiv actual.

## 8. Criterii de acceptare

1. DDL-ul creează toate FK/check/unique constraints; DB respinge stări/certețuri invalide și reuse-ul cheii cu payload diferit.
2. Două enqueue concurente cu aceeași cheie/hash produc un singur job și același `job_id`; alt hash produce `409` fără schimbarea payloadului.
3. Două worker claims concurente nu pot ocupa poarta cu două joburi. La `unknown`, gate-ul împiedică claim-ul următor.
4. Toate modificările de stare, attempt-uri, rezultate și decizii de reconciliere produc evenimente append-only; update/delete pe audit/attempt e refuzat.
5. Crash înainte de commit-ul enqueue nu confirmă job; crash după commit permite idempotent replay; crash după claim marchează `unknown`, nu retry.
6. Timeoutul și eroarea cu efect neconfirmat nu sunt clasificate `failed/no_effect` și nu declanșează retry automat.
7. Backup/restore păstrează relațiile, auditul și gate-ul; după restore nu pornește automat un rezultat incert.
8. Payloaduri peste limita configurată sunt respinse cu răspuns stabil, fără trunchiere sau fragmentare tacită.

## 9. Decizii deschise

- Calea SQLite, filesystem local, topology de procese/worker și versiunea SQLite suportată.
- Limita de payload, backlog, retenția payload/idempotency/audit și dacă hash-ul va fi SHA-256 sau HMAC versionat.
- Dacă se păstrează payloadul în DB, se criptează la nivel de aplicație sau se folosește criptare de volum.
- Codurile exacte pentru refuz sigur, răspuns parțial, timeout și reconciliere Understory.
- Politica de ordonare a joburilor; `queue_seq` nu decide singur FIFO până la aprobarea politicii.
- Backup RPO/RTO, locație/retentie copii și rolul care poate rezolva `unknown`.
