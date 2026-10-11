# Raport runtime Rendiv: acces Docker și lacune rămase

- **Data:** 2026-10-11
- **Subiect:** Continuarea auditului read-only pentru `ai-pithagoras`, `ai-understory` și `rendiv-studio`, după activarea accesului Docker
- **Domeniu:** S-au încercat `docker ps` fără sudo, cu ieșire limitată la nume, ID, imagine, stare și porturi. Docker a refuzat în continuare accesul la socket. Nu s-a putut executa `docker inspect`. Nu s-au citit variabilele de mediu, loguri ori secrete și nu s-au rulat comenzi MCP, inferențe sau operații care schimbă starea.

## CONFIRMAT

- `docker ps --all --filter name=ai-pithagoras --filter name=ai-understory --filter name=rendiv-studio --format ...` a eșuat cu `permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock`.
- O a doua încercare `docker ps --all --format ...`, tot fără sudo și cu acces escaladat la comandă, a eșuat cu același mesaj. Nu au fost afișate metadate de container.
- În această rundă nu s-a executat `docker inspect`; starea de pornire, modelul și endpointul configurate, volumele, politica de restart, rețelele și mapările de porturi rămân necunoscute.
- Auditul anterior al codului Pithagoras a identificat integrarea Understory prin tool-uri MCP directe, inclusiv `memory_add`, `memory_update` și `memory_maintain`; aceste apeluri nu trec prin coada `exclusive` utilizată de anumite operații ale portalului.
- Codul Understory inspectat anterior oferă MCP streamable HTTP la `/mcp`, transport stdio, chat cu capacitate de scriere la `POST /api/chat` și intrarea CLI documentată `pnpm agent:mutate`. Sunt căi posibile în cod, nu confirmarea că sunt expuse sau active în runtime.
- Codul Pithagoras folosește `pi-mcp-adapter@2.18.0`; timeoutul `requestTimeoutMs` poate fi stabilit global sau per server. Contextul utilizatorului indică timeout implicit MCP de 60 s, dar valoarea runtime nu a fost confirmată.
- Contextul și documentația anterioară consemnează pentru Understory o verificare `docker inspect` făcută anterior de utilizator: `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M` și endpointul llama.cpp comun. Pithagoras este descris ca folosind aceeași configurație, fără reverificare în această rundă.
- Verificările GET llama.cpp din auditul anterior au raportat modelul `Qwen3.6-35B-A3B-Q5_K_M` disponibil/încărcat la momentul verificării. Acest fapt nu confirmă configurația curentă a fiecărui client.
- Codul Pithagoras persistă `portal.db` prin `better-sqlite3` cu WAL. Aceasta nu confirmă volumele Docker actuale și nu reprezintă o coadă persistentă Rendiv.
- Cerința de proiectare este ca inferența conversațională Pithagoras să aibă prioritate față de procesarea AI Understory pe llama.cpp comun. Prioritatea între loturile bufferului rămâne nedecisă. Operațiile Understory deja începute nu trebuie întrerupte brutal.

## NECONFIRMAT

- Dacă cele trei containere există, sunt pornite și corespund imaginilor/serviciilor așteptate.
- Valorile curente `LLM_MODEL` și `LLM_API_BASE_URL` pentru Pithagoras și Understory și endpointul llama.cpp efectiv folosit de fiecare.
- Volumele și bind mount-urile, sursele și destinațiile lor, persistența datelor și politica de restart.
- Rețelele Docker comune, aliasurile, porturile publicate și conectivitatea MCP între containere. `/mcp` este doar o cale identificată în cod; portul și expunerea runtime nu au fost confirmate.
- Timeoutul MCP efectiv și comportamentul la expirare. Nu s-a inspectat configurația clientului și nu s-a provocat un timeout.
- Care căi de scriere identificate în cod sunt active în runtime, ce clienți le folosesc și dacă există căi adiționale prin portal sau configurații externe.
- Contractul pentru statusul mutațiilor în curs și idempotency la Understory. Auditul anterior nu a identificat un contract de acest fel, fără verificare runtime în această rundă.
- Existența și persistența unei cozi Rendiv implementate.

## RISC

- Fără `docker inspect`, nu se poate stabili dacă baza de date, bundle-ul Understory sau viitoarea coadă au mount-uri durabile ori ce se întâmplă la restart.
- MCP direct, chat-ul web, CLI-ul și endpointul API pot ocoli viitoarea coadă Rendiv dacă rămân active pentru scrieri și nu sunt rutate printr-un punct comun de control.
- Un timeout al clientului poate lăsa rezultatul unei mutații Understory neclar; retry-ul automat poate duplica efecte dacă nu există idempotency sau reconciliere.
- Calea `/mcp` din cod nu dovedește accesibilitatea în rețea și nici porturile publicate.
- Un sondaj al sloturilor llama.cpp nu rezervă capacitate pentru Pithagoras. Coordonarea trebuie să împiedice pornirea loturilor noi când conversațiile au nevoie de inferență, fără întreruperea operațiilor Understory deja pornite.
- Încercarea Docker din această rundă arată că accesul la daemon nu este funcțional pentru procesul auditului, în pofida activării menționate. Concluziile runtime nu pot fi actualizate până când accesul read-only la socket funcționează.

## Recomandări înainte de implementare

1. Restabiliți accesul read-only la Docker pentru utilizatorul de audit și repetați `docker ps` și `docker inspect` cu proiecție de câmpuri, fără `.Config.Env` integral.
2. Confirmați modelul și URL-ul endpointului llama.cpp pentru fiecare client, fără a afișa credențiale sau alte valori de mediu.
3. Confirmați mounts, restart policy, rețele, aliasuri, porturi MCP și URL-ul/transportul folosit de fiecare client.
4. Determinați timeoutul efectiv din configurația Pithagoras și contractul de timeout al clientului/serverului; nu deduceți valoarea runtime din valoarea implicită raportată de utilizator.
5. Inventariați toate căile active de scriere și stabiliți cum sunt rutate prin Rendiv ori dezactivate ca bypass-uri.
6. Înaintea retry-urilor automate, stabiliți reconcilierea pentru rezultate ambigue și garanțiile de idempotency/status. Confirmați un volum durabil și strategia de recuperare înainte să alegeți locația cozii.
7. Implementați admiterea cu prioritate pentru cererile conversaționale Pithagoras; decideți separat ordonarea loturilor bufferului și nu întrerupeți brutal operațiile Understory deja începute.

## Dovezi și verificări

- `docker ps --all --filter name=ai-pithagoras --filter name=ai-understory --filter name=rendiv-studio --format '{{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'` — refuz de acces la Docker socket.
- `docker ps --all --format '{{.Names}}\t{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'` — refuz identic; nu au fost returnate nume sau porturi.
- `docker inspect` nu a fost rulat deoarece accesul la daemon a fost refuzat la listare.
- Constatarea de cod și verificările GET descrise mai sus provin din auditul/documentația anterioare, nu au fost repetate în această rundă.
- Nu au fost rulate teste, servicii, operații MCP, inferențe, restarturi sau deployment. Nu s-au citit secrete, variabile de environment în bloc, baze de date sau date de memorie.
