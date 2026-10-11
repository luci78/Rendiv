# Rendiv: integrare sursele, Understory și prioritizarea inferenței

- **Secțiune:** 01 — Proiectare Rendiv
- **Stare:** propunere tehnică; neimplementată și neaprobată pentru implementare
- **Data:** 2026-10-11
- **Arhitectură:** [`01-ARCHITECTURE.md`](01-ARCHITECTURE.md)
- **Bază de date:** [`01-DATABASE.md`](01-DATABASE.md)
- **Baseline:** [`../baselines/BASELINE-2026-10-11.md`](../baselines/BASELINE-2026-10-11.md)

## 1. Starea actuală relevantă

Baseline-ul confirmă că Pithagoras poate expune direct tool-urile MCP Understory; configurația runtime care activează efectiv acea intrare nu a fost citită. Understory expune `/mcp`, inclusiv mutațiile `memory_add`, `memory_update`, `memory_maintain`, și `/api/chat`, al cărui agent are unelte de scriere. `/bundle` este bind mount read-write. Portul Understory este publicat pe host; autentificarea efectivă și reachability din exterior nu sunt confirmate.

Nu există endpoint de enqueue Rendiv implementat și nu s-a confirmat integrare activă Home Assistant → Rendiv. `rendiv-studio` este un container separat observat pe host; nu se presupune că este serviciul Rendiv proiectat aici. Modelul efectiv Pithagoras, timeoutul MCP configurat și clienții llama.cpp nu sunt confirmați.

## 2. Contract API propus

API-ul este intern, versionat și autentificat. Numele domeniului/portului, TLS, limitele și autentificarea efectivă se stabilesc la deployment; nu se preiau din valori runtime neconfirmate.

### Enqueue

```http
POST /v1/jobs
Authorization: <credential de serviciu per caller>
Idempotency-Key: <cheie stabilă pentru aceeași intenție>
Content-Type: application/json
```

Corpul logic propus:

```json
{
  "operation": "memory_add",
  "payload": {
    "...": "corpul structurat al operației sau lotul logic integral"
  }
}
```

- Identitatea/sursa este derivată din credentialul autentificat, nu acceptată ca valoare arbitrară din body.
- `operation` este allowlist (`memory_add`, `memory_update`, `memory_maintain`); nu acceptați un URL, comandă, tool name sau MCP method liber de la caller.
- Payloadul rămâne un document logic pentru Understory. Rendiv validează formă și mărime, dar nu clasifică conceptele și nu fragmentează semantic batch-ul Home Assistant.
- `Idempotency-Key` este obligatoriu, cu format opac și limită de lungime aleasă în contract. Callerul o refolosește la retry de transport numai pentru aceeași intenție.

Răspuns la job nou sau replay identic:

```http
202 Accepted
```

```json
{
  "job_id": "<uuidv7>",
  "state": "queued",
  "status_url": "/v1/jobs/<uuidv7>",
  "created_at": "<UTC timestamp>"
}
```

Replay cu aceeași cheie/hash returnează același `job_id` și starea curentă. Refolosirea cheii cu payload diferit întoarce `409 Conflict`. Payload invalid întoarce `400`/`422`; corp peste limita configurată întoarce `413`; caller neautorizat întoarce `401`/`403`; limitare de rată/backlog întoarce răspuns temporar documentat. Niciun răspuns pozitiv nu se emite înainte de commit SQLite.

### Status

```http
GET /v1/jobs/{job_id}
Authorization: <credential de serviciu sau operator>
```

Răspunsul include `job_id`, `state`, `created_at`, `started_at`, `finished_at`, `attempt_count`, `effect_certainty`, un cod de eroare sigur și link/rezumat de reconciliere disponibil. Nu include payloadul, hashul, tokenuri, prompturi sau conținut de memorie. Callerul vede doar joburile proprii; operatorul cu rol dedicat poate vedea toate stările.

Stările răspunsului sunt `queued`, `running`, `succeeded`, `failed` și `unknown`. `unknown` este explicit: nu reprezintă eșec și nu autorizează retry. GET este read-only. Reconcilierea este o operație separată, privilegiată, motivată și auditată.

### Validare și limite

- Parse strict JSON, UTF-8 valid, schema versionată, respingere pentru câmpuri neașteptate sau operații nepermise.
- Stabiliți un `max_request_bytes` configurabil și un plafon de backlog/disk înainte de implementare. Valoarea runtime nu este cunoscută și nu este inventată aici.
- Măsurați limita cu bytes UTF-8 ai reprezentării canonice, nu cu numărul de caractere. Respingeți peste limită; nu trunchiați și nu despărțiți automat batch-ul logic.
- Limitați numărul de requests/secundă și pending jobs per principal; folosiți răspuns temporar la saturație, fără a accepta job ne-durabil.
- Idempotency key are plafon de lungime și character set simplu; idempotency records rămân cel puțin cât perioada în care callerul poate retrimite.
- Nu includeți corpuri, chei sau fragmente de text în error messages, access logs, traces sau metric labels.

