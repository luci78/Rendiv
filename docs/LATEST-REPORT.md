# Raport runtime Rendiv: inspecție Docker și lacune de implementare

- **Data:** 2026-10-11
- **Subiect:** Continuarea auditului runtime Pithagoras–Understory pentru containere, configurație AI, timeout MCP, persistență și căi de acces
- **Domeniu:** Inspecție strict read-only. S-a încercat numai `sudo docker ps` după permisiunea explicită; comanda s-a oprit la cererea parolei. Nu s-au furnizat parole și nu s-a încercat o cale alternativă de acces. Nu au fost executate `docker inspect`, `docker exec`, operații MCP, inferențe, restarturi sau modificări.

## CONFIRMAT

### Runtime și model

- `sudo docker ps --all --format ...` a afișat solicitarea sudo pentru parola utilizatorului. Sudo a răspuns `a password is required`; comanda a fost întreruptă fără introducerea parolei. Prin urmare, inventarul live de containere nu a fost obținut și `docker inspect` nu a fost rulat.
- Raportul runtime anterior consemnează verificări GET read-only ale serverului llama.cpp: `/health` a răspuns 200, iar `/v1/models` și `/models` au indicat Qwen3.6-35B-A3B-Q5_K_M disponibil/încărcat la momentul verificării. Acest lucru confirmă starea serverului atunci, nu configurația efectivă a fiecărui client.
- Contextul și documentația anterioară consemnează că Understory a fost verificat de utilizator prin `docker inspect` cu `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M` și endpointul comun llama.cpp. Pithagoras este descris ca folosind aceeași configurație conform contextului anterior, fără reverificare runtime în acel audit. Această etapă nu a putut reconfirma niciuna dintre valori prin Docker.
- Codul Pithagoras folosește `pi-mcp-adapter@2.18.0`. Opțiunea `requestTimeoutMs` poate fi configurată global sau per server; fără override se aplică implicitul MCP SDK. Contextul proiectului indică 60 s pentru timeoutul implicit, dar configurația efectivă nu a fost verificată.

### Căi MCP și scriere identificate în codul auditat anterior

- Pithagoras expune integrarea Understory prin tool-uri MCP directe, inclusiv mutațiile `memory_add`, `memory_update` și `memory_maintain`. Aceste apeluri nu trec prin coada `exclusive` a serviciului intern folosit de anumite operații ale portalului.
- Codul Understory oferă MCP streamable HTTP la `/mcp` și transport stdio. Codul mai oferă chat web la `POST /api/chat`, cu agentul și tool-urile sale de citire/scriere; README-ul documentează și intrarea CLI `pnpm agent:mutate`.
- Acestea sunt suprafețe posibile deduse din cod, nu confirmarea că fiecare client sau rută este activă în containerele curente. Inventarul runtime al clienților nu a fost posibil.
- Prioritatea de proiectare rămâne: inferența conversațională Pithagoras are prioritate față de procesarea AI Understory pe serverul llama.cpp comun. Prioritatea între loturile bufferului este separată și încă nedecisă. Operațiile Understory deja începute nu trebuie întrerupte brutal.

### Persistență și status

- Codul Pithagoras deschide `portal.db` cu `better-sqlite3` și activează WAL. Recuperarea `RoutineSupervisor` tratează run-urile routines rămase `running` drept `interrupted`; aceasta nu este recuperare pentru o coadă Rendiv.
- În codul Understory inspectat anterior, `memory_status` descrie starea/health-ul bundle-ului, nu un job de mutație. Traces și `traceId` oferă urme de execuție, nu un contract observat de polling durabil sau idempotency. Nu a fost găsit un contract de idempotency pentru mutațiile Understory.
- Aceste constatări privesc codul. Montările efective ale containerelor și durabilitatea după restart nu sunt confirmate fără `docker inspect`.

## NECONFIRMAT

