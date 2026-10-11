# Raport Etapa 5 — backup, recuperare și monitorizare Rendiv

- **Data:** 2026-10-11
- **Subiect:** Implementare izolată a backupului SQLite, verificării/restaurării și monitorizării read-only
- **Repository înainte de lucru:** curat la commitul `a702436` (`Validate Rendiv Stage 4 Docker checkpoint`). Schema curentă verificată în cod: migrațiile versionate `0001_bootstrap` și `0002_jobs_and_events`; nu au fost modificate migrații istorice.
- **Domeniu:** Numai fișiere Rendiv. Testele au folosit DB SQLite temporare. Nu s-au executat Docker/Compose, servicii permanente, deployment, inferențe sau apeluri MCP; nu s-au accesat DB/volume reale ori sisteme externe.

## Implementare verificată în cod

- `rendiv_api.backup` folosește `sqlite3.Connection.backup()` (SQLite Online Backup API), inclusiv pentru sursă în WAL. Verifică sursa și copia cu `integrity_check`, `foreign_key_check`, checksum-urile exacte ale migrațiilor aplicate și structura tabelelor/coloanelor așteptate.
- Backupul este generat într-un temporar cu permisiuni `0600`, în directorul destinației. După verificare și fsync este publicat atomic prin hard link fără înlocuirea unei destinații existente. Temporarele sunt curățate la eșec. Destinația trebuie să fie absolută, nouă, să aibă director părinte existent, iar filesystemul trebuie să permită hard link și fsync în acel director.
- Comenzile `python -m rendiv_api.backup create SOURCE DESTINATION`, `verify BACKUP` și `restore BACKUP NEW_DATABASE` raportează rezultat generic și sumar fără payload, credentiale, principal sau ID-uri individuale. Tokenurile API sunt configurate din environment, nu în schema SQLite.
- Restaurarea verifică sursa înainte de copiere, restaurează prin Online Backup API într-un fișier temporar pe calea explicită, absolută și neexistentă, verifică rezultatul înainte și după publicare și refuză suprascrierea. Nu schimbă starea joburilor și nu modifică DB activă.
- `read_monitoring_snapshot()` deschide baza cu `mode=ro` și `PRAGMA query_only=ON`. Returnează contoare agregate per stare, backlog, cel mai vechi timestamp queued, număr unknown și ultima activitate din `job_events`. Nu adaugă endpoint HTTP sau administrativ și nu expune payloaduri, hash-uri, principals ori ID-uri de job.
- Rezultatul backup/verify/restore indică agregat joburile `running` și `unknown`. Niciun retry sau dispatch nu este implementat. Joburile `running` găsite după crash nu se reexecută automat; `unknown` cere reconciliere umană bazată pe dovezi. Timeoutul singur nu demonstrează că operația Understory a eșuat.

## Teste și dovezi

- Suite completă Etapele 1–5: **53 PASS** cu Python 3.12.3 și SQLite temporar.
- `pip check`: **PASS**, fără dependențe incompatibile, în `/tmp/rendiv-stage1-venv`.
- `git diff --check`: **PASS**.
- Testele Etapei 5 acoperă sursă WAL și tranzacție scriitoare concurentă necomisă în timpul backupului, consistența snapshotului, restore și verificare, date corupte, checksum migrare invalid, DB lipsă, destinație existentă, refuz de permisiune injectat, lipsa suprascrierii, monitorizare fără schimbarea rândurilor și interdicția apelurilor externe prin socket.
- Toate artefactele DB sunt create în directoare temporare ale testelor. Nu a fost creată DB persistentă. Nu s-au instalat dependențe globale.

## Limitări și aprobări necesare înainte de producție

- Testul de permisiuni inserează controlat o eroare `PermissionError` la crearea temporarului; permisiunile filesystemului real și comportamentul pe volumul de producție nu au fost verificate.
- Backupul conține integral DB, inclusiv payloadurile joburilor. Deși tokenurile de serviciu nu sunt stocate în SQLite, callerii trebuie să evite introducerea credențialelor în payload. Copiile necesită control de acces OS, criptare la rest, rotație/retentie și o destinație off-host aprobate.
- Calea și filesystemul de producție, suportul pentru hard link/fsync, capacitatea, frecvența backupului, RPO/RTO, retenția, responsabilul de recuperare și testul periodic de restore necesită aprobare. Nicio valoare operațională nu a fost inventată.
- Monitorizarea este o funcție internă read-only, nu un endpoint și nu un exporter. Pragurile, alertele, paging-ul și conectarea la sistemul de monitorizare necesită decizie separată.
- Restore-ul nu mută automat `running` la `unknown`; funcționalitatea de tranziții/reconciliere nu există încă. Înainte de activarea oricărui worker viitor, operatorul trebuie să oprească dispatch-ul, să clasifice `running` ca rezultat incert prin procedura auditată aprobată și să reconcilieze `unknown` cu dovezi. Această etapă nu implementează tranziții, worker sau cutover.
- Nicio schimbare de infrastructură, deployment ori integrare Pithagoras/Understory/Home Assistant/llama.cpp nu a fost efectuată.

## Recomandare

Înainte de folosirea producției, aprobă locația și protecția copiilor, verifică suportul filesystemului pentru publicarea atomică și repetă un ciclu backup–verify–restore pe o copie izolată a configurației reale. Nu activa workerul până când orice job `running`/`unknown` restaurat nu a fost reconciliat și auditat.
