# Audit: certitudinea efectelor și tranzițiile workerului

- **Checkpoint:** 6B.2C
- **Data:** 2026-10-11
- **Domeniu:** cod Rendiv local, contractul documentat în `03-UNDERSTORY-CONTRACT.md`, transport fake și SQLite temporar. Fără servicii sau mutații reale.
- **Stare:** deciziile operatorului din checkpoint au fost aplicate local; nu este necesară schimbare de schemă sau API.

## 1. Concluzii

1. `changed_paths` este numai succes raportat de Understory. Nu dovedește read-back independent ori durabilitate. Adaptorul îl mapează acum la `unknown/unknown`, cu `reason_code=reported_success_unverified`; jobul blochează FIFO până la reconciliere umană. Read-back-ul poate adăuga dovezi, dar nu garantează atomicitate sau durabilitate tranzacțională.
2. `LocalWorker` tratează `FAILED_NO_EFFECT` fără dovadă structurată și verificabilă ca `unknown/unknown`, cu `reason_code=no_effect_unproven`. În prezent `ExecutionResult` nu transportă o dovadă verificabilă, iar contractul Understory nu definește una; prin urmare workerul nu poate încheia un job în `failed` pe acest traseu.
3. Contractul documentează o cale healthy no-op pentru `memory_maintain`, dar nu specifică un marker textual stabil care să poată fi validat din răspuns. Răspunsul fără căi rămâne `unknown/unknown`, cu `reason_code=maintain_response_unverified`. O confirmare explicită, neambiguă și validabilă poate fi tratată drept succes terminal `succeeded/complete`, fără stare nouă; markerul curent nu este confirmat, deci adaptorul nu presupune că există.
4. `running -> unknown` la crash/restart, tranzițiile și auditul sunt fail-closed și tranzacționale; nu există retry automat. Rezultatul necunoscut blochează coada și după restart.
5. Fiecare cerere JSON-RPC folosește ID UUID per apel pentru corelare. ID-ul nu este idempotency key.

Punctele 1–3 cer o decizie despre semantica rezultatului și disponibilitate; nu au fost schimbate stările, schema sau semantica globală.

## 2. Dovezi: rezultat raportat, efect observat, persistență durabilă

Contractul 03 descrie succesul aplicației ca `runMutation` terminat fără excepție și `ok: true`; callback-urile adaugă căile în `filesChanged` după ce metodele KnowledgeBase se rezolvă. O listă nevidă este, așadar, un raport al Understory despre metodele care au terminat. În implementarea Rendiv, adaptorul caută secțiunea textuală `Files changed:` și cere cel puțin o cale; nu citește bundle-ul și nu verifică acea cale.

| Nivel | Ce dovedește contractul/sistemul | Ce nu dovedește |
|---|---|---|
| Succes raportat | Răspuns fără `isError`, cu căi nevid listate; Understory raportează completarea metodei și căile schimbate | Că intenția semantică a fost satisfăcută complet; că textul este un receipt independent de server |
| Efect observat | Nu există read-back Rendiv în adaptor/worker. Contractul 03 spune că un operator poate examina read-back pentru reconciliere, dar nu definește endpoint sau procedură automată | Existența actuală a fișierului și conținutul său post-mutație |
| Persistență durabilă confirmată | Niciun fsync/receipt de durabilitate sau contract de commit durabil nu este expus către Rendiv în contractul 03 | Supraviețuirea unei opriri/crash de host după răspuns |

`succeeded/complete` nu mai este emis pentru un simplu raport de căi. În modelul actual, `unknown/unknown` păstrează starea incertă și blochează workerul; `reason_code` din audit păstrează cauza fără schimbare de schemă/API. O reconciliere viitoare poate adăuga dovadă read-back, dar trebuie să nu o prezinte drept garanție de commit durabil sau atomic.

## 3. Matricea operațiilor

Tabelul de bază se aplică la `memory_add` și `memory_update`; payloadurile lor diferă conform contractului 03. No-op-ul documentat se aplică lui `memory_maintain`. Starea indicată este comportamentul actual adaptor → worker, cu excepția coloanei „dacă workerul primește FAILED_NO_EFFECT”, care descrie interfața generală a workerului.

### `memory_add`

Argumente: `content` obligatoriu string, `suggested_path` opțional string.