- Numele, imaginile, starea și porturile containerelor Pithagoras și Understory în runtime-ul actual.
- Valorile actuale `LLM_MODEL` și `LLM_API_BASE_URL` ale ambelor containere. Valoarea Understory rămâne o verificare raportată anterior de utilizator; Pithagoras nu a fost reverificat.
- Volumele/mount-urile persistente, sursele și destinațiile lor, modul read-write și politica de restart a containerelor.
- Rețelele Docker, aliasurile, porturile publicate și existența unei rute MCP accesibile între Pithagoras, Understory și alte servicii.
- Timeoutul MCP efectiv și comportamentul la expirare în configurația runtime. Nu se știe dacă expirarea clientului anulează procesarea Understory sau doar oprește așteptarea clientului; nu s-a provocat un timeout.
- Inventarul complet al clienților și căilor active de scriere, inclusiv configurările externe care nu apar în codul auditat.
- Dacă endpointul llama.cpp `/slots` poate identifica sursa unei inferențe sau poate acorda prioritate/rezervare. Verificarea anterioară a fost doar un instantaneu read-only.
- Existența unei cozi persistente Rendiv, a statusului de job sau a mecanismului de idempotency la destinație.

## RISC

- Dacă Understory termină o mutație după timeoutul clientului, un retry orb poate dubla efecte; codul inspectat nu oferă o garanție de idempotency observată.
- Clienții MCP direcți, chat-ul web, CLI-ul și operațiile portalului pot ocoli serializarea unei cozi Rendiv dacă rămân active căi de scriere paralele.
- `GET /slots` poate ajuta la observarea activității, dar nu rezervă serverul și nu elimină cursa dintre verificare și pornirea unei inferențe conversaționale.
- Lipsa accesului la Docker lasă necunoscute restart policy, volumele și topologia efectivă; astfel nu se poate afirma că datele cozii sau ale memoriei supraviețuiesc restarturilor containerelor.
- Oprirea forțată a unei operații Understory deja începute poate lăsa efecte parțiale și contrazice regula de prioritate stabilită.

## Recomandarea minimă pentru Rendiv

1. Mențineți o coadă persistentă Rendiv cu identificator stabil/idempotency key, hash-ul lotului și stări explicite (`queued`, `running`, `succeeded`, `failed`, `unknown`). Alegeți stocarea numai după confirmarea mediului de deploy și a volumului durabil.
2. Folosiți un singur worker pentru mutațiile Understory și reconciliere după timeout/restart. Nu relansați automat rezultatele ambigue; verificați efectul printr-o cale read-only/status înainte de retry. Cum Understory nu oferă un contract de status/idempotency confirmat, această limitare trebuie rezolvată înaintea retry-urilor sigure.
3. Inventariați și rutați toate căile active de scriere prin Rendiv, sau documentați explicit bypass-urile care rămân. Înainte de planificare, confirmați rețeaua și accesibilitatea MCP fără a expune credențiale.
4. Protejați inferența conversațională Pithagoras la admiterea lucrărilor noi pe serverul llama.cpp comun. Nu întrerupeți brutal lucrările Understory deja pornite. Păstrați prioritatea între loturi ca decizie separată încă nedecisă.
5. Înainte de implementare, obțineți o inspecție Docker autorizată care să confirme selectiv configurația model/endpoint, mounts, restart policy, rețele și porturi, precum și timeout MCP fără afișarea environmentului complet ori a secretelor.

## Dovezi și verificări

- Consultate regulile din `AGENTS.md` și raportul runtime precedent din `docs/LATEST-REPORT.md`.
- Încercare runtime curentă: `sudo docker ps --all --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'`; sudo a solicitat parola și a răspuns `a password is required`. S-a oprit fără autentificare. Nu s-a rulat `docker inspect`.
- Dovezile anterioare sunt descrise distinct mai sus; endpointurile llama.cpp au fost interogate numai prin GET, iar codul proiectelor a fost inspectat read-only.
- Nu au fost citite fișiere `.env`, configurații cu credențiale, loguri private, baze de date sau conținutul memoriei. Nu s-au declanșat inferențe, operații MCP, teste, restarturi sau deployment.
