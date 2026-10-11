# Raport Checkpoint 6A — validare worker Rendiv în Docker

- **Data:** 2026-10-11
- **Subiect:** Test runtime izolat al workerului local simulat, concurenței, opririi forțate și recuperării `unknown`
- **Repository înainte de test:** curat la `c988bd0` (`Report Rendiv Stage 6A validation`); starea Git a fost verificată înaintea resurselor temporare.
- **Commit documentare checkpoint:** `0a86c60` (`Document Rendiv Stage 6A Docker checkpoint`); raportul curent este publicat separat.
- **Domeniu:** Imagine, container, volum, rețea și harness fictiv temporare pentru Rendiv. Fără deployment permanent, executor real, Understory/Pithagoras/Home Assistant/llama.cpp/MCP sau modificări de infrastructură.

## Preflight și izolare

- Docker CLI/daemon 29.8.2, Compose 5.6.0. Inventarul inițial avea patru containere, cinci rețele, niciun named volume și patru imagini relevante. Nu exista coliziune pentru numele unice folosite.
- Tag temporar: `rendiv-cp6a:rendiv-6a-mv41rojo-9835fu`. Proiect Compose: `rendiv-6a-mv41rojo-9835fu`; volum: `rendiv-6a-mv41rojo-9835fu-data`; rețea: `rendiv-6a-mv41rojo-9835fu_rendiv-private`.
- Configurația randată a definit un singur serviciu, fără porturi publicate, cu rețea internă proprie, un volum named pentru DB și harness montat read-only. Containerul inspectat avea UID/GID `10001:10001`, `ReadonlyRootfs=true`, `PortBindings={}`, fără Docker socket și numai mount-urile menționate; rețeaua internă avea un singur container.
- Buildul imaginii a trecut cu `docker compose ... build --pull --no-cache rendiv-api`; a descărcat imaginea Python și pachetele din lockfile, deci a necesitat internet. A fost pornit numai serviciul API din proiect cu `up -d --no-build`; workerul a fost lansat separat de harness.

## Teste runtime

Harnessul a fost invocat explicit prin `docker compose ... exec -T rendiv-api python /checkpoint/worker_harness.py`. A folosit numai `EnqueueRepository`, SQLite pe volumul temporar și executori ficțivi.

- **FIFO/serial:** trei joburi au fost executate în ordinea `queue_seq`, cu rezultate simulate succes, eșec confirmat fără efect și succes. Stările/certitudinea efectului și evenimentele append-only au corespuns rezultatelor; nu a existat mai mult de un apel executor activ.
- **Timeout incert:** primul job a devenit `unknown/unknown`; următorul a rămas `queued/none`. Pornirea ulterioară a fost blocată de `unknown` și nu a reexecutat niciun job.
- **Doi workeri concurenți:** două procese distincte, pe același container/filesystem/DB, au concurat. Primul a ținut executorul fictiv activ; al doilea a primit `WorkerBusy`. După finalizarea primului, un singur job era `succeeded`, următorul `queued`.
- **Oprire forțată:** un proces worker a fost omorât cu `SIGKILL` în timpul unui job `running`. La repornire, jobul a trecut atomic la `unknown/unknown`, a fost scris `recovered_running_as_unknown`, coada a rămas blocată și executorul repornit nu a fost apelat.
- **Rețea/AI:** harnessul a înlocuit socket connect cu refuz imediat; scenariile au trecut. Rețeaua Compose era internă fără egress. Nu au avut loc apeluri AI sau către servicii externe.

Comenzile relevante folosite (fișierul env a conținut numai valori fictive și nu este publicat):

```sh
docker compose --env-file /tmp/rendiv-6a-mv41rojo-9835fu/test.env \
  -p rendiv-6a-mv41rojo-9835fu -f compose.yaml \
  -f /tmp/rendiv-6a-mv41rojo-9835fu/compose-override.yaml \
  build --pull --no-cache rendiv-api

docker compose --env-file /tmp/rendiv-6a-mv41rojo-9835fu/test.env \
  -p rendiv-6a-mv41rojo-9835fu -f compose.yaml \
  -f /tmp/rendiv-6a-mv41rojo-9835fu/compose-override.yaml \
  up -d --no-build rendiv-api

docker compose --env-file /tmp/rendiv-6a-mv41rojo-9835fu/test.env \
  -p rendiv-6a-mv41rojo-9835fu -f compose.yaml \
  -f /tmp/rendiv-6a-mv41rojo-9835fu/compose-override.yaml \
  exec -T rendiv-api python /checkpoint/worker_harness.py

docker compose --env-file /tmp/rendiv-6a-mv41rojo-9835fu/test.env \
  -p rendiv-6a-mv41rojo-9835fu -f compose.yaml \
  -f /tmp/rendiv-6a-mv41rojo-9835fu/compose-override.yaml \
  down --volumes --remove-orphans
docker image rm rendiv-cp6a:rendiv-6a-mv41rojo-9835fu
```

## Cleanup și verificări

- Cleanup-ul a eliminat numai containerul, rețeaua, volumul și imaginea create pentru acest proiect; filtrele după numele unic au returnat zero resurse. Directorul temporar local, inclusiv tokenul fictiv și harnessul, a fost șters. Nu s-au folosit prune sau comenzi globale de curățare.
- Inventarele post-test au corespuns preflight-ului: aceleași patru containere, cinci rețele și patru imagini; zero named volumes. Resursele existente nu au fost modificate.
- Suita completă a proiectului: **65 teste PASS** (Python 3.12.3, venv temporar, SQLite de test).
- `pip check`: **PASS**, fără dependențe incompatibile. `git diff --check`: **PASS**.
- Nu au fost necesare corecții de cod; Etapa 6A a rămas neschimbată.

## Limitări și riscuri rămase

- Buildul a necesitat internet; build offline nu a fost demonstrat, iar OCI image reference nu este fixată după digest.
- `flock` oferă coordonarea testată numai când workerii folosesc același fișier pe filesystem POSIX local cu locking fiabil. Nu s-au validat NFS, locking cross-host sau mai multe hosturi.
- Harnessul demonstrează workerul local cu executor fictiv. Nu validează efecte Understory, executor real, supervisor, lease/heartbeat, reconciliere umană sau automatizată, producție ori cutover.
- Joburile `unknown` cer dovezi primare și intervenție umană viitoare; această etapă nu adaugă procedură de mutare a stării sau retry.

## Recomandare

Înainte de orice integrare reală, validați filesystemul și forma de gate pentru topologia țintă, apoi aprobați contractul executorului și procedura de reconciliere umană. Nu activați workerul în API/Compose și nu începeți Etapa 6B pe baza acestui checkpoint.
