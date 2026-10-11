# Raport runtime Rendiv: acces Docker și lacune rămase

- **Data:** 2026-10-11
- **Subiect:** Audit read-only al containerelor `ai-pithagoras`, `ai-understory` și `rendiv-studio`
- **Domeniu:** S-a încercat `docker ps` fără sudo, conform cererii. Docker API a refuzat accesul la socket. Nu s-au rulat `docker inspect`, `docker exec`, comenzi sudo, inferențe sau mutații MCP și nu s-au schimbat containere ori configurații.

## CONFIRMAT

- Comanda filtrată `docker ps --all` pentru cele trei nume a eșuat cu `permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock`. Nu au fost returnate metadate de container în această etapă.
- Auditul anterior al codului Pithagoras a identificat integrarea Understory prin tool-uri MCP directe, inclusiv `memory_add`, `memory_update` și `memory_maintain`; aceste apeluri nu trec prin coada internă `exclusive` a serviciului folosit de anumite operații ale portalului.
- Codul Understory inspectat anterior oferă MCP streamable HTTP la `/mcp`, transport stdio, chat cu capacitate de scriere la `POST /api/chat` și intrarea CLI documentată `pnpm agent:mutate`. Acestea sunt căi posibile în cod, nu confirmarea că sunt active în runtime.
- Codul Pithagoras folosește `pi-mcp-adapter@2.18.0`; timeoutul `requestTimeoutMs` poate fi stabilit global sau per server. Contextul proiectului indică timeout implicit MCP de 60 s, dar valoarea runtime nu a fost confirmată.
- Contextul/documentația anterioară consemnează pentru Understory o verificare anterioară a utilizatorului prin `docker inspect`: `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M` și endpointul llama.cpp comun. Pithagoras este descris ca folosind aceeași configurație conform contextului, fără reverificare în această etapă.
- Verificările GET llama.cpp din auditul anterior au raportat modelul Qwen3.6-35B-A3B-Q5_K_M disponibil/încărcat la acel moment. Ele confirmă starea serverului la interogare, nu configurația curentă a fiecărui client.
- Codul Pithagoras persistă `portal.db` prin `better-sqlite3` cu WAL; aceasta nu confirmă volumele Docker curente și nu reprezintă coada persistentă Rendiv.
- Cerința de prioritate este: inferența conversațională Pithagoras are prioritate față de procesarea AI Understory pe llama.cpp comun. Prioritatea între loturile bufferului este încă nedecisă. Nu se întrerup brutal operațiile Understory deja începute.

## NECONFIRMAT

- Dacă cele trei containere există, sunt pornite și corespund imaginilor/serviciilor așteptate.
- Valorile curente `LLM_MODEL` și `LLM_API_BASE_URL` pentru Pithagoras și Understory.
- Volumele/mount-urile, sursele și destinațiile lor, caracterul persistent și politica de restart.
- Rețelele Docker comune, aliasurile, porturile publicate și accesibilitatea efectivă a MCP între containere. `/mcp` este o cale din cod, nu un port publicat confirmat.
- Timeoutul MCP efectiv și comportamentul la expirare. Nu s-a inspectat configurația și nu s-a provocat timeout.
- Care dintre căile de scriere din cod sunt activate, clienții runtime existenți și eventualele căi suplimentare din configurații externe.
- Un contract de status pentru mutații în curs sau idempotency la Understory. Auditul de cod anterior nu a găsit un contract de acest tip; nu s-a efectuat verificare runtime.
- Existența și persistența unei cozi Rendiv implementate.

## RISC

- Fără `docker inspect`, nu se poate stabili dacă baza de date, bundle-ul Understory sau viitoarea coadă au mount-uri durabile și cum se comportă la restart.
- Timeoutul clientului poate lăsa neclar dacă mutația Understory a terminat; retry-ul orb poate duplica efecte în lipsa unei garanții de idempotency.
- MCP direct, chat-ul web, CLI-ul și API-ul portalului pot ocoli o coadă Rendiv dacă aceste căi rămân active și acceptă scrieri.
- Numele `/mcp` din cod nu demonstrează conectivitatea de rețea sau publicarea portului.
- Un sondaj al sloturilor llama.cpp este doar observațional și nu rezervă capacitate pentru Pithagoras. Coordonarea trebuie să împiedice pornirea unor loturi noi când conversațiile au nevoie de inferență, fără a întrerupe operațiile Understory începute.

## Recomandări și informații necesare înainte de implementare

1. Restabiliți accesul read-only la Docker pentru utilizatorul care rulează auditul, apoi repetați `docker ps` și `docker inspect` cu proiecție strictă a câmpurilor; nu afișați `.Config.Env` integral.
2. Confirmați mounts, restart policy, rețele, aliasuri și porturi MCP, apoi identificați ce URL/transport MCP folosește efectiv fiecare client.
3. Determinați timeoutul efectiv din setările Pithagoras fără a citi sau expune tokenuri și stabiliți comportamentul la expirare din contractul client/server.
4. Inventariați toate căile active de scriere și decideți cum sunt direcționate prin Rendiv sau dezactivate ca bypass-uri.
5. Înainte de retry automat, definiți reconciliere după rezultat ambiguu și idempotency/status pentru mutații. Stabiliți unde va locui coada persistentă numai după confirmarea volumului durabil și a strategiei de backup/recuperare.
6. Implementați admiterea cu prioritate pentru cererile conversaționale Pithagoras; păstrați nedecisă politica de ordonare între loturi până la o decizie separată și nu întrerupeți brutal loturile deja începute.

## Dovezi și verificări

- Comandă read-only încercată fără sudo: `docker ps --all --filter name=ai-pithagoras --filter name=ai-understory --filter name=rendiv-studio --format ...`.
- Rezultat: refuz de acces la Docker socket. Din acest motiv, în această rundă nu s-a executat `docker inspect` și nu s-au putut confirma containere, mounts, restart policy, rețele sau porturi.
- Constatările despre cod și verificările GET menționate mai sus provin din auditul anterior și sunt marcate ca atare; nu au fost repetate aici.
- Nu au fost citite secrete, variabile de environment în bloc, loguri private, baze de date sau date de memorie. Nu au fost executate operații de scriere, teste, restarturi ori deployment.
