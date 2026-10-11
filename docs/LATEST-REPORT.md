# Raport audit runtime Pithagoras–Understory

- **Data:** 2026-10-11
- **Subiect:** Configurație AI, persistență, acces MCP, timeouturi și căi de scriere directe relevante pentru coada Rendiv
- **Domeniu:** Inspecție read-only a containerelor Docker și a codului sursă Pithagoras/Understory. Valorile de token, parolele, cheile API și conținutul fișierelor de configurare care le-ar putea conține nu au fost citite sau publicate. Nu s-au executat cereri MCP, inferențe, mutații, teste, restarturi sau deployment.

## Constatări verificate în runtime

### Configurații AI

- Containerul `ai-understory` are `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M`, `LLM_API_BASE_URL=http://192.168.20.30:8080/v1` și `LLM_API_FORMAT=openai` în environment-ul Docker. Acestea sunt valorile efective furnizate containerului la pornire.
- Containerul `ai-pithagoras` nu are variabile de environment cu setările `LLM_MODEL`, `LLM_API_BASE_URL` sau `LLM_API_FORMAT`. Configurația sa efectivă de model poate proveni din date persistente/aplicație; aceasta nu a fost inspectată deoarece fișierele și stocarea de configurare pot conține secrete. Prin urmare, folosirea de către Pithagoras a aceluiași model și endpoint rămâne **neconfirmată în runtime**. Mențiunile din documentația Rendiv despre această egalitate provin din context anterior, nu din verificarea curentă.

### Persistență și restart

- `ai-pithagoras` folosește politica Docker `unless-stopped`. Are bind mount-uri read-write pentru `/data` și `/workspaces`, mapate la datele persistente Pithagoras de pe host.
- `ai-understory` folosește politica `unless-stopped`. Bind mount-ul read-write către `/bundle` este mapat la datele Understory de pe host. Bundle-ul folosit de serviciu este astfel persistent față de recrearea containerului, în limitele păstrării directorului host.
- Acestea sunt bind mount-uri, nu volume Docker numite. Inspecția confirmă maparea și accesul read-write; nu a verificat backup-uri, permisiuni pe host, integritatea datelor sau comportamentul de recuperare după întrerupere.

### Rețele, porturi și acces MCP

- `ai-pithagoras` folosește `network_mode=host`; nu apare cu mapări de porturi Docker. Procesul împarte spațiul de rețea al hostului.
- `ai-understory` este în rețeaua bridge `ai-stack_default`. Portul `3800/tcp` este publicat pe `0.0.0.0:3800`, deci Docker îl leagă pe toate interfețele IPv4 ale hostului. Atingerea din afara hostului depinde în continuare de rutare și firewall; acestea nu au fost testate.
- `rendiv-studio` este într-o rețea Docker separată, `rendiv-config_default`, fără rețea bridge comună cu `ai-understory`. Dacă workerul Rendiv va comunica direct cu Understory, ruta și limitele de acces trebuie definite explicit; aliasul `understory` este valabil în rețeaua `ai-stack_default`, nu în rețeaua Rendiv.
- Sursa Pithagoras (`server/src/features.ts`) generează intrarea MCP Understory cu URL implicit `http://localhost:3800/mcp`, `lifecycle: "lazy"` și `directTools: true`. URL-ul poate fi suprascris prin `MEMORY_UNDERSTORY_URL` sau de intrarea MCP persistată. Nu s-a citit configurația persistentă; URL-ul și activarea efectivă a intrării MCP/adaptorului în runtime rămân **neconfirmate**.
- Codul Understory (`packages/server/src/index.ts`, `packages/server/src/auth.ts`) pune autentificare bearer opțională în fața rutelor `/mcp` și `/api`, în funcție de setarea serverului. Starea efectivă a autentificării nu a fost verificată, deoarece ar necesita inspectarea unei valori secrete. Nu s-a făcut o cerere HTTP către serviciu.

## Căi de scriere care pot ocoli coada Rendiv

- **Confirmat în codul Pithagoras:** integrarea este proiectată să pună tool-urile Understory direct în lista agentului (`directTools: true`). Dacă intrarea MCP și adaptorul sunt active în runtime, apelurile agentului `understory_memory_add`, `understory_memory_update` și celelalte tool-uri ajung la Understory fără coada Rendiv. Activarea curentă nu a fost verificată din configurația persistentă.
- **Confirmat în codul Understory:** endpointul MCP stateless `/mcp` înregistrează `memory_add`, `memory_update` și `memory_maintain`, iar handler-ele apelează `runMutation` direct (`packages/server/src/mcp/server.ts`, `packages/server/src/mcp/http.ts`). Portul publicat permite o cale de rețea directă către acest endpoint; nu s-a invocat.
- **Confirmat în codul Understory:** `/api/chat` folosește toolset-ul complet de citire și scriere (`packages/server/src/api/chat.ts`, `packages/core/src/agent/agent.ts`). Este încă o cale potențială de mutație, în afara MCP. Ea intră sub aceeași autentificare condițională pentru `/api`.
- Bundle-ul Understory este montat read-write, deci orice proces sau operator cu acces la directorul host poate edita memoria direct, fără MCP și fără Rendiv. Auditul nu a inventariat actorii de pe host.
- `memory_status` raportează starea bazei de cunoștințe, nu starea unei operații MCP. Codul verificat nu oferă ID durabil de job, status per mutație sau cheie de idempotency pentru `add/update/maintain`. Transportul HTTP creează un server MCP nou pentru fiecare cerere. Nu există dovadă aici că un timeout al clientului anulează mutația deja începută sau că un retry este sigur.

