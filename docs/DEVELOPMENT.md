# Dezvoltare și progres

## Etape

| Etapă | Rezultat urmărit | Stare |
|---|---|---|
| 1. Documentarea sistemului | Reguli Codex, arhitectură cunoscută/neconfirmată și plan de lucru | Încheiată prin această inițializare |
| 2. Confirmarea contractelor | Verificarea API-urilor MCP, timeouturilor efective, statusului operațiilor și posibilităților de deduplicare | Neîncepută; analiza de cod este documentată, verificările runtime lipsesc |
| 3. Proiectarea cozii | Schema persistentă, priorități, serializare, recovery, verificarea după timeout și politica anti-duplicate | Neîncepută |
| 4. Implementarea bufferului Rendiv | Acceptare asincronă, procesare serială și integrare cu sistemele sursă/destinație | Neîncepută; nu este autorizată în această etapă |
| 5. Verificare și operare | Validarea comportamentului, monitorizare, retry și proceduri de recuperare | Neîncepută |

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
| 5. Backup și observabilitate | Proceduri și metrici | Neîncepută |

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


## Etapă de documentare: analiza Pithagoras–Understory

- Creat `docs/PITHAGORAS-UNDERSTORY-ANALYSIS.md` cu arhitectura observată în cod, dovezi, riscuri, verificări runtime rămase și propunerea de coadă pentru Rendiv.
- Confirmat în cod: Pithagoras expune tool-urile MCP Understory direct; coada `exclusive` din serviciul portalului nu acoperă apelurile directe; programarea de dreaming este timer în proces; SQLite și supervisorul de routines sunt mecanisme existente ce pot informa proiectarea.
- Separată starea unui tur Pithagoras de activitatea unei inferențe; contorul global al inferențelor către llama.cpp nu este confirmat ca implementat.
- Valorile endpoint/model comun au fost furnizate de utilizator și sunt consemnate în arhitectură; runtime-ul Pithagoras și timeoutul MCP efectiv rămân de verificat. Configurația Understory consemnată anterior nu a fost reverificată în această etapă.
- Recomandarea păstrează coada în Rendiv, serializează scrierile și joburile de noapte, răspunde asincron cu ID de job, închide căile MCP directe de scriere și marchează timeout/restart ca rezultat incert fără retry automat.
- Nicio implementare, modificare Pithagoras/Understory, operație de memorie, test sau acces la serviciu activ nu a fost efectuat în această etapă.
