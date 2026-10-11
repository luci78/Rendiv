# Raport audit runtime Rendiv: acces Docker nefuncțional

- **Data:** 2026-10-11
- **Subiect:** Reluarea inspecției read-only pentru `ai-pithagoras`, `ai-understory` și `rendiv-studio`
- **Domeniu:** S-a încercat mai întâi `docker ps`, cu ieșire limitată la numele, imaginea și starea containerelor. Sandboxul a eșuat înainte de execuția comenzii; încercarea autorizată în afara sandboxului a fost refuzată de Docker socket. Inspecția s-a oprit aici. Nu s-au citit environment-uri, loguri sau secrete și nu s-au executat operații MCP.

## CONFIRMAT

- `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'` în sandbox a eșuat înainte de a ajunge la Docker, cu `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
- Aceeași comandă rulată în afara sandboxului a primit `permission denied while trying to connect to the Docker API at unix:///var/run/docker.sock`.
- Nu au fost returnate informații despre containere și nu s-a rulat `docker inspect`.
- Nu s-au modificat, oprit sau repornit containere. Nu s-au declanșat inferențe sau mutații MCP.

## NECONFIRMAT

Pentru `ai-pithagoras`, `ai-understory` și `rendiv-studio` nu se pot confirma în această rundă:

- existența și starea containerelor;
- modelul configurat și endpointurile llama.cpp utilizate;
- volumele și bind mount-urile;
- rețelele, aliasurile și porturile publicate;
- politica de restart;
- timeoutul MCP configurat efectiv.

Documentația și constatările din raportul anterior menționează modelul `Qwen3.6-35B-A3B-Q5_K_M`, un endpoint llama.cpp comun și un timeout MCP implicit raportat de utilizator de 60 s. Acestea nu au fost reverificate și nu constituie confirmări ale configurației runtime curente.

## RISC

- Fără acces la daemon, nu se poate stabili configurația runtime sau persistența datelor și nu se poate evalua dacă rețeaua MCP și endpointurile sunt expuse conform intenției.
- Contextul anterior indică faptul că Understory poate lucra mai mult decât timeoutul MCP implicit raportat. Fără valoarea configurată și fără verificarea comportamentului efectiv, rezultatul unei cereri poate rămâne neclar la timeout; acest aspect rămâne de investigat.

## Dovezi și verificări

- `docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'` — eșec în sandbox: `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`.
- Aceeași comandă cu execuție în afara sandboxului — refuz Docker socket: `permission denied ... /var/run/docker.sock`.
- `docker inspect` nu a fost rulat, deoarece verificarea inițială `docker ps` nu a funcționat.
- Nu au fost rulate teste, servicii, comenzi MCP, inferențe, restarturi sau deployment.
