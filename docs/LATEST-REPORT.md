# Raport Checkpoint 5A — validare runtime backup și restore Rendiv

- **Data:** 2026-10-11
- **Subiect:** Validare Docker izolată a backupului SQLite, verificării, restaurării și monitorizării Etapei 5
- **Repository înainte de lucru:** curat la `23bd766` (`Add Rendiv SQLite backup and monitoring`). Schema verificată: migrațiile `0001_bootstrap` și `0002_jobs_and_events`, schema version 2. Nicio migrație istorică nu a fost modificată.
- **Domeniu:** Exclusiv Rendiv și resurse Docker temporare unice. Nu s-au accesat baze/volume reale, nu s-a făcut deployment și nu s-au atins Pithagoras, Understory, llama.cpp, Home Assistant sau alte servicii.

## Preflight și izolare

- Docker CLI/daemon: 29.8.2; Docker Compose: 5.6.0. Inventarele inițiale de containere, rețele, volume și imagini au fost înregistrate înainte de creare; proiectul `rendiv-5a-mv40znicmptf4j` și tag-ul `rendiv-cp5a:mv40znicmptf4j` nu existau.
- Configurația Compose randată a avut un singur serviciu API, fără porturi publicate, fără socket Docker și fără rețele existente. Rețeaua dedicată `rendiv-5a-mv40znicmptf4j_rendiv-private` era internă. Volumele dedicate au fost `rendiv-5a-mv40znicmptf4j-data`, `rendiv-5a-mv40znicmptf4j-backup` și `rendiv-5a-mv40znicmptf4j-restore`.
- Buildul imaginii Rendiv de test a trecut cu dependențele blocate. A necesitat internet pentru imaginea de bază și descărcarea pachetelor. Python 3.12.15 slim Bookworm s-a rezolvat în acest build la digestul observat `sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`; referința OCI din configurație nu este fixată prin digest.
- Inspectarea containerului a confirmat UID/GID `10001:10001`, root filesystem read-only, fără port host și numai mount-urile RW dedicate. Rețeaua internă conținea doar containerul testului.

## Rezultate runtime

- Au fost create două joburi sintetice prin API cu bearer fictiv. POST a răspuns queued, GET a expus doar metadate. Containerul API a fost recreat cu același volum de date; readiness a trecut, replay-ul ambelor cereri a identificat joburile existente, iar statusurile au persistat ca queued.
- Mecanismul real `rendiv_api.backup` a creat backupul din DB activă prin SQLite Online Backup API, în volumul separat. Comenzile `create`, `verify`, `restore` într-un volum de restore distinct și verificarea bazei restaurate au trecut. Sursa, backupul și restore-ul au avut schema/checksum de migrații identice și același conținut logic: schema 2, două joburi queued și două evenimente de audit.
- Monitorizarea read-only a raportat queued=2, backlog=2 și unknown=0. Hashurile logice ale schemei, joburilor și evenimentelor înainte și după citirea monitorizării au coincis; baza nu s-a modificat.
- Teste negative sub UID/GID 10001: backup corupt refuzat cu eroare controlată; restaurarea către destinație existentă refuzată fără alterarea octeților existenți; permisiuni de scriere revocate au făcut create și restore să eșueze fără publicarea unui fișier; DB absentă a produs eroare controlată pentru backup și monitorizare.
- Nu au fost afișate tokenuri, payloaduri sau ID-uri individuale. Nu au avut loc apeluri externe sau operații AI.

## Cleanup și verificări

- Au fost eliminate numai containerul și rețeaua proiectului unic, cele trei volume de test și imaginea `rendiv-cp5a:mv40znicmptf4j`, prin `docker compose down --volumes --remove-orphans` scoped la proiect și `docker image rm` pe tag-ul temporar. Verificarea după cleanup a găsit zero resurse cu prefixul unic. Fișierele temporare locale din `/tmp/rendiv-5a-mv40znicmptf4j` au fost eliminate.
- Comenzile runtime pentru build și cleanup au fost `docker compose --env-file /tmp/rendiv-5a-mv40znicmptf4j/test.env -p rendiv-5a-mv40znicmptf4j -f compose.yaml -f /tmp/rendiv-5a-mv40znicmptf4j/compose-override.yaml build --pull --no-cache rendiv-api`, aceeași comandă Compose cu `down --volumes --remove-orphans`, apoi `docker image rm rendiv-cp5a:mv40znicmptf4j`. În container s-au folosit comenzile `python -m rendiv_api.backup create /var/lib/rendiv/rendiv.sqlite3 /checkpoint/backup/checkpoint.sqlite3`, `verify /checkpoint/backup/checkpoint.sqlite3`, `restore /checkpoint/backup/checkpoint.sqlite3 /checkpoint/restore/restored.sqlite3` și `verify /checkpoint/restore/restored.sqlite3`. Fișierul de environment cu bearer fictiv nu a fost publicat.
- Inventarul Docker post-test a corespuns inventarului inițial pentru containere, rețele, volume și imagini; nu s-au folosit comenzi prune și nu s-au șters resurse existente.
- Suita completă Etapele 1–5: **53 teste PASS** (Python 3.12.3).
- `pip check`: **PASS**, fără dependențe incompatibile în venv temporar.
- `git diff --check`: **PASS** înaintea actualizării raportului; verificarea finală se rulează după documentare.

## Limite și decizii înainte de producție

- Nu au fost validate backupurile persistente reale, retenția/rotația, criptarea la rest, destinația off-host, accesul OS, frecvența, RPO/RTO sau restaurarea pe filesystemul de producție. Acestea necesită decizie și aprobare operațională.
- Digestul OCI nu este fixat în Dockerfile/Compose; digestul menționat este numai cel observat pentru buildul acestui checkpoint. Buildul offline nu a fost demonstrat și testul a folosit internet.
- Testul nu a făcut deployment și nu a creat directoare ori baze persistente pe VM. Backupul și restore-ul au existat numai în volume temporare dedicate, eliminate după test.
- `running`/`unknown` nu au fost generate prin worker; nu există worker sau reconciliere automată. Joburile `running` restaurate după crash nu se reexecută automat, iar `unknown` necesită reconciliere umană pe bază de dovezi înaintea oricărei mutații.

## Recomandare

Înainte de producție, aprobă retenția, criptarea, destinația și controlul accesului backupurilor, RPO/RTO și responsabilul de recuperare; fixează imaginea după digest și validează un build offline. Rulează apoi un restore controlat pe o copie izolată a configurației aprobate. Acest checkpoint nu începe Etapa 6.