| Scenariu | Dovadă disponibilă | Certitudine | Stare permisă/actuală | Reexecuție | Lipsă pentru reconciliere |
|---|---|---|---|---|---|
| Succes cu changed paths | Text fără `isError`, fără marker partial, cu listă de căi | Succes raportat, nu efect/durabilitate confirmate | Actual: `unknown/unknown`; audit `reported_success_unverified` | Nu; blochează coada | Read-back al conținutului și dovada terminării; read-back-ul nu oferă garanție tranzacțională |
| Succes fără changed paths / `none` | Text de succes, dar fără cale | Ambiguu; contractul spune că nu confirmă efectul cerut | `unknown`, coada blocată | Nu | Outcome mașinabil și lookup/read-back |
| No-op | Nu este rezultat normal specific add; text fără căi nu îl distinge sigur de răspuns incomplet | `unknown` | `unknown` | Nu | Cod de no-op explicit și semantica lui |
| Failed | `isError`/text failed; nu este garantat no-effect | `unknown`, nu `failed/none` | `unknown`, coada blocată | Nu | Dovadă că niciun fișier/efect derivat nu s-a schimbat și că agentul s-a oprit |
| Efect parțial | Marker partial / unele scrieri raportate înainte de eroare | `unknown` în adaptor; efect parțial posibil | `unknown`, coada blocată | Nu | Manifest complet înainte/după, terminarea handlerului, reconciliere |
| Timeout înainte/după efect | Doar timeout; fake-ul distinge efectul simulat, protocolul real nu | `unknown` (worker persistă timeout ca unknown) | `unknown`, coada blocată | Nu | Status de execuție și read-back independent |
| Disconnect | Lipsă răspuns; efectul poate fi aplicat | `unknown` | `unknown`, coada blocată | Nu | Confirmarea terminării și a efectului |
| Răspuns invalid | JSON-RPC/CallToolResult invalid, ID greșit sau mesaj contradictoriu | `unknown` | `unknown`, coada blocată | Nu | Răspuns corelat verificabil; lookup de status |
| Crash în timpul execuției | Rândul Rendiv a rămas `running`; nu există răspuns fiabil | `unknown` | Restart: `running -> unknown`, audit append-only | Nu | Dovezi destinație și absența execuției active |
| Răspuns duplicat/contradictoriu | ID diferit/refolosit este respins; result+error este invalid. Transportul `exchange` livrează un singur mesaj | `unknown` pentru conflict/ID necorelat; duplicat identic cu ID curent nu poate fi distins de răspunsul curent | `unknown` dacă decodorul detectează contradicția | Nu | Transport/session ID și lookup/receipt; duplicate handling explicit |

### `memory_update`

Argumente: `instruction` obligatoriu string. Clasificările sunt aceleași ca pentru add; răspunsul cu căi confirmă doar ceea ce a raportat agentul în fișierele listate.

| Scenariu | Dovadă disponibilă | Certitudine | Stare permisă/actuală | Reexecuție | Lipsă pentru reconciliere |
|---|---|---|---|---|---|
| Succes cu changed paths | Căi nevid raportate | Succes raportat, nu read-back ori durabilitate | Actual: `unknown/unknown`; audit `reported_success_unverified` | Nu; blochează coada | Read-back și criteriul rezultatului; nicio garanție tranzacțională |
| Succes fără changed paths / no-op | Niciun path; contractul nu oferă semnificație sigură pentru update fără schimbare | `unknown` | `unknown`, coada blocată | Nu | Outcome explicit no-op vs. agentul nu a făcut editarea |
| Failed | `isError` fără garanție no-effect | `unknown` | `unknown` | Nu | Garanție no-effect pentru toate ferestrele de scriere |
| Efect parțial | Marker partial/căi raportate înaintea eșecului | `unknown`, posibil partial | `unknown` | Nu | Snapshot/manifest și reconciliere |
| Timeout înainte/după efect | Timeout fără status upstream | `unknown` | `unknown` | Nu | Status/read-back și terminarea upstream |
| Disconnect | Răspuns absent | `unknown` | `unknown` | Nu | Status/read-back |
| Răspuns invalid | Decodorul respinge envelope/ID/content incorect | `unknown` | `unknown` | Nu | Răspuns valid corelat sau lookup |
| Crash în timpul execuției | Claim `running`, fără receipt | `unknown` după restart și audit | `unknown` | Nu | Dovada efectului și a opririi upstream |
| Răspuns duplicat/contradictoriu | ID greșit ori JSON-RPC cu `error` și `result` | `unknown` când este detectat | `unknown` | Nu | Corelare și idempotency/status |