## 3. Integrare Pithagoras

1. Inventariați toate profilele/agenții și callerii care pot vedea `understory_memory_*`; configurația efectivă și setul de tool-uri nu se presupun identice între sesiuni.
2. Într-o etapă de compatibilitate, adăugați/adoptați un tool Pithagoras care trimite mutația la Rendiv și întoarce rapid `job_id`/`queued`. Citirea `memory_query` poate rămâne directă numai dacă politica de acces permite; toate scrierile trebuie să treacă prin Rendiv după cutover.
3. Folosiți un key stabil per eveniment/intentie (de ex. ID-ul durabil al evenimentului sursă plus operația), nu un hash al textului ca unic ID. Nu inventați ID-uri repetabile din timestamp aproximativ.
4. Dezactivați tool-urile directe mutative pentru callerul migrat numai după ce enqueue-ul, statusul, ACL-ul și monitorizarea sunt operaționale. Evitați perioada cu două căi active pentru aceeași intenție.
5. La eșecul API-ului, Pithagoras nu raportează că memoria a fost salvată. Conversația poate continua, dar operația este marcată neacceptată și callerul prezintă retry controlat cu aceeași cheie. Orice outbox local Pithagoras este o extensie separată, nu se presupune existentă.

## 4. Integrare Home Assistant

- Home Assistant trimite fiecare lot logic drept un enqueue și păstrează același `Idempotency-Key` la retry de rețea al acelui lot.
- Rendiv validează și păstrează întregul lot. Nu introduce taxonomie paralelă, nu împarte semantic batch-ul și nu decide conceptele Understory.
- Callerul folosește status API pentru a verifica progresul. `202` confirmă persistența jobului în Rendiv, nu scrierea în memorie.
- Lipsa contractului HA curent, schema batch-ului, event ID-ul nativ, limitele de dimensiune și politica la lot respins sunt decizii deschise; nu sunt prezentate ca integrare existentă.

## 5. Understory și toate căile de bypass

### Rute de închidere graduală

| Cale actuală/potențială | Comportament confirmat în baseline | Măsură propusă înainte de cutover complet |
|---|---|---|
| Tool-uri MCP directe din Pithagoras | Sursa Pithagoras poate expune direct add/update/maintain; activarea runtime este neconfirmată | Callerul migrat primește numai enqueue pentru mutații; filtrează/dezactivează tool-urile directe de scriere după smoke/acceptance în mediu izolat. Read-only query se decide separat. |
| Client de rețea către Understory `/mcp` | Endpointul oferă tool-uri mutative; portul este publicat; acl/auth/reachability efective necunoscute | Restricționează portul la proxy/Rendiv și operatorii autorizați; pune un proxy de filtrare în față sau schimbă permisiunile MCP astfel încât doar workerul să poată muta. |
| Understory `/api/chat` | Codul chat folosește toolset complet cu scriere | Dezactivează mutațiile prin UI/API sau restricționează ruta/operatorii; altfel rămâne bypass chiar dacă Pithagoras este migrat. |
| Acces direct la bundle `/bundle` / sursă host | Bind mount read-write confirmat | ACL OS, ownership și procedură break-glass; exclude scrieri simultane cu workerul și loghează intervenția operatorului. |
| CLI, scripturi, alte procese/agenți | Codul Understory are cale CLI de mutație; callerii existenți nu sunt inventariați complet | Inventariază joburi, cron, operatori și clienți; oprește/rutează căile după proprietar și fereastră de cutover. |
| Operații portal Pithagoras cu coadă `exclusive` | Coada în memorie acoperă doar operații portal selectate, nu tool-urile MCP directe | Include orice operație portal care scrie bundle-ul în același gate Rendiv sau interzice concurența în timpul mutației. |

`memory_status` nu este status de job și nu înlocuiește `GET /v1/jobs/{job_id}`. Nu există garanție exactly-once doar pentru că Rendiv deduplică enqueue-ul: după ce requestul a ajuns la Understory, timeoutul sau răspunsul pierdut pot lăsa efectul necunoscut. Rendiv păstrează aceeași intenție și cere reconciliere, nu retrimitere automată.

## 6. Prioritate inferență versus ordinea joburilor

