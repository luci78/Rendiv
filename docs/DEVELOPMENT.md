# Dezvoltare și progres

## Etape

| Etapă | Rezultat urmărit | Stare |
|---|---|---|
| 1. Documentarea sistemului | Reguli Codex, arhitectură cunoscută/neconfirmată și plan de lucru | Încheiată prin această inițializare |
| 2. Confirmarea contractelor | Verificarea API-urilor MCP, timeouturilor efective, statusului operațiilor și posibilităților de deduplicare | Neîncepută; analiza de cod este documentată, verificările runtime lipsesc |
| 3. Proiectarea cozii | Schema persistentă, priorități, serializare, recovery, verificarea după timeout și politica anti-duplicate | Neîncepută |
| 4. Implementarea bufferului Rendiv | Acceptare asincronă, procesare serială și integrare cu sistemele sursă/destinație | Neîncepută; nu este autorizată în această etapă |
| 5. Backup, recuperare și monitorizare | Online backup SQLite, verificare/restaurare izolată și agregate read-only | Încheiată local; numai DB temporare, fără deployment |
| 6A. Worker local simulat | Claim FIFO serial, tranziții și audit atomic cu executor fictiv | Validată local și într-un container Docker temporar; fără worker automat sau executor extern |
| 6B. Integrare Understory | Adaptor/protocol fake și audit static al contractului; fără transport real | 6B.2B simulat și 6B.2C aplicat; 6B.2D documentat. Integrarea reală rămâne neîncepută |

La inițializarea documentară, etapele de implementare 2–5 nu fuseseră executate. Progresul curent al codului este urmărit separat mai jos.

## Decizii și cerințe consemnate

- Procesarea memoriei trebuie scoasă din calea conversației interactive.
- Coada trebuie să fie persistentă și să trimită serial către Understory.
- Inferența conversațională Pithagoras are prioritate față de procesarea AI Understory pe serverul llama.cpp comun.
- Prioritatea relativă între loturile din coadă este o decizie separată și rămâne nedecisă.
- O expirare MCP la 60 s, în timp ce Understory poate lucra câteva minute, cere verificarea stării înainte de orice retry.
- Deduplicarea trebuie să prevină repetarea efectelor după timeout, întrerupere sau restart.
- Home Assistant trimite loturi logice; Understory face organizarea semantică.
- Verificarea runtime Understory raportată de utilizator prin `docker inspect`: `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M` și `LLM_API_BASE_URL=http://192.168.20.30:8080/v1`.
- Pithagoras folosește aceeași configurație conform contextului anterior, dar nu a fost reverificat în această etapă.
- Detectarea activității llama.cpp nu este confirmată ca implementată și trebuie investigată ca parte a proiectării priorității inferenței.
- Nicio componentă externă și nicio memorie existentă nu se modifică în etapa de documentare.

## Jurnalul acestei inițializări

- Rendiv-project era gol, cu excepția metadatelor Git.
- Au fost inspectate read-only fragmente relevante din codul Pithagoras și README/codul Understory, fără citirea configurațiilor de secrete.
- Codul Pithagoras confirmă integrarea MCP Understory existentă și rutarea modelului pentru unele cereri Understory; nu confirmă coada Rendiv cerută.
- Nu au fost rulate teste, apeluri MCP, servicii sau comenzi de deployment. Nu s-au modificat proiectele externe și nu s-a făcut commit.

## Corectare documentară ulterioară

- Separată prioritatea inferenței conversaționale Pithagoras față de Understory de ordinea loturilor din coadă, care rămâne nedecisă.
- Înregistrată verificarea runtime Understory prin `docker inspect`, precum și faptul că runtime-ul Pithagoras nu a fost reverificat în această etapă.
- Marcată investigarea detectării activității llama.cpp drept lucru deschis; nu se afirmă că este deja implementată.

## Progres implementare Rendiv API

| Etapă | Rezultat urmărit | Stare |
|---|---|---|
| 1. Schelet API | Configurație tipată, health/readiness, migrații SQLite checksum/fail-closed și teste izolate | Încheiată local; fără deployment sau bază persistentă de producție |
| 2. SQLite + enqueue | Persistență joburi, idempotency și audit | Încheiată local; numai strat intern, fără rută publică |
| 3. API autentificat | Enqueue/status, bearer per principal, limite și ACL | Încheiată local; fără deployment sau integrare externă |
| 4. Containerizare izolată | Imagine non-root, Compose intern, volum configurabil și instrucțiuni de operare | Validată în proiect Docker temporar; fără deployment |
| 5. Backup și observabilitate | Online backup/verificare/restaurare și agregate read-only | Încheiată local; fără endpoint de administrare sau deployment |
| 6A. Worker local simulat | Claim FIFO serial, audit și stări conservatoare prin executor injectat | Validată cu teste și harness Docker temporar; fără executor real, API startup sau deployment |
| 6B. Adaptor/protocol Understory | Contract tipizat și transport MCP simulat, apoi audit de certitudine | Numai fake; fără transport real sau worker de producție |

### Etapa 1 — schelet API (2026-10-11)

- Scope: numai aplicație FastAPI, setări non-secrete tipate, `/healthz`, `/readyz` și infrastructură de migrații versionate cu SHA-256 și refuz la checksum/schema neconformă.
- Testele folosesc fișiere SQLite în directoare temporare; aplicația nu creează automat directorul părinte configurat. Nu se configurează endpointuri de job, enqueue/status, worker, MCP sau acces la servicii externe.
- Acceptanța locală: 9 teste trecute cu Python 3.12.3; `git diff --check` trece. Dependențele de test au fost instalate numai în `/tmp/rendiv-stage1-venv`; nu a fost pornit serviciul API.
- Nu s-a creat bază persistentă de producție și nu s-a modificat infrastructură externă. Aplicația nu implementează jobs/enqueue/status sau dispatch.