### `memory_maintain`

Argumente: obiect gol `{}`. Dacă graful e sănătos, Understory întoarce healthy no-op fără agent; dacă găsește probleme, folosește agentul și poate schimba fișiere.

| Scenariu | Dovadă disponibilă | Certitudine | Stare permisă/actuală | Reexecuție | Lipsă pentru reconciliere |
|---|---|---|---|---|---|
| Succes cu changed paths | Căi raportate de helper după outcome `ok` | Succes raportat; nu read-back/durabilitate | Actual: `unknown/unknown`; audit `reported_success_unverified` | Nu; blochează coada | Read-back și criteriul rezultatului; nicio garanție tranzacțională |
| Succes fără changed paths | Helperul de mutație poate raporta zero căi | Ambiguu pentru handlerul cu agent | `unknown` | Nu | Distincție mașinabilă între agent no-op și răspuns incomplet |
| Healthy no-op | Contractul confirmă calea no-op, dar nu definește un marker textual stabil validabil aici | Necunoscut până la identificarea răspunsului explicit și neambiguu | Actual: `unknown/unknown`; audit `maintain_response_unverified` | Nu; blochează coada | Marker de răspuns stabil din contract; validare că handlerul s-a încheiat și nu a modificat nimic |
| Failed | `isError` nu dovedește no-effect | `unknown` | `unknown` | Nu | Garanție no-effect/status |
| Efect parțial | Agentul a raportat fișiere înainte de eșec | `unknown`, posibil partial | `unknown` | Nu | Manifest complet și terminarea handlerului |
| Timeout înainte/după efect | Nu există status upstream | `unknown` | `unknown` | Nu | Status/read-back |
| Disconnect | Răspuns absent; handlerul poate continua | `unknown` | `unknown` | Nu | Confirmarea terminării și efectului |
| Răspuns invalid | Envelope/content/ID invalid | `unknown` | `unknown` | Nu | Status/read-back |
| Crash în timpul execuției | Jobul rămâne `running` | `unknown` după recovery | `unknown` | Nu | Dovezi destinație, inclusiv dacă era healthy/no-op |
| Duplicat/contradictoriu | Conflict de ID/error-result respins; rezultat text repetat nu oferă un receipt | `unknown` dacă necorelat; identic cu ID curent nedetectabil | `unknown` la invaliditate | Nu | Receipt/status și politici duplicate |

Pentru toate operațiile, un `FAILED_NO_EFFECT` fără dovadă structurată/verificabilă este convertit de worker în `unknown/unknown` și nu eliberează coada. Nici adaptorul simulat, nici contractul Understory actual nu produc o astfel de dovadă.

## 4. Flux adaptor → worker → SQLite → audit

1. `validate_job()` validează numele și argumentele. Cererile invalide nu ajung la transport.
2. `serialize_tool_call()` construiește un JSON-RPC `tools/call`; ID-ul UUID nou este doar pentru corelare.
3. `McpTransport.exchange()` este numai interfață injectată. Timeoutul, excepția de transport, mesajul malformed, ID-ul incorect, `isError`, textul partial și lipsa unei liste nevid de căi nu devin succes.
4. `classify_effect()` clasifică lista textuală de căi drept succes raportat, iar adaptorul întoarce `UNKNOWN` cu motiv auditabil `reported_success_unverified`. Rezultatele neclasificabile devin `UNKNOWN`/`TIMEOUT`. Adaptorul nu emite `FAILED_NO_EFFECT`. Pentru `memory_maintain`, un răspuns fără listă de căi primește motivul `maintain_response_unverified`; nu este promovat fără marker explicit validabil.
5. `LocalWorker.run_until_idle()` ține lock POSIX `flock`, face claim FIFO în `BEGIN IMMEDIATE`, execută executorul în afara tranzacției DB, apoi finalizează.
6. `_finish()` scrie schimbarea jobului și evenimentul în aceeași tranzacție. Eșecul auditului rollback-ează tranziția; crash-ul lasă `running`, pe care pornirea următoare îl transformă în `unknown`.
7. Orice `unknown` existent este detectat la recovery și înaintea claim-ului. Coada se oprește; nu există retry sau bypass automat.

### `failed` și dovada no-effect