Prioritatea conversațională Pithagoras privește admiterea cererilor către modelul llama.cpp. Prioritatea/ordinea joburilor privește ce mutație queued alege workerul. Sunt două politici separate; joburile Pithagoras nu primesc automat precedență față de batch-urile Home Assistant.

Un `GET /slots` poate raporta ocuparea observată, dar nu rezervă slotul și nu face admiterea atomică. Pithagoras poate începe o cerere între acel GET și POST-ul Understory. Endpointul nu oferă prin simpla citire clase de caller, fairness, rezervare sau garanția de disponibilitate pentru următoarea conversație; existența/semantica lui pentru serverul configurat nu este confirmată.

Propunerea este un gateway de admitere LLM comun, cu autentificare distinctă per client și clase interactive/background. Gateway-ul:

1. primește cereri Pithagoras și Understory prin aceeași poartă;
2. pune cererile interactive în fața cererilor background care încă nu au primit slot;
3. nu admite un nou pas de inferență Understory cât timp o cerere interactivă este în așteptare;
4. nu oprește o inferență/mutație Understory deja începută;
5. raportează așteptarea și ocuparea prin metrici, nu prin polling GET-then-act al workerului.

Workerul Rendiv trebuie să fie singura sursă de mutații Understory, dar gateway-ul programează fiecare inferență internă generată de agentul Understory. Este necesar ca Pithagoras, Understory și toți ceilalți clienți relevanți să folosească gateway-ul. Dacă există un singur slot fără preempție, o inferență Pithagoras poate aștepta cererea Understory activă. Prioritate absolută și latență zero nu pot fi promise fără slot/capacitate rezervată, scheduling nativ verificat sau model/server separat.

Ordinea în care workerul alege batch-urile rămâne nedecisă. Înainte de implementare trebuie aprobată o politică distinctă (de ex. FIFO sau echitate ponderată) și un comportament de starvation. Proiectul nu afirmă că inferențele Pithagoras au prioritate prin schimbarea ordinii dintre joburile Pithagoras și HA.

## 7. Autentificare și control acces

- TLS pe interfața Rendiv și autentificare serviciu-la-serviciu cu identitate separată pentru Pithagoras, Home Assistant și worker. mTLS sau bearer tokens scoped per caller sunt alternative; formatul și secret manager-ul se decid la deployment.
- Callerul poate crea numai joburi pentru operațiile autorizate și citi numai joburile proprii. Operatorul are rol distinct, MFA/SSO dacă este disponibil, acces auditabil la toate joburile și endpoint-uri de reconciliere.
- Workerul are acces minim: numai operarea Understory permisă, fără acces API general din partea callerilor. Rendiv validează fiecare operație, nu acceptă arbitrary tool names sau arbitrary URLs.
- Restricționează Understory `/mcp` și `/api` la rețeaua/proxy necesar; portul host expus nu este un control suficient. Securizează ACL-urile mount-ului bundle și credențialele în afara payloadurilor.
- Rotația/revocarea credentialelor trebuie să păstreze identitatea de audit și să poată bloca rapid un caller fără ștergerea joburilor acceptate.

## 8. Observabilitate, backup și operare

### Metrici/loguri

Metrici cu cardinalitate limitată: număr queued/running/unknown, vechimea celui mai vechi job, durata până la enqueue commit, durata jobului, timeouturi, răspunsuri parțiale, conflicte idempotency, erori auth, gate ocupat/incert, backlog/disk și latency pe clasele inference gateway.

Logurile includ `job_id`, attempt ID, caller ID tehnic, state transition, cod rezultat și timpi. Nu includ payload, hash, auth headers, prompturi, text de memorie sau date personale. Auditul event-based din SQLite este autoritativ pentru tranziții; logurile runtime nu sunt substitut.

Alerte: gate `uncertain`, job `unknown`, job `running` peste pragul operațional ales, creștere continuă backlog, disk aproape plin, backup eșuat, coadă fără progres și întârzieri interactive peste SLO.

### Backup/restore

- Copie consistentă SQLite cu online backup/WAL gestionat; verificare checksum, criptare și acces limitat.
- Politica include payloaduri, stări, gate, idempotency keys/tombstones și audit în aceeași snapshot consistentă.
- Restore într-un mediu izolat; `running` devine `unknown`, iar niciun job incert nu pornește automat. Operatorul reconciliază înainte de redeschiderea gate-ului.
- Stabiliți RPO/RTO, rotația, retenția, test periodic restore și owners înainte de deployment. Valorile nu sunt cunoscute și nu sunt inventate aici.

### Rollback

