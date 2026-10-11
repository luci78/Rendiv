# Raport checkpoint 4A — validare Docker Rendiv

- **Data:** 2026-10-11
- **Subiect:** Validarea izolată a containerizării Etapei 4, fără deployment
- **Domeniu:** Inspectare și testare exclusivă a artefactelor Rendiv cu un proiect Compose temporar. Nu s-au utilizat secrete reale, DB ori volume existente și nu s-au accesat Pithagoras, Understory, llama.cpp sau Home Assistant.

## Rezultate confirmate

- Preflight read-only: Docker CLI și daemon `29.8.2`, Docker Compose `5.6.0`, context `default`. Numele proiectului de test `rendiv-4a-88a6deb8ca53` nu exista înainte de test.
- `docker compose config --quiet` a trecut cu valori fictive pentru configurația de producție. Nu au fost afișate sau înregistrate valorile tokenului fictiv.
- Imaginea Rendiv s-a construit cu tag-ul unic `rendiv-cp4a:88a6deb8ca53`. Buildul a necesitat internet pentru imaginea de bază și pachet index. Prima încercare a identificat folosirea indisponibilă a `groupadd` în imaginea Python slim; Dockerfile a fost corectat să creeze directoarele și să seteze ownership prin Python, iar rebuildul a trecut.
- În proiectul temporar au fost create un singur serviciu Rendiv, rețeaua internă `rendiv-4a-88a6deb8ca53_rendiv-private` și volumul dedicat `rendiv-4a-88a6deb8ca53-data`. Compose nu a publicat porturi pe host. Rețeaua era marcată `internal`; containerul rula ca UID/GID 10001, avea root filesystem read-only, iar singurul mount observat era volumul dedicat la `/var/lib/rendiv`. Lista mount-urilor nu conținea Docker socket.
- Din container: `/healthz` și `/readyz` au răspuns 200. POST fără token și cu token invalid au răspuns 401. POST autentificat a răspuns 202 cu stare `queued`; replay-ul aceleiași chei/payload a întors același job, iar GET a returnat metadate fără payload.
- După recrearea containerului păstrând volumul de test, `/readyz` a răspuns 200, replay-ul a recunoscut același job, iar GET a confirmat că acesta persistă în starea `queued`.
- Într-un container separat temporar, calea DB a fost suprascrisă la un path invalid din `/proc`: `/readyz` a răspuns 503 `not_ready`, iar POST autentificat a răspuns 503 `database_unavailable`. Containerul de diagnostic a fost eliminat imediat.
- Curățarea a eliminat numai containerul/proiectul Compose de test, rețeaua și volumul cu numele unice și tag-ul de imagine Rendiv creat pentru test. Nu s-a folosit `prune`. Inventarul ulterior a avut aceleași ID-uri/nume de containere, aceleași ID-uri de rețele, niciun volum numit existent înainte sau după și exact aceleași imagini etichetate ca înainte. Statusul afișat pentru `ai-understory` a avansat de la 41 la 42 ore în cursul testului; ID-ul și starea de funcționare au rămas aceleași.

## Verificări și comenzi

Comenzi Docker relevante, restrânse la configurația și identificatorii unici ai testului:

```sh
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
docker compose version --short
docker compose --env-file /tmp/rendiv-4a-88a6deb8ca53/compose-test.env \
  -p rendiv-4a-88a6deb8ca53 -f compose.yaml config --quiet
docker compose --env-file /tmp/rendiv-4a-88a6deb8ca53/compose-test.env \
  -p rendiv-4a-88a6deb8ca53 -f compose.yaml build --pull --no-cache rendiv-api
docker compose --env-file /tmp/rendiv-4a-88a6deb8ca53/compose-test.env \
  -p rendiv-4a-88a6deb8ca53 -f compose.yaml up -d --no-build rendiv-api
docker compose --env-file /tmp/rendiv-4a-88a6deb8ca53/compose-test.env \
  -p rendiv-4a-88a6deb8ca53 -f compose.yaml up -d --no-build --force-recreate rendiv-api
docker compose --env-file /tmp/rendiv-4a-88a6deb8ca53/compose-test.env \
  -p rendiv-4a-88a6deb8ca53 -f compose.yaml down --volumes --remove-orphans
docker image rm rendiv-cp4a:88a6deb8ca53
```

Cererea HTTP a fost executată din interiorul containerului prin Python standard library. Testul de DB indisponibilă a folosit un container `compose run` suplimentar numai în proiectul temporar, fără publicare de porturi și cu path în `/proc`; acesta a fost șters după verificare. Env-file-ul cu token fictiv a rămas în `/tmp` pe durata testului și apoi a fost eliminat.

Verificările repository:

- `PYTHONPATH=src /tmp/rendiv-stage1-venv/bin/python -m pytest -p no:cacheprovider` — **43 PASS**.
- `/tmp/rendiv-stage1-venv/bin/python -m pip check` — **PASS**, fără dependențe incompatibile.
- `git diff --check` — **PASS**.

## Artefacte actualizate și limitări

- Corectat Dockerfile-ul pentru imaginea slim, actualizat testul static asociat și jurnalul Etapei 4 din `docs/DEVELOPMENT.md` cu rezultatele checkpointului.
- Tag-ul de bază fixează versiunea Python 3.12.15, dar Dockerfile-ul nu fixează digestul OCI. Lockfile-ul fixează versiunile pachetelor, nu hash-urile artefactelor; nu s-a demonstrat build offline. Nu au fost verificate storage-ul de producție, drepturile hostului, TLS/proxy, conectivitatea callerilor sau backup/restore.
- Un format Go-template local de `docker inspect` a respins funcția `hasPrefix`; nu a schimbat resurse. UID, root read-only, port bindings și lista mount-urilor au fost verificate separat. Restart policy este declarată de Compose (`unless-stopped`), fără verificare runtime păstrată.
- Checkpointul nu implementează worker, dispatch sau integrare AI și nu este deployment. Etapa 5 nu a început.
