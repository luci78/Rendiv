# Raport Etapa 6A — worker local simulat Rendiv

- **Data:** 2026-10-11
- **Subiect:** Worker FIFO local, cu executor fictiv injectabil și fără dispatch extern
- **Repository înainte de modificări:** curat la `1e277a2` (`Document Rendiv 5A runtime commands`); statusul Git a fost verificat înainte de editare.
- **Commit implementare:** `bd977f2` (`Add isolated Rendiv local worker`), cu worker, teste și jurnal de dezvoltare. Raportul curent este publicat separat conform regulii repository-ului.
- **Domeniu:** Numai workerul local, testele izolate și documentația de progres/raport. Fără Docker/Compose, deployment, servicii permanente, baze persistente reale, apeluri MCP, AI sau modificări de infrastructură.

## Implementare

- `rendiv_api.worker.LocalWorker` procesează joburile în ordinea `queue_seq`. Este pornit numai prin apel explicit și cere un executor injectat; API-ul, lifespan-ul FastAPI, Dockerfile și Compose nu pornesc workerul. Nu există executor pentru Understory sau alt serviciu extern.
- Claim-ul folosește `BEGIN IMMEDIATE`, verifică readiness/checksum-urile migrațiilor și selectează primul job `queued`. Schimbarea `queued -> running` și evenimentul append-only `worker_claimed` sunt în aceeași tranzacție. Nicio tranzacție SQLite nu rămâne deschisă pe durata executorului.
- Tranzițiile sunt permise explicit: `queued -> running`; apoi `running -> succeeded`, `failed` ori `unknown`. Certitudinea efectului este validată împreună cu tranziția: running/unknown=`unknown`, succeeded=`complete`, failed sigur=`none`. UPDATE-ul jobului și INSERT-ul evenimentului se comit atomic; o eroare la audit face rollback la ambele.
- Toate instanțele worker pentru aceeași bază trebuie să obțină lock exclusiv POSIX prin fișier adiacent `*.worker.lock`, ținut pe durata execuției. Dacă lockul este ocupat, nu este privat/verificabil sau baza nu este ready, workerul refuză procesarea. Înainte de claim se verifică și absența oricărui `running` neașteptat.
- După obținerea lockului la pornire, orice rând rămas `running` este trecut atomic la `unknown`, `effect_certainty=unknown`, cu eveniment `recovered_running_as_unknown`. Starea `unknown` blochează restul cozii. Timeoutul, excepțiile normale și rezultatul ambiguu devin `unknown`; workerul nu reîncearcă. Numai rezultatul explicit simulat `FAILED_NO_EFFECT` produce `failed/none`.
- Nu s-a adăugat migrație: schema implementată v2 și auditul existent sunt suficiente pentru această etapă. `worker_gate` și `job_attempts` apar în documentele de design ca propuneri, nu fac parte din schema curentă.

## Dovezi și teste

- Executorul fictiv a confirmat FIFO și maxim un apel simultan. Doi workeri concurenți: al doilea a primit `WorkerBusy` și nu a executat job; primul a terminat și a păstrat FIFO.
- Crash simulată înainte de claim a lăsat jobul queued. Crash în timpul execuției, după claim, a lăsat `running`; pornirea următoare l-a trecut la `unknown` și nu a apelat executorul pentru a-l relua.
- Timeout, rezultat `unknown`, rezultat invalid și excepție a executorului au blocat coada fără retry. Eșecul injectării evenimentului la claim și la rezultat a verificat rollback-ul atomic și recuperarea conservatoare.
- DB lipsă/coruptă a oprit workerul înaintea executorului. Testul de rețea a interzis socket connect în timpul execuției fictive. Backupul/restaurarea au păstrat statusul `succeeded`, iar API-ul existent a expus statusul după restore fără payload.
- Suite completă Etapele 1–6A: **65 teste PASS** cu Python 3.12.3, SQLite temporar și venv `/tmp/rendiv-stage1-venv`.
- `pip check`: **PASS**, fără dependențe incompatibile. `git diff --check`: **PASS**. Nicio dependență nu a fost instalată global.

## Limite, riscuri și probe pentru operator

- Serializarea depinde de filesystem POSIX local cu `flock` și SQLite locking fiabile, de o singură cale comună la DB și de cooperarea tuturor workerilor Rendiv cu același lock. Nu este o garanție între hosturi sau pe NFS/discuri cu semantică de locking neconfirmată. În caz de lock nesigur, workerul trebuie oprit; nu trebuie pornite copii independente.
- Lockul este extern bazei și nu oferă lease/heartbeat ori gate persistent auditabil în SQLite. Nu există tabel de attempts, reconciliere manuală, schimbare administrativă de stare, supervisor, dispatch real sau metrică publică. `unknown` blochează coada până la o intervenție ulterioară aprobată.
- Înainte de orice reconciliere umană, operatorul trebuie să examineze evenimentele Rendiv și timestampurile claim/rezultat, să stabilească dacă requestul a părăsit workerul, să caute răspuns/correlation ID și auditul primar al destinației pentru efecte complete/parțiale și să confirme că operația nu mai rulează. Timeoutul sau lipsa răspunsului nu dovedesc no-effect. Dacă probele nu sunt concludente, păstrează `unknown`, nu retrimite și escaladează către owner-ul destinației.
- Testele folosesc crash și rezultate simulate, nu măsoară efecte sau comportament Understory. Niciun rezultat de test nu confirmă compatibilitatea runtime a unei integrări viitoare.

## Recomandare

Înainte de worker real, aprobă forma unui gate persistat/auditabil și comportamentul de lock pentru topologia de deploy; definește contractul executorului și dovada no-effect a destinației; proiectează un flux operator de reconciliere cu autorizare și audit. Păstrează workerul oprit în API/Compose și nu începe Etapa 6B în cadrul acestei schimbări.