## Timeout MCP

- **Confirmat în codul Pithagoras:** adaptorul fixat în `server/src/api/mcp.ts` este `pi-mcp-adapter@2.18.0`; obiectul generat pentru intrarea Understory în `server/src/features.ts` nu setează `requestTimeoutMs`.
- Codul adaptorului instalat nu a fost disponibil în checkout-ul inspectat, iar fișierul global `mcp.json`/setările adaptorului din datele runtime nu au fost citite. Documentația de arhitectură menționează 60 s ca valoare implicită raportată, iar documentația versiunii adaptorului descrie configurare globală/per-server; acestea nu confirmă valoarea efectivă sau eventualul override din containerul curent.
- **Neconfirmat:** timeoutul MCP efectiv, timeouturile proxy/network, dacă închiderea transportului oprește o mutație Understory și durata maximă reală a operațiilor. Nu s-au trimis cereri pentru măsurarea lor.

## Ce trebuie clarificat înainte de implementarea cozii

1. Modelul, endpointul și modelul de fallback folosite efectiv de Pithagoras, precum și inventarul celorlalți clienți ai endpointului llama.cpp comun. Confirmarea trebuie obținută fără citirea sau afișarea credențialelor din configurații.
2. Timeoutul MCP și override-urile efective, plus comportamentul transportului la timeout/deconectare. Trebuie stabilită o metodă de verificare care nu expune și nu citește credențiale.
3. Starea efectivă a intrării MCP Understory și a autentificării; cine poate accesa portul `3800` prin rețea și ce clienți pot apela `/mcp` sau `/api/chat`.
4. Toate căile de scriere trebuie puse în spatele Rendiv sau restricționate: tool-urile directe Pithagoras, MCP accesibil de pe rețea, chat-ul Understory, accesul la fișierele bundle de pe host și eventualele procese CLI/operator.
5. Contractul de reconciliere pentru operații cu rezultat incert: Understory nu expune în codul inspectat un job ID/status per scriere sau idempotency key. Înainte de retry trebuie stabilit cum se detectează efectul deja aplicat ori cum se gestionează manual rezultatul ambiguu.
6. Mecanismul concret de prioritate pentru inferența conversațională Pithagoras față de AI Understory pe serverul comun. Așteptarea până la un moment fără inferențe observate nu elimină cursa în care o conversație începe după lansarea jobului; nu trebuie întreruptă brutal o operație Understory începută.
7. Prioritatea relativă între loturile din coadă rămâne o decizie separată și nedecisă. Mai trebuie definite serializarea, recuperarea după restart, deduplicarea, retry/backoff și comportamentul pentru mutații parțiale.

## Recomandare

Păstrați Rendiv drept punct unic de admitere pentru scrieri și inventariați/rutați explicit fiecare cale de mai sus înainte de a declara că nu există bypass. Proiectarea trebuie să trateze timeoutul/deconectarea și restartul în timpul unei mutații ca rezultat potențial incert, fără retry automat până la reconciliere. Cerința de prioritate a conversațiilor trebuie proiectată separat de ordinea loturilor și nu este încă o proprietate implementată.

## Dovezi și limitări

- Docker read-only: `docker ps` și `docker inspect` pentru `ai-pithagoras`, `ai-understory` și `rendiv-studio`; au fost tipărite doar modelul, endpointul și formatul AI neconfidențiale, politica de restart, mount-urile, rețelele și porturile. Numele variabilelor au fost folosite doar pentru filtrare; valorile secrete nu au fost afișate.
- Cod Pithagoras: `server/src/features.ts`, `server/src/api/mcp.ts`; căutare timeout în `server/src`.
- Cod Understory: `packages/server/src/mcp/server.ts`, `packages/server/src/mcp/http.ts`, `packages/server/src/index.ts`, `packages/server/src/auth.ts`, `packages/server/src/api/chat.ts`, `packages/core/src/agent/agent.ts`; README-ul descrie tool-urile MCP și endpointul HTTP.
- Nu s-au citit fișiere `.env`, configurații persistente ce pot conține credențiale sau memoria Understory. Nu s-au citit loguri, nu s-a apelat MCP/HTTP, nu s-au executat inferențe sau mutații și nu s-au modificat/restartat containere.
- Nu s-au rulat teste și nu s-a făcut deployment.