### Etapa 2 — SQLite + enqueue intern (2026-10-11)

- Migrația `0002_jobs_and_events.sql` adaugă tabelele `jobs`/`job_events`, constrângeri, indecși și trigger-e append-only; ștergerea joburilor este blocată pentru a păstra idempotency și secvența FIFO. Ledger-ul înregistrează checksum SHA-256.
- `EnqueueRepository` validează operația/identitatea/payloadul, folosește RFC 8785 și SHA-256, UUIDv7 și tranzacția `BEGIN IMMEDIATE` pentru queue sequence FIFO, job și evenimentul `enqueued`.
- Replay-ul cu aceeași identitate/hash întoarce jobul fără eveniment nou; hash diferit refuză fără modificări. Fiecare writer setează și verifică foreign keys, WAL, synchronous FULL și busy timeout. Ready/checksum/schema neconforme blochează enqueue înainte de scriere și se reverifică în tranzacție.
- API-ul public `POST /v1/jobs`, status, workerul, dispatch-ul și orice conexiune externă rămân absente. Testul de rețea interzice explicit socket connect în timpul enqueue-ului.
- Verificare locală: 24 teste PASS cu SQLite exclusiv în directoare temporare; `pip check` și `git diff --check` PASS. Dependințele au fost folosite din venv temporar; nu s-a creat DB persistentă și nu s-a pornit serviciu.

### Etapa 3 — API autentificat (2026-10-11)

- `POST /v1/jobs` acceptă numai corp JSON strict cu `operation` și obiectul `payload`; câmpurile suplimentare, inclusiv `source_principal`, sunt respinse. `Idempotency-Key` este obligatoriu. Răspunsul `202` este construit numai după ce repository-ul confirmă COMMIT; replay-ul identic întoarce același job, iar hash diferit produce `409`.
- `GET /v1/jobs/{job_id}` selectează numai metadate și filtrează în SQL după principalul derivat din bearer token. Joburile altui principal și ID-urile inexistente răspund identic cu `404`. Payloadul, hashul, cheia de idempotency și principalul nu apar în răspuns.
- Tokenurile sunt configurate numai prin `RENDIV_API_TOKENS_JSON` ca mapare principal–token și stocate în setări `SecretStr`; middleware-ul compară digesturi cu `compare_digest`, verifică toate intrările și autentifică înainte de citirea corpului. Tokenurile pentru teste sunt generate în memorie.
- Corpul HTTP este limitat la 272 KiB, payloadul RFC 8785 la 256 KiB; JSON-ul duplicat/ambiguu este refuzat. Limitele implicite conservatoare pentru dezvoltare/test sunt 10 cereri per principal per 60 s și backlog de 1.000 joburi `queued`. Limitarea ratei este în memorie, per proces; pragurile operaționale și dimensionarea trebuie aprobate înainte de deployment. Configurația `production` refuză pornirea dacă lipsesc tokenuri sau dacă limitele nu sunt explicite.
- Erorile publice folosesc răspunsuri generice: `400/422` validare, `401` autentificare, `404` job inaccesibil/inexistent, `409` conflict idempotency, `413` dimensiune, `429` rată/backlog și `503` DB/schema indisponibilă. Erorile neașteptate nu includ detalii sau stack trace.
- Backlogul este verificat sub aceeași tranzacție `BEGIN IMMEDIATE`; replay-ul valid se rezolvă înaintea pragului backlog. Readiness/checksum/schema se verifică la enqueue/status, iar orice indisponibilitate refuză operația. Migrațiile existente nu au fost schimbate.
- Verificare locală: 38 teste PASS, inclusiv ACL, autentificare, replay/conflict, JSON strict, payload/body limits, rate/backlog, schema/DB indisponibilă, concurență, redactare și interdicția de socket extern. Testele folosesc SQLite temporar și ASGI client în proces. Dependențele sunt folosite din `/tmp/rendiv-stage1-venv`; fără serviciu permanent, DB de producție sau conexiune la sisteme externe.
- Înainte de deployment rămân necesare aprobarea limitelor 10/60 s, backlog 1.000, overhead-ul de corp 16 KiB și configurația TLS/reverse proxy; limitatorul local presupune un singur proces și se resetează la restart. Nu există worker/dispatch, integrare Pithagoras/Understory/Home Assistant, MCP, gateway LLM ori administrator Codex.

### Etapa 4 — containerizare izolată (2026-10-11)