Rollback-ul se face per sursă, după oprirea dispatch-ului Rendiv pentru acea sursă și reconcilierea joburilor `running/unknown`. Nu se retrimit aceleași intenții pe vechea cale directă cât timp jobul Rendiv poate fi aplicat. Pentru a evita întreruperea serviciilor, sursele încă nemigrate rămân pe fluxul actual până la cutover-ul lor; callerii migrați primesc acceptare/status Rendiv. Dacă Rendiv nu este disponibil, callerul nu face fallback automat la scriere directă: continuă conversația, dar semnalează că mutația nu a fost acceptată, iar retry-ul păstrează aceeași cheie. Disponibilitatea unei outbox-uri locale ar necesita proiectare separată.

## 9. Migrare graduală propusă

1. **Inventar fără schimbări:** confirmă callerii, URL-uri și credentiale printr-un proces secret-safe; identifică toate căile mutative și regulile de firewall. Măsoară timeouturile fără a modifica memoria.
2. **Mediu izolat:** construiește Understory de test cu date sintetice, verifică statusul, răspunsurile partial/no-effect și crash recovery. Nicio probă de scriere pe memoria de producție.
3. **Rendiv în shadow-readiness:** deploy-ul va fi separat și nu va primi mutații de producție până când DB, backup, auth, metrici și runbook sunt acceptate. Shadow mode nu dublează mutațiile către Understory.
4. **Sursă pilot:** migrează o sursă controlată la `POST /v1/jobs`, confirmă idempotency/status și observabilitate. Alte surse își păstrează fluxul până la propria fereastră.
5. **Pithagoras:** înlocuiește numai scrierile callerului pilot cu enqueue; menține conversația independentă de procesarea semantică și dezactivează direct-write doar pentru acel caller după validare.
6. **Home Assistant:** migrează loturile logice cu chei stabile; verifică retry-ul de transport, limitele și raportarea statusului.
7. **Închiderea bypass-urilor:** filtrează tool-uri și endpointuri directe, restricționează rețeaua, UI/API și accesul bundle; păstrează break-glass auditat. Nu declara gate global până când toți writerii sunt incluși.
8. **Operare graduală:** crește volumul după pragurile de acceptare, cu rollback per sursă și fără retry automat pentru rezultate ambigue.

## 10. Criterii de acceptare

- Callerii Pithagoras/HA obțin `202` și job ID după commit fără a aștepta Understory; failure înainte de commit nu este raportat ca acceptat.
- Reîncercarea de rețea folosește aceeași cheie și nu produce al doilea job; payload diferit cu aceeași cheie este respins.
- API status respectă ACL, nu divulgă payload/hash/credenciale și expune `unknown` explicit.
- Batch HA rămâne întreg; input peste limită este refuzat fără trunchiere sau split ascuns.
- Nu există două mutații Rendiv simultane; timeout/crash nu declanșează retry și păstrează gate-ul incert.
- Toate rutele de bypass din tabel sunt fie tehnic blocate/rutate, fie au owner, control compensator și excepție aprobată.
- Cerere Pithagoras aflată în așteptare primește următoarea admitere disponibilă înaintea unei noi cereri Understory background. Nicio operație activă nu este ucisă. Pentru un singur slot, întârzierea cauzată de apelul activ este cuantificată; SLO-ul se aprobă explicit.
- Restore și rollback au procedură repetată în mediu izolat; joburi `unknown` nu sunt retransmise automat.
- Metricile și alertele identifică stagnarea, rezultate incerte, lipsa spațiului și întârzierea interactivă fără a expune conținut.

## 11. Decizii deschise

1. Endpoint/host/TLS și identitățile service-to-service; locația procesului Rendiv nu este stabilită de baseline.
2. Rutele exacte prin care Pithagoras poate oferi enqueue fără a ține conversația; contractul plugin/tool și ID-ul stabil al evenimentului sursă.
3. Schema Home Assistant, event ID, payload max bytes, rate și comportamentul la input prea mare.
4. Politica de job ordering între surse și starvation; separată de priority classes pentru inference.
5. Suportul backend pentru gateway/admission, sloturi rezervate și toate clientele care trebuie rutate prin el.
6. Timeouturi și garanții de no-effect/reconciliere Understory; contract nou de status/idempotency dacă va fi posibil.
7. Auth mechanism, secret manager, rotație, acces operator și protecția endpointurilor Understory.
8. SLO-uri pentru enqueue, coadă, inference interactive și operarea batch-urilor; RPO/RTO și retenție.
9. Politica de read-only access MCP Pithagoras versus mutații; tratamentul portal `exclusive`, CLI, UI `/api/chat` și actorilor cu acces la host.