`worker.py` nu mai acceptă enum-ul `FAILED_NO_EFFECT` ca probă. Fără dovadă verificabilă el persistă `unknown/unknown`, cu motiv `no_effect_unproven`; testul de regresie confirmă că următorul job rămâne queued. Nu există în contractul local un format ori verificator pentru o dovadă no-effect. Nu s-a adăugat un format ipotetic; niciun executor actual nu poate obține `failed/none` prin această interfață.

## 5. Atomicitate, retry și redacție

- Claim-ul `queued -> running` și eventul `worker_claimed` sunt în aceeași tranzacție SQLite `BEGIN IMMEDIATE`/COMMIT.
- Finalizarea (`succeeded`, `failed` ori `unknown`) și eventul aferent sunt într-o tranzacție. La excepție se face rollback; dacă rezultatul nu poate fi persistat, jobul rămâne `running` și recovery îl schimbă în `unknown`.
- FIFO este după `queue_seq`; workerul deține `flock` pe durata execuției. Garanția depinde de filesystem local POSIX și de cooperarea tuturor workerilor.
- Nu există retry: un rezultat nonterminal oprește run-ul; `unknown` blochează și pornirile ulterioare. Răspunsurile duplicate nu duc la a doua execuție de către worker.
- Workerul nu loghează payloadul sau textul rezultatului. Evenimentele worker folosesc `metadata_json='{}'`, tipuri/coduri statice și ID-ul workerului; enqueue stochează principalul tehnic ca actor, nu credentialul. Payloadul rămâne în tabelul jobs conform scopului sistemului, nu în audit. Testul cu canary confirmă că payloadul nu apare în evenimente sau logurile capturate.

## 6. Verificări locale

Teste noi în `tests/test_effect_certainty_audit.py` folosesc numai transport in-memory și SQLite temporar. Împreună cu `tests/test_understory_adapter.py` și `tests/test_worker.py`, verifică fiecare operație, succes raportat cu/fără căi, no-op maintain, failed, partial, timeout înainte/după efect simulat, disconnect înainte/după, invalid/contradictoriu, duplicate cu ID vechi, crash/recovery, lipsa retryului, blocarea cozii, audit și redacție.

Suita completă după aplicarea deciziilor: 141 teste PASS; `pip check` și `git diff --check` PASS. Aceste teste demonstrează clasificarea și tranzițiile Rendiv, nu verifică adevărul unui răspuns real Understory, efectul pe bundle sau durabilitatea filesystemului.

## 7. Deciziile operatorului aplicate și limite rămase

1. **`changed_paths`:** este succes raportat de Understory, nu dovadă de durabilitate. Nu este suficient pentru `succeeded/complete`; adaptorul produce `unknown/unknown`, iar evenimentul append-only păstrează `reported_success_unverified`. Acest comportament blochează coada după fiecare asemenea rezultat, până la o reconciliere umană. Read-back-ul poate confirma conținut observabil suplimentar, dar nu este garanție de tranzacție ori de durabilitate după crash.
2. **`FAILED_NO_EFFECT`:** fără dovadă structurată și verificabilă nu poate produce `failed/none`. Interfața curentă nu are format/verificator de proof, astfel că orice rezultat enum simplu este convertit la `unknown/unknown` cu `no_effect_unproven`. Integrarea viitoare trebuie să definească și să verifice o dovadă reală înainte de a activa această tranziție; nu s-a inventat una.
3. **`memory_maintain` no-op:** succesul terminal ar fi permis numai pentru confirmarea explicită, neambiguă și validabilă că operația s-a încheiat fără modificări; în modelul existent acesta poate fi `succeeded/complete`, fără stare nouă. Contractul local confirmă că există o cale healthy no-op, dar nu oferă un marker textual stabil pentru adaptor. Rezultatul rămâne deci `unknown/unknown` cu `maintain_response_unverified` și blochează coada.

Nu este necesară migrare sau schimbare a API-ului public: modelul actual reprezintă situațiile neconfirmate prin `unknown` și auditul append-only prin coduri de motiv existente. Faptul că starea publică `unknown` blochează FIFO este impactul disponibilității acceptat de clasificarea prudentă. Nu s-au schimbat schema, enum-ul de stări, endpointurile sau semantica globală. Înainte de integrarea reală rămân necesare: dovada de succes pe care operatorul o acceptă după read-back, markerul Understory verificabil pentru no-op și formatul/verificatorul unei dovezi de no-effect. Acestea nu sunt confirmate de contractul runtime actual.