- `Dockerfile` are două etape, folosește tag-ul oficial Python 3.12.15 slim Bookworm ([Docker Official Images](https://github.com/docker-library/official-images/blob/master/library/python)), instalează exclusiv versiunile exacte din `requirements.lock` și rulează Uvicorn cu un singur worker sub UID/GID 10001. Imaginea runtime nu copiază teste, documente, fișiere locale sau baze. Pentru că imaginea slim nu conține `groupadd`, directoarele aplicației sunt create și atribuite UID/GID 10001 prin Python, fără pachet de sistem suplimentar.
- `.dockerignore` exclude `.env`, chei/certificate, secrete denumite, SQLite și sidecar-urile WAL/SHM, cache-uri, virtualenv, metadatele Git și fișierele de test/documentație.
- `compose.yaml` definește numai serviciul Rendiv, o rețea Compose dedicată `internal`, un volum named dedicat configurabil și portul containerului doar prin `expose`; nu are `ports`, `privileged`, socket Docker, host networking, mount-uri sau rețele externe. Root filesystem este read-only, capabilitățile sunt eliminate, iar singura cale persistentă RW este `/var/lib/rendiv`.
- Configurația `production` cere tokenurile din `RENDIV_API_TOKENS_JSON`, volume name și limitele de operare ca variabile furnizate din afara repository-ului. Nu există tokenuri ori valori efective de producție în Compose. Rețeaua `internal` blochează egress-ul containerului; endpointul nu este accesibil de pe host până la o cale de acces explicită și aprobată. Nu a fost introdus un override care să publice portul.
- Compose are healthcheck către `/readyz`. Buildul și rularea au fost validate numai cu tag, token fictiv, proiect Compose și volum temporare; nu s-au folosit date de producție și nu s-a publicat port pe host.

Instrucțiuni pentru operator după gate-urile de deployment (nu rula în etapa de documentare):

```sh
# Furnizează din secret manager variabilele obligatorii fără a le scrie în repository.
# Alege un RENDIV_DATA_VOLUME unic și o imagine RENDIV_IMAGE aprobată.
docker compose -p rendiv -f compose.yaml up -d --build

# Verifică starea și healthcheck-ul fără publicarea unui port pe host.
docker compose -p rendiv -f compose.yaml ps
docker compose -p rendiv -f compose.yaml exec -T rendiv-api \
  python -c "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8080/readyz', timeout=3).status)"

# Oprirea păstrează volumul de date.
docker compose -p rendiv -f compose.yaml stop

# Elimină containerul și rețeaua Compose, dar păstrează volumul numit.
docker compose -p rendiv -f compose.yaml down
```

Rollback-ul operat ulterior trebuie să folosească imaginea anterioară aprobată și aceeași bază persistentă numai după verificarea compatibilității schemei. Oprește serviciul, selectează explicit referința veche a imaginii, pornește fără rebuild și verifică `/readyz`. Nu folosi `down -v`, nu șterge volumul și nu încerca rollback de schemă prin editarea migrațiilor; pentru incompatibilitate, păstrează baza pentru recuperare conform runbook-ului backup/restore al Etapei 5.

- Checkpoint 4A: preflight a confirmat Docker CLI/daemon 29.8.2 și Compose 5.6.0; proiectul unic `rendiv-4a-88a6deb8ca53` nu exista înainte de test. `docker compose config --quiet` a trecut cu valori fictive. Buildul a folosit internet pentru imaginea de bază și pachet index. Prima încercare a eșuat pentru că `groupadd` lipsește din imaginea slim; după corectarea Dockerfile, rebuildul a trecut.
- În runtime-ul temporar: `/healthz` și `/readyz` au răspuns 200; token lipsă/invalid a răspuns 401; POST a răspuns 202, replay-ul idempotent a întors același job, iar GET a întors metadate fără payload. După recrearea containerului cu același volum, readiness a răspuns 200 și jobul a fost găsit prin replay și status. Containerul a rulat ca UID/GID 10001, cu root filesystem read-only, fără port host și cu singurul mount RW la volumul dedicat; rețeaua Compose era `internal` și montările nu includeau Docker socket. Cu o cale DB invalidă în `/proc`, readiness și POST au răspuns 503 (fail-closed).
- Au fost eliminate numai containerul/proiectul Compose, rețeaua, volumul și imaginea temporare ale checkpointului; inventarul containerelor, rețelelor, volumelor și imaginilor de dinainte a rămas neschimbat. Nu s-au folosit comenzi prune și nu s-a modificat infrastructura existentă.
- Verificare finală: 43 teste PASS, `pip check` PASS și `git diff --check` PASS în `/tmp/rendiv-stage1-venv`.
- Limitări înainte de deployment: tag-ul Python fixează versiunea 3.12.15, dar referința OCI nu este fixată prin digest; lockfile-ul fixează versiunile, nu hash-urile artefactelor. Buildul offline nu este demonstrat și buildul observat a necesitat internet. Nu au fost validate volume reale, ownership pe VM, conectivitatea callerilor, TLS/proxy, backup/restore sau servicii externe. `docker inspect` a confirmat UID, read-only, port bindings și mount-uri; formatul local folosit pentru citirea restart policy a eșuat la funcția Go-template indisponibilă, deci politica rămâne confirmată numai în configurația Compose (`unless-stopped`).

### Etapa 5 — backup, recuperare și monitorizare (2026-10-11)

- `rendiv_api.backup` oferă `create_backup`, `verify_database` și `restore_backup`, plus comenzi locale `python -m rendiv_api.backup create|verify|restore`. Copia folosește `sqlite3.Connection.backup()` din SQLite Online Backup API, astfel încât snapshot-ul include tranzacțiile WAL confirmate fără copiere directă a fișierului activ.
- Backupul verifică DB sursă, creează un fișier temporar cu permisiuni `0600` în directorul destinației, efectuează backupul online, rulează `PRAGMA integrity_check`, `foreign_key_check`, checksum-urile migrațiilor și validarea tabelelor/coloanelor așteptate. Apoi face fsync și publică atomic prin hard link fără înlocuirea destinației existente; sistemul de fișiere al destinației trebuie să permită hard link în același director. Eșecurile sunt raportate cu mesaje generice fără valori din DB.
- Restaurarea cere o cale absolută, nouă și neexistentă. Validează backupul înainte, îl copiază prin aceeași API SQLite într-un temporar, validează rezultatul și îl publică fără suprascriere. Nu modifică baza activă, nu pornește servicii și nu transformă stările joburilor. Rezultatul CLI arată numai numărul joburilor per stare; valorile `running`/`unknown` cer reconciliere umană bazată pe dovezi înainte de orice worker viitor. Nu se face retry automat; timeoutul nu demonstrează eșecul operației Understory.
- `rendiv_api.monitoring.read_monitoring_snapshot()` deschide DB cu `mode=ro` și `PRAGMA query_only=ON`; returnează agregat numărul joburilor pe fiecare stare, backlogul, timestampul celui mai vechi job queued, numărul `unknown` și ultima activitate din audit. Nu există endpoint HTTP nou și rezultatul nu conține payload, hash, principal sau ID individual.
- Teste izolate includ WAL și tranzacție de scriere necomisă în timpul backupului, restaurare, integritate, backup corupt, destinație existentă, checksum de migrare invalid, DB inexistentă, eroare simulată de permisiuni, fără suprascriere, monitorizare fără schimbarea datelor și blocarea apelurilor externe prin socket. Toate testele folosesc fișiere `tmp_path`; nu s-au accesat DB/volume reale sau Docker.
- Acceptanță locală: 53 teste PASS, `pip check` PASS și `git diff --check` PASS cu `/tmp/rendiv-stage1-venv`. Nu au fost instalate dependențe globale și nu s-au pornit servicii.
- Înainte de producție necesită aprobare/verificare: director și filesystem local care suportă hard link și fsync; backup off-host, criptare la rest, retenție/rotație, acces OS, RPO/RTO și owner; test restore periodic; volum/capacitate și drepturi reale. Endpointul privat de metrici, pragurile/alertele și integrarea cu monitorizarea rămân neimplementate și neaprobate. Backupul include payloadurile deja păstrate în DB; tokenurile API sunt configurate din environment, nu în schema DB, iar politica de a preveni callerii să includă date secrete în payload rămâne necesară înainte de date reale.
- Runbook-ul de operare pentru backup/restaurare este documentat după comenzile de development de mai jos; aceste comenzi nu au fost executate pe vreo bază persistentă.

### Checkpoint 5A — validare runtime backup/restore (2026-10-11)

- Preflight-ul a găsit repository-ul curat la `23bd766`, Docker CLI/daemon 29.8.2 și Compose 5.6.0. Proiectul unic `rendiv-5a-mv40znicmptf4j` și tag-ul `rendiv-cp5a:mv40znicmptf4j` nu existau. Configurația randată a definit un singur serviciu API, fără porturi publicate, cu rețea proprie `internal`, filesystem root read-only și volume numite distincte `rendiv-5a-mv40znicmptf4j-{data,backup,restore}`. Tokenul de test a fost fictiv și stocat numai în fișier temporar cu permisiuni restrictive.
- Buildul imaginii de test a trecut, dar a folosit internet pentru imaginea de bază și pachetele fixate din lockfile. Imaginea Python 3.12.15 slim Bookworm s-a rezolvat la digestul observat `sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`; Dockerfile nu fixează acel digest. Build offline nu a fost validat.
- Containerul unic a rulat cu UID/GID `10001:10001`, `read_only=true`, fără bindings de port și fără Docker socket. Mount-urile RW au fost numai cele trei volume dedicate; rețeaua proprie era internă și avea un singur container.
- Au fost create prin API două joburi sintetice. POST a confirmat enqueue, GET a expus numai metadate. După recrearea containerului cu același volum de date, readiness a trecut, replay-ul ambelor chei de idempotency a identificat joburile existente, iar statusurile au rămas `queued`.
- Comenzile reale `python -m rendiv_api.backup create`, `verify` și `restore` au trecut. Backupul a fost creat în volumul separat, verificat, restaurat într-un fișier nou din volumul distinct de restore și verificat din nou. Snapshotul sursă, backup și restore au avut aceeași structură/checksum de migrații și aceleași rânduri logice: schema 2, două joburi queued și două evenimente de audit. Nu au fost afișate payloaduri sau identificatori.
- Monitorizarea internă read-only a raportat queued=2, backlog=2 și unknown=0. Hashul logic al schemei/joburilor/evenimentelor înainte și după monitorizare a coincis; baza nu s-a modificat.
- Teste negative runtime sub UID/GID 10001: backup corupt refuzat cu eroare controlată; restore către destinație existentă refuzat fără schimbarea octeților; directoare fără permisiune de scriere au refuzat create și restore fără artefact publicat; DB absentă a produs eroare controlată atât pentru backup, cât și pentru monitorizare.
- Au fost eliminate numai containerul, rețeaua, cele trei volume și imaginea temporare de mai sus, prin `docker compose down --volumes --remove-orphans` scoped la proiect și `docker image rm` pe tag-ul unic. Confirmarea după cleanup a găsit zero resurse cu prefixul proiectului. Inventarul containerelor, rețelelor, volumelor și imaginilor inițiale a rămas neschimbat; nu s-au folosit prune. Fișierele temporare locale din `/tmp/rendiv-5a-mv40znicmptf4j` au fost șterse.
- Comenzile pentru operațiile runtime principale au fost:

  ```sh
  docker compose --env-file /tmp/rendiv-5a-mv40znicmptf4j/test.env \
    -p rendiv-5a-mv40znicmptf4j -f compose.yaml \
    -f /tmp/rendiv-5a-mv40znicmptf4j/compose-override.yaml \
    build --pull --no-cache rendiv-api
  docker compose --env-file /tmp/rendiv-5a-mv40znicmptf4j/test.env \
    -p rendiv-5a-mv40znicmptf4j -f compose.yaml \
    -f /tmp/rendiv-5a-mv40znicmptf4j/compose-override.yaml \
    down --volumes --remove-orphans
  docker image rm rendiv-cp5a:mv40znicmptf4j
  ```

  În container, backupul, verificarea și restore-ul au folosit `python -m rendiv_api.backup create /var/lib/rendiv/rendiv.sqlite3 /checkpoint/backup/checkpoint.sqlite3`, `python -m rendiv_api.backup verify /checkpoint/backup/checkpoint.sqlite3`, `python -m rendiv_api.backup restore /checkpoint/backup/checkpoint.sqlite3 /checkpoint/restore/restored.sqlite3` și apoi `python -m rendiv_api.backup verify /checkpoint/restore/restored.sqlite3`. Fișierul env cu bearer fictiv nu a fost inclus în repository sau raport.
- Verificare locală după runtime: 53 teste PASS, `pip check` PASS și `git diff --check` PASS în `/tmp/rendiv-stage1-venv`. Nicio bază reală, volum existent sau serviciu extern nu a fost accesat; nu s-a făcut deployment.
- Înainte de producție rămân deschise retenția/rotația, criptarea la rest, locația aprobată/off-host și controlul accesului la backup, RPO/RTO și responsabilul de recuperare, pinning OCI după digest și validarea buildului offline. Checkpointul nu testează retenția, criptarea, locația de producție, RPO/RTO, filesystemul ori volumul persistent real.

### Etapa 6A — worker local simulat (2026-10-11)

- S-a adăugat `rendiv_api.worker.LocalWorker`, pornit exclusiv prin apel explicit. API-ul, lifespan-ul FastAPI, Dockerfile și Compose nu importă și nu pornesc workerul. Nu există executor real; constructorul cere un executor injectat.
- Workerul procesează după `queue_seq` și revendică fiecare job într-o tranzacție `BEGIN IMMEDIATE`: verifică migrațiile, lipsa altui `running`/`unknown`, schimbă `queued -> running` și adaugă `worker_claimed` în același COMMIT. Toate tranzițiile și evenimentele aferente sunt validate și comise atomic; trigger-ele append-only existente rămân active.
- Workerii coordonează execuția prin fișier lock privat adiacent DB (`*.worker.lock`) cu `flock(LOCK_EX|LOCK_NB)` POSIX ținut pe durata executorului. Lock imposibil de verificat/obținut ori un `running` neașteptat oprește procesarea. Garanția presupune filesystem POSIX local cu locking fiabil și ca toți workerii Rendiv să respecte același lock; nu este garanție cross-host/NFS.
- La pornire, sub lock, orice `running` rămas devine `unknown` cu `effect_certainty=unknown` și eveniment `recovered_running_as_unknown`. Orice `unknown` blochează întreaga coadă. Timeoutul, rezultatul ambiguu și excepțiile executorului produc `unknown`; nu există retry sau reconciliere automată. Checkpointul 6B.2C a întărit conservator această regulă: `FAILED_NO_EFFECT` fără dovadă verificabilă devine `unknown`; succesul Understory doar raportat cu `changed_paths` nu produce `succeeded/complete`.
- Executorul și rezultatele sunt interfețe locale injectate. Testele folosesc exclusiv executor fictiv; crash-ul este reprezentat prin excepție de tip `BaseException` care lasă jobul `running`, pentru a verifica recuperarea la următoarea pornire. Codul nu deschide socketuri și nu apelează MCP sau servicii externe.
- Nu s-a adăugat migrație: schema implementată v2 susține stările și auditul. `worker_gate` și `job_attempts` menționate în design rămân propuneri, nu tabele existente; coordonarea acestei etape folosește lock file și verificări SQLite. Backup/restore și API status au fost verificate asupra jobului procesat.
- Dovezi de examinat înaintea oricărei reconcilieri viitoare: istoricul append-only al jobului și timestampurile claim/result; confirmarea dacă requestul a părăsit workerul; răspunsul/correlation ID-ul destinației dacă există; auditul Understory privind efectele, inclusiv scrieri parțiale; și confirmarea că operația nu mai rulează. Timeoutul sau lipsa răspunsului singure nu dovedesc no-effect. Dacă probele nu sunt decisive, jobul rămâne `unknown`, iar coada rămâne blocată. Nicio tranziție manuală nu este implementată în 6A.
- Verificarea inițială a implementării: 65 teste PASS cu Python 3.12.3 și SQLite temporar; `pip check` PASS; `git diff --check` PASS. Checkpointul Docker separat este consemnat mai jos. Fără servicii permanente, DB de producție, migrații noi, instalări globale sau integrare AI.
- Limitări: workerul este un harness local cu executor fictiv, nu un proces supervisat; nu are retry, reconciliere, lease/heartbeat, metadate attempts sau interfață operator. Lockul depinde de filesystem POSIX local și cooperarea tuturor workerilor. Executorul real, serializarea între hosturi, gate persistent în DB și procedura umană de reconciliere rămân în afara 6A.

### Checkpoint 6A — validare worker în Docker (2026-10-11)

- Preflight: Git curat la `c988bd0`; Docker CLI/daemon 29.8.2, Compose 5.6.0. Inventarele inițiale erau patru containere, cinci rețele, zero named volumes și patru imagini relevante. Proiectul unic `rendiv-6a-mv41rojo-9835fu`, imaginea `rendiv-cp6a:rendiv-6a-mv41rojo-9835fu`, volumul `rendiv-6a-mv41rojo-9835fu-data` și rețeaua `rendiv-6a-mv41rojo-9835fu_rendiv-private` au fost create numai pentru checkpoint.
- Buildul imaginii a trecut și a folosit internet pentru imaginea Python de bază și dependențele blocate. Containerul real a rulat ca UID/GID `10001:10001`, root filesystem read-only, fără port publicat sau Docker socket. A avut numai volumul named dedicat și bind-ul harness read-only; rețeaua Compose proprie era `internal` și avea numai containerul Rendiv.
- Harnessul a fost invocat explicit prin `docker compose exec ... python /checkpoint/worker_harness.py`; API-ul nu a pornit workerul automat. Toate operațiile au folosit executori fictivi. FIFO, serializarea, succesul, eșecul confirmat fără efect și timeoutul incert au trecut. Timeoutul a lăsat primul job `unknown`, a blocat următorul job queued și nu a făcut retry la o pornire ulterioară.
- Doi workeri în procese distincte, pe același container, filesystem și DB temporară, au concurat: primul a intrat în executorul blocant, al doilea a primit `WorkerBusy`, iar ordinea/stările au confirmat o singură execuție simultană.
- Testul crash a oprit cu `SIGKILL` procesul worker în timp ce jobul era `running`. La pornirea următoare a fost persistat `running -> unknown` cu `effect_certainty=unknown` și evenimentul `recovered_running_as_unknown`; executorul de la repornire nu a fost apelat, iar coada a rămas blocată.
- Harnessul a refuzat socket connect, iar rețeaua internă nu avea egress. Nu au avut loc apeluri către Understory, Pithagoras, Home Assistant, llama.cpp sau MCP.
- Cleanup-ul a folosit numai `docker compose -p rendiv-6a-mv41rojo-9835fu ... down --volumes --remove-orphans` și `docker image rm rendiv-cp6a:rendiv-6a-mv41rojo-9835fu`; zero resurse temporare au rămas. Inventarele de containere, rețele, volume și imagini au corespuns preflight-ului; nu s-au folosit prune.
- Verificare finală: 65 teste PASS, `pip check` PASS și `git diff --check` PASS în venv temporar. Buildul offline nu a fost demonstrat; digestul OCI nu este fixat. Testarea nu validează filesystem de producție, locking cross-host/NFS, executor real, reconciliere sau deployment.

### Etapa 6B.1 — adaptor Understory simulat (2026-10-11)

- `rendiv_api.understory_adapter` definește tipurile interne `Operation`, `JobPayload`, `TransportRequest`, `TransportResponse` și protocolul `InjectedTransport`. Acesta adaptează numai `memory_add`, `memory_update` și `memory_maintain` din allowlistul existent; payloadul rămâne un obiect JSON generic, fără câmpuri sau semnificații presupuse.
- Nu există transport HTTP/MCP/socket sau implementare Understory. Transportul trebuie injectat explicit. Tipurile de răspuns sunt clasificări interne pentru adaptor și teste, nu schema unui răspuns Understory.
- Succesul confirmat se mapează la `succeeded`; eșecul confirmat fără efect la `failed/none`. Timeoutul produce rezultatul worker `timeout`, iar incertitudinea, eroarea/întreruperea transportului și răspunsul invalid produc `unknown`; workerul 6A persistă auditul și blochează coada în aceste cazuri. Adaptorul nu repetă apeluri.
- Testele folosesc transport fake fără conexiuni; simulează timeout înainte/după efect, întrerupere, ambiguitate, răspuns invalid și integrarea cu auditul/coada workerului.
- Contractul operațional Understory încă lipsește: schemă și validări pentru fiecare payload, wire protocol și endpoint/tool exact, autentificare, timeouturi, schema răspunsurilor și identificatori de corelare, condițiile pentru a demonstra succesul/no-effect, erori și efecte parțiale, limite/idempotency și procedura de reconciliere. Acestea trebuie confirmate din implementarea/configurația reală înainte de 6B.2.
- Implementarea nu modifică schema, migrațiile, API-ul, Compose ori workerul; nu accesează servicii externe. Testarea completă și `pip check` pentru etapa sunt consemnate în `docs/LATEST-REPORT.md`.

### Etapa 6B.2A — investigare read-only contract Understory (2026-10-11)

- Checkout-ul local `/home/luci78/ai-stack/understory`, commit `f6c342332f390a444a8669636b1cf8f9669dd995`, a fost inspectat static și era curat la verificarea read-only. Raportul cu surse/simboluri și limite este `docs/design/03-UNDERSTORY-CONTRACT.md`.
- Codul local confirmă schemele MCP: `memory_add(content: string, suggested_path?: string)`, `memory_update(instruction: string)` și `memory_maintain({})`. Payloadul intern către agent este limbaj liber; agentul poate apela tool-uri interne de scriere pentru concepte Markdown.
- Transporturile implementate în checkout sunt MCP Streamable HTTP stateless la `/mcp` și stdio. Bearer auth HTTP pentru `/mcp` și `/api` este condițional de `AUTH_TOKEN`; activarea efectivă și transportul clientului nu au fost verificate.
- Traseul local persistă fișiere Markdown, indexuri și log. Efectele nu sunt tranzacție atomică multi-fișier. `partial` raportează căi schimbate; `failed` cu set de căi gol nu demonstrează universal no-effect, din cauza ordinii scrierilor și înregistrării căilor.
- Nu s-au găsit idempotency key, job ID/status sau mecanism de reconciliere. Timeouturile/anularea efectivă și potrivirea codului cu runtime rămân neconfirmate. `/api/chat`, dreamer, CLI și accesul filesystem sunt bypass-uri mutative în cod; activarea lor runtime nu a fost verificată.
- S-au inspectat numai surse locale; fără teste, servicii, HTTP/MCP, Docker sau valori secrete. Nicio sursă Understory nu a fost modificată. Nu s-a implementat executorul real și Etapa 6B.2B nu a început.

### Etapa 6B.2B — transport MCP simulat conform contractului (2026-10-11)

- `rendiv_api.understory_adapter` validează arguments conform schemelor observate: `memory_add` (`content`, opțional `suggested_path`), `memory_update` (`instruction`) și `memory_maintain` (`{}`). Nu adaugă semantică sau câmpuri operației.
- Apelul este serializat ca JSON-RPC `tools/call` și răspunsul `CallToolResult` este decodat de adaptor prin interfața injectată `McpTransport.exchange`. Nu există transport HTTP/stdio concret; fake-ul din teste este singurul peer.
- `changed_paths` nevid este doar succes raportat, nu read-back sau durabilitate; după decizia din 6B.2C, adaptorul îl marchează `unknown/unknown`. `isError`, failed fără probă no-effect, partial, răspuns malformed, disconnect și ambiguitate rămân `unknown`; timeoutul este persistat `unknown`. Healthy no-op pentru maintain rămâne unknown dacă nu există marker explicit neambiguu și validabil. Contractul nu oferă format de dovadă no-effect, iar adaptorul nu emite `FAILED_NO_EFFECT`.
- Workerul 6A păstrează FIFO, flock, auditul atomic și recuperarea la crash; integrarea fake verifică unknown blocant și că restartul nu reexecută jobul.
- Validarea a fost făcută numai cu peer in-memory și DB-uri temporare; fără conexiuni, servicii, Understory real, schema/migrații noi, schimbări API sau Compose. Contract real mașinabil, receipt, idempotency, lookup, no-effect și reconciliere rămân necesare înainte de integrarea reală.

### Checkpoint 6B.2C — auditul certitudinii efectelor (2026-10-11)

- Auditul și matricea completă sunt în `docs/design/04-EFFECT-CERTAINTY-AUDIT.md`. Deciziile operatorului au fost aplicate fără schimbare de schemă sau API.
- `changed_paths` rămâne succes raportat de Understory; adaptorul întoarce `unknown/unknown` cu reason auditabil `reported_success_unverified`. Acest rezultat blochează coada. Read-back-ul poate adăuga dovezi observabile, dar nu garantează o tranzacție sau durabilitate.
- Workerul convertește `FAILED_NO_EFFECT` fără dovadă structurată/verificabilă în `unknown/unknown`, reason `no_effect_unproven`; nu execută retry. Interfața actuală nu poate verifica un proof și nu permite `failed/none` prin simpla declarație a executorului.
- `memory_maintain` fără schimbări rămâne `unknown/unknown` cu reason `maintain_response_unverified`, fiindcă contractul local nu specifică un marker textual stabil, validabil. O confirmare explicită și validabilă ar putea fi terminală `succeeded/complete` fără stare nouă; adaptorul nu presupune un asemenea marker.
- FIFO, atomicitatea job/audit, crash recovery, blocarea unknown și redacția rămân verificate. JSON-RPC folosește UUID per apel pentru corelare, nu idempotency.
- Nu s-au schimbat schema, migrații, API, Docker/Compose sau infrastructura. Testele folosesc numai fake in-memory și SQLite temporar; nu s-au accesat Understory ori servicii reale.

### Checkpoint 6B.2D — audit read-only al contractului Understory (2026-10-11)

- Inspectat static checkout-ul local Understory la commitul `f6c342332f390a444a8669636b1cf8f9669dd995`; acesta era curat. Codul local arată markerul exact al ramurii healthy no-op din `memory_maintain` (`server.ts:193–203`), care execută lint fără `runMutation`. Aceasta corectează limita documentată în 6B.2C pentru sursa locală; nu dovedește versiunea activă și adaptorul Rendiv încă nu recunoaște markerul.
- Pentru `memory_add`/`memory_update`, `changed_paths` și succesul raportat nu dovedesc durabilitate ori exhaustivitatea efectelor: conceptul poate fi scris înainte să eșueze indexarea/logarea, iar callback-ul poate lăsa lista goală. Prin urmare `FAILED_NO_EFFECT` nu poate fi demonstrat din `failed`, `isError` sau paths goale.
- Sursa nu arată operation ID durabil, idempotency, status lookup, revision per operație, tranzacție multi-fișier sau receipt de commit. Timeoutul și anularea efectivă rămân neconfirmate; fallback-ul de model nu este idempotency a mutației.
- Rezultatele, matricea per operație, opțiunile de contract și referințele exacte sunt în `docs/design/05-UNDERSTORY-CONTRACT-AUDIT.md`. Nu au fost apelate API-uri, citite bundle-uri/DB-uri, rulate teste ori accesate servicii active; nu au fost modificate surse externe.
- Îmbunătățirea recomandată este un rezultat MCP structurat/versionat cu outcome explicit și operation ID; pentru replay/reconciliere după timeout este necesar separat journal durabil cu idempotency și status. Până atunci rezultatele ambigue rămân `unknown` fără retry.

### Checkpoint 6B.2E — identitate runtime și contract MCP V1 (2026-10-11)

- Metadatele read-only Docker au confirmat containerul `ai-understory`, image ID/repo digest `sha256:ad0699e1644f7ec75393c3335696be677b05a1c845e917e3a610a3a07f20ba7c`, restart `unless-stopped`, bind mount RW către `/bundle`, rețeaua `ai-stack_default`, portul host `3800` și comanda `node server/dist/index.js`. Environment, logs și conținutul volumului au fost excluse.
- Checkout-ul local curat este la `f6c342332f390a444a8669636b1cf8f9669dd995`, dar imaginea nu expune source/revision provenance care să lege digestul de commit. Versiunea runtime rămâne NECONFIRMATĂ.
- `docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md` propune outcome MCP structurat/versionat, corelare request, operation ID per încercare, semantics pentru applied/no_op/partial/rejected_before_write/unknown, fail-closed legacy fallback și matrice Rendiv. Documentul este propunere, nu implementare.
- Outcome structurat poate clarifica raportul terminal și no-op-ul; nu rezolvă deduplicarea la retry, status după restart, journal efectelor, atomicitate multi-fișier ori durability. Maparea `applied` la `succeeded/complete` necesită aprobarea explicită a semanticii acestei stări.
- Nu au fost accesate endpoints, environment values, secrete ori conținutul memoriei; nu s-au schimbat Docker sau serviciile și nu s-au rulat teste.

### Dezvoltare locală și teste izolate

Dependențele și versiunile folosite se instalează într-un mediu virtual local, nu ca serviciu permanent. Testele creează bazele SQLite sub `tmp_path` și nu cer Understory, Pithagoras sau acces la Docker.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.lock
PYTHONPATH=src .venv/bin/python -m pytest -p no:cacheprovider
```

Pentru a porni manual API-ul în dezvoltare este necesară o cale explicită, temporară, pentru DB; nu folosiți calea persistentă de producție în teste:

```sh
RENDIV_APP_ENV=development \
RENDIV_DATABASE_PATH=/tmp/rendiv-development.sqlite3 \
PYTHONPATH=src .venv/bin/uvicorn rendiv_api.app:create_app --factory
```

### Runbook operator backup și recuperare (instrucțiuni, neexecutate)

Aceste comenzi sunt doar procedură pentru o fereastră de mentenanță aprobată; nu au fost executate pe DB persistentă. Destinațiile trebuie alese explicit ca path-uri absolute noi. Backupul conține integral datele din DB, inclusiv payloadurile joburilor, deci trebuie protejat ca datele sursă. Tokenurile API sunt environment-only și nu fac parte din schema Rendiv.

```sh
# Înlocuiește valorile cu locații aprobate; BACKUP_PATH trebuie să nu existe.
BACKUP_PATH="/absolute/approved/backup/rendiv-YYYYMMDDTHHMMSSZ.sqlite3"
PYTHONPATH=src python -m rendiv_api.backup create \
  "$RENDIV_DATABASE_PATH" "$BACKUP_PATH"
PYTHONPATH=src python -m rendiv_api.backup verify "$BACKUP_PATH"

# Recuperarea scrie doar în alt path absolut, nou și neexistent.
RESTORE_PATH="/absolute/approved/recovery/rendiv-YYYYMMDDTHHMMSSZ.sqlite3"
PYTHONPATH=src python -m rendiv_api.backup restore \
  "$BACKUP_PATH" "$RESTORE_PATH"
PYTHONPATH=src python -m rendiv_api.backup verify "$RESTORE_PATH"
```

Revizuiește codurile de stare agregate din rezultat. `running` găsit după un crash nu se reexecută automat; `unknown` cere reconciliere umană bazată pe dovezi și nu se requeue-uiește pe baza timeoutului singur. Etapa 5 nu implementează schimbări de stare sau worker. Nu redirecționa serviciul activ către restaurare până la o aprobare și un plan separat de cutover/rollback. Păstrează sursa și backupul pentru investigație; frecvența, retenția, locația off-host, criptarea, RPO/RTO și responsabilul de recuperare necesită aprobare înainte de producție.


## Etapă de documentare: analiza Pithagoras–Understory

- Creat `docs/PITHAGORAS-UNDERSTORY-ANALYSIS.md` cu arhitectura observată în cod, dovezi, riscuri, verificări runtime rămase și propunerea de coadă pentru Rendiv.
- Confirmat în cod: Pithagoras expune tool-urile MCP Understory direct; coada `exclusive` din serviciul portalului nu acoperă apelurile directe; programarea de dreaming este timer în proces; SQLite și supervisorul de routines sunt mecanisme existente ce pot informa proiectarea.
- Separată starea unui tur Pithagoras de activitatea unei inferențe; contorul global al inferențelor către llama.cpp nu este confirmat ca implementat.
- Valorile endpoint/model comun au fost furnizate de utilizator și sunt consemnate în arhitectură; runtime-ul Pithagoras și timeoutul MCP efectiv rămân de verificat. Configurația Understory consemnată anterior nu a fost reverificată în această etapă.
- Recomandarea păstrează coada în Rendiv, serializează scrierile și joburile de noapte, răspunde asincron cu ID de job, închide căile MCP directe de scriere și marchează timeout/restart ca rezultat incert fără retry automat.
- Nicio implementare, modificare Pithagoras/Understory, operație de memorie, test sau acces la serviciu activ nu a fost efectuat în această etapă.
