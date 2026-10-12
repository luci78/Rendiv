# Contract MCP Understory V1 — statut și reguli aprobate

- **Origine:** contract propus în 6B.2E, revizuit prin deciziile 6B.2K-A
- **Stare:** regulile acestui checkpoint sunt **APROBATE pentru implementare offline**; contractul și integrarea rămân **NEAPROBATE pentru producție**. Validatorul offline din 6B.2G nu este integrat în adaptor/worker.
- **Data:** 2026-10-12
- **Domeniu:** răspunsurile operațiilor `memory_add`, `memory_update`, `memory_maintain` și maparea lor în Rendiv
- **Bază factuală:** sursele locale și limitele din `03-UNDERSTORY-CONTRACT.md` și `05-UNDERSTORY-CONTRACT-AUDIT.md`; runtime-ul este raportat separat mai jos

## 1. Identitatea runtime Understory

### Confirmat prin metadate Docker read-only

Comenzile utilizate au fost `docker ps --no-trunc --format '{{.ID}} {{.Image}} {{.Names}}'`, `docker inspect` formatat fără `.Config.Env` și `docker image inspect` formatat fără environment sau filesystem. Nu s-au folosit exec, logs, API, MCP ori comenzi de schimbare a stării.

| Câmp | Valoare observată |
|---|---|
| Container | `ai-understory` |
| Container ID | `2cb642db5307f38fb0f43fc41c3298f3b75f6f81fc0c537848ba2a1439bbd6e6` |
| Image reference configurat | `ai-stack-understory` |
| Image ID | `sha256:ad0699e1644f7ec75393c3335696be677b05a1c845e917e3a610a3a07f20ba7c` |
| Repo digest local | `ai-stack-understory@sha256:ad0699e1644f7ec75393c3335696be677b05a1c845e917e3a610a3a07f20ba7c` |
| Image created | `2026-10-09T17:10:41.792141804Z` |
| Container created | `2026-10-09T20:41:24.437353896Z` |
| Platformă | `linux/amd64` |
| Provenance labels | numai labels Compose (`project=ai-stack`, `service=understory`, versiune Compose); niciun label OCI source/revision/version identificat |
| Metadata discrepancy | container label `com.docker.compose.image` este `sha256:07615849ff7bade28438d3f3f22b47f301870deea76770735715a14982b04266`, diferit de `.Image`/image ID curent de mai sus |
| Comandă | entrypoint `docker-entrypoint.sh`; args `node server/dist/index.js` |
| Restart policy | `unless-stopped` |
| Mount | bind RW: `/home/luci78/ai-stack/data/understory/pithagoras` → `/bundle`; au fost citite numai metadatele mount-ului, nu conținutul |
| Rețea și port | `ai-stack_default`; container port `3800/tcp` publicat pe host `0.0.0.0:3800` |
| Environment | exclus intenționat din inspecție; valori neinspectate și neincluse |

ID-ul și repo digestul identifică artefactul local observat, nu commitul sursă. Discrepanța dintre labelul Compose al containerului și image ID curent este un indiciu că acel label nu poate fi tratat drept proveniență; cauza nu a fost investigată prin inspectarea configurației Compose externe. Labels și configurația imaginii nu conțin provenance verificabil pentru commit. `docker image inspect` nu a fost folosit pentru environment sau straturile de filesystem.

### Comparare cu checkout-ul local

Checkout-ul read-only `/home/luci78/ai-stack/understory` indică HEAD `f6c342332f390a444a8669636b1cf8f9669dd995`, cu working tree curat la verificare. Codul local are `packages/server/src/mcp/server.ts` și sursele descrise în documentele 03/05. Nicio dovadă inspectată nu leagă image ID/digest de acest commit. **Versiunea Understory din container este NECONFIRMATĂ.** Nu se deduce identitatea din tagul `ai-stack-understory` sau din timestamps.

Nu au fost citite configuri de build externe sau fișiere care pot conține secrete. Pentru o legătură verificabilă sunt necesare labels OCI buildate, de exemplu `org.opencontainers.image.revision` și `org.opencontainers.image.source`, sau provenance semnată/SBOM legată de digest, comparată cu sursa construită. Acest document nu afirmă că astfel de mecanisme există.

## 2. Statut și principii

Deciziile operatorului din checkpointul 6B.2K-A aprobă implementarea offline a regulilor din această revizie, fără schimbări la persistență și fără integrare Rendiv. Aprobarea nu este deployment approval: niciun rezultat nu deblochează FIFO, iar regulile de tranziție terminală rămân fail-closed. Validatorul independent `src/rendiv_api/mcp_contract_v1.py` și testele lui sunt cod local Rendiv și nu sunt actualizate în acest checkpoint documentar. Secțiunea runtime consemnează numai dovezile istorice 6B.2E; identitatea buildului activ rămâne neconfirmată.

V1 definește un obiect `structuredContent` în rezultatul MCP `tools/call`, păstrând textul `content` și semantica legacy `isError` pentru clienții existenți. Deciziile sunt aprobate pentru implementare offline; nu schimbă argumentele tool-urilor și nu aprobă integrarea de producție.

- ID-ul JSON-RPC corelează un exchange request/response.
- `operation_id` identifică o încercare Understory, dar nu e idempotency key și nu oferă status după restart.
- `applied` nu se emite pentru mutații în această versiune: V1 nu transportă dovada durabilă cerută. Rendiv păstrează orice raport insuficient demonstrat la `unknown/unknown`.
- Numai `memory_maintain` poate raporta `no_op`, exclusiv pe ramura healthy demonstrabilă; acest rezultat singur nu terminalizează jobul Rendiv. O mapare production la `succeeded/complete` necesită aprobare separată.
- Rezultat legacy, invalid, contradictoriu, necorelat sau insuficient demonstrat produce `unknown/unknown`, blochează FIFO și nu este reîncercat automat.

### Argumentele tool-urilor existente

| Operație | Arguments MCP existente |
|---|---|
| `memory_add` | `content: string` obligatoriu; `suggested_path?: string` |
| `memory_update` | `instruction: string` obligatoriu |
| `memory_maintain` | obiect gol `{}` |

V1 nu schimbă aceste arguments. Contractul de rezultat nu inventează semantica payloadurilor.

## 3. Schema V1 și validare strictă

Rezultatul aprobat pentru implementare offline este un JSON object cu `additionalProperties=false` la nivelul envelope-ului și `evidence`. După parsare trebuie să fie un singur obiect, fără chei duplicate la orice nivel. Compararea cheilor și enums este case-sensitive.

### Câmpuri de top-level

| Câmp | Cerință și tip | Regulă |
|---|---|---|
| `contract_version` | obligatoriu, string | Exact `understory-mcp-result/1`; orice altă valoare este incompatibilă pentru consumerul V1 |
| `request_id` | obligatoriu, string non-empty sau integer sigur JSON | Echo exact al ID-ului JSON-RPC al cererii; boolean, float, null, lipsă sau mismatch respins |
| `operation_id` | obligatoriu, string UUIDv7 lowercase | Unic pentru o singură încercare; nu reutilizat deliberat; nu promite persistență sau lookup |
| `operation` | obligatoriu, string enum | Exact unul din `memory_add`, `memory_update`, `memory_maintain`; trebuie egal cu tool-ul cerut |
| `outcome` | obligatoriu, enum | `applied`, `no_op`, `partial`, `rejected_before_write`, `unknown` |
| `no_op` | obligatoriu, boolean | Adevărat numai pentru outcome `no_op`; fals pentru toate celelalte |
| `changed_paths` | obligatoriu, array de string | Paths raportate; unice, sortate lexicografic, POSIX-relative, non-empty, fără absolute POSIX/Windows path, `.`/`..`, backslash, NUL sau newline. `[]` este valid când outcome-ul și evidence permit |
| `evidence` | obligatoriu, object exact | Câmpurile și combinațiile de mai jos |
| `reason_code` | condițional, string enum | Obligatoriu pentru `partial`, `rejected_before_write`, `unknown`; interzis pentru `applied` și `no_op`; numai allowlist V1 de mai jos |

`request_id` este identic valoric cu ID-ul JSON-RPC, nu cu `operation_id`. V1 acceptă JSON-RPC IDs string sau integer sigur; implementarea clientului trebuie să păstreze tipul și valoarea exactă.

**Conversia paths aprobată:** serializarea V1 transformă numai un path bundle-relative canonic Understory cu exact un slash sentinel inițial, de forma `/concepts/x.md`, în `concepts/x.md`. Nu elimină slash-uri dintr-un path absolut de sistem și nu schimbă valoarea internă ori textul legacy. Respinge slash-uri inițiale multiple, path gol, drive/UNC paths, `.`/`..`, backslash, NUL, newline și orice path care nu poate fi dovedit bundle-relative. Apoi sortează și verifică unicitatea. Conversia este doar normalizare de reprezentare; nu este dovadă de scriere, completitudine sau durabilitate.

### Câmpuri `evidence`

Toate câmpurile de aici sunt obligatorii, string enums, fără valori libere:

| Câmp | Enum permis |
|---|---|
| `execution` | `completed`, `not_completed`, `unknown` |
| `execution_path` | `mutating`, `healthy_no_op`, `rejected_pre_write`, `unknown` |
| `effect` | `reported_applied`, `reported_none`, `reported_partial`, `unknown` |
| `effect_scope` | `reported_paths_only`, `operation_scope`, `unknown` |
| `read_back` | `not_performed`, `observed_match`, `observed_mismatch`, `unknown` |
| `atomicity` | V1 numai `not_asserted` |
| `durability` | V1 numai `not_asserted` |

`read_back` este doar o observație a stării curente. Nicio valoare read-back nu dovedește singură identitatea cauzei, lipsa unei suprascrieri concurente, atomicitatea sau durability.

### Combinații permise pe outcome

| Outcome | `execution` | `execution_path` | `effect` | `effect_scope` | Paths | Alte reguli |
|---|---|---|---|---|---|---|
| `applied` | `completed` | `mutating` | `reported_applied` | `reported_paths_only` sau `operation_scope` | zero sau mai multe | `no_op=false`; fără `reason_code`; read_back nu poate fi `observed_mismatch`; atomicity/durability `not_asserted`. Forma rămâne rezervată; sursa actuală nu o emite pentru operații mutative fără dovadă durabilă, iar V1 nu are câmp pentru acea dovadă |
| `no_op` | `completed` | `healthy_no_op` | `reported_none` | `operation_scope` | exact `[]` | Numai `memory_maintain`; `no_op=true`; fără `reason_code`; read_back nu poate fi `observed_mismatch`; ramura trebuie demonstrată fără mutație |
| `partial` | `completed`, `not_completed` sau `unknown` | `mutating` sau `unknown` | `reported_partial` | `reported_paths_only`, `operation_scope` sau `unknown` | orice listă de paths valide | `no_op=false`; `reason_code` obligatoriu; nu afirmă că manifestul e exhaustiv |
| `rejected_before_write` | exact `not_completed` | exact `rejected_pre_write` | `reported_none` | `operation_scope` | exact `[]` | `no_op=false`; `reason_code` obligatoriu; garanție verificabilă upstream că niciun write nu a început |
| `unknown` | orice enum | `mutating` sau `unknown` | `reported_applied`, `reported_none`, `reported_partial` sau `unknown` | `reported_paths_only`, `operation_scope` sau `unknown` | orice listă validă | `no_op=false`; `reason_code` obligatoriu; nu produce tranziție terminală de succes/eșec; se aplică toate invariant-urile de mai jos |

În orice outcome, `atomicity` și `durability` rămân `not_asserted`. Pentru `no_op` și `rejected_before_write`, `read_back` poate fi numai `not_performed` sau `unknown`; o observație read-back nu face parte din proba acestor răspunsuri. Combinațiile neenumerate, inclusiv `no_op` incompatibil cu outcome-ul, `rejected_before_write` cu `execution=unknown`, sau `no_op` pe cale `mutating`, sunt invalide și Rendiv le tratează `unknown/unknown`. Deși schema descrie forma `applied`, producătorul Understory nu emite acest outcome pentru o operație mutativă până când există dovadă durabilă verificabilă și o revizie de contract care o poate reprezenta. În V1 curent `durability` este numai `not_asserted`, deci condiția nu poate fi satisfăcută de envelope-ul V1.

Invariant-uri între câmpurile `evidence` (valabile și pentru `unknown`): `effect=reported_applied` cere `execution=completed` și `execution_path=mutating`; `effect=reported_partial` cere `execution_path=mutating|unknown`; `execution_path=healthy_no_op` poate apărea numai la outcome `no_op`; `execution_path=rejected_pre_write` numai la `rejected_before_write`; `effect=reported_none` cu `effect_scope=operation_scope` este permis numai pentru `no_op` sau `rejected_before_write`. Dacă o dovadă observată nu poate fi reprezentată fără contradicție, envelope-ul nu se emite ca V1 valid și consumerul folosește `unknown` generic cu evidence `unknown`.

### Allowlist `reason_code`

V1 permite numai coduri statice, fără mesaj anexat: `invalid_arguments`, `policy_rejected`, `operation_failed`, `partial_effect`, `response_lost`, `upstream_timeout`, `transport_lost`, `invalid_upstream_result`, `unknown_internal`. Codurile necunoscute sau textul liber invalidează envelope-ul. Nu se includ stack traces, payloaduri, prompturi, căi absolute ori date din memorie.

### ID-urile și idempotency sunt trei lucruri diferite

1. **JSON-RPC `id` / `request_id`:** leagă un răspuns de un singur request protocolar. O retransmitere poate primi alt request ID.
2. **`operation_id`:** identificator opac UUIDv7 al unei încercări generate de Understory. Fără journal/status upstream, nu este căutabil durabil și nu previne duplicatele.
3. **Identitatea logică/idempotency:** lipsește din V1. Necesită cheie stabilă a intenției, stocare unică și returnarea rezultatului original; rămâne o extensie arhitecturală ulterioară.

## 4. Semantica outcome-urilor

- **`applied`:** schema descrie forma unui raport de aplicare, dar sursa actuală nu îl emite pentru mutațiile add/update sau maintain fără dovadă durabilă verificabilă. V1 nu are câmp care să poată purta acea dovadă (durability este obligatoriu `not_asserted`), deci outcome-ul este rezervat și nu este disponibil producerului în această revizie. Nici `changed_paths`, nici finalizarea agentului nu substituie dovada.
- **`no_op`:** handlerul raportează explicit încheierea fără modificări. În V1 combinația `healthy_no_op` este definită doar pentru calea healthy no-op a `memory_maintain`; nu presupune semantics no-op pentru add/update.
- **`partial`:** se emite numai când `MutationOutcome.status === "partial"` confirmă explicit că există cel puțin un efect raportat înainte de eșec. Paths rămân `reported_paths_only` și pot fi incomplete; nu afirmă durabilitate.
- **`rejected_before_write`:** outcome condițional, permis numai cu o ramură de respingere verificată înaintea primului write și cu dovadă verificabilă legată de acel apel/build. Eroarea, `isError`, lista goală sau absența unei căi raportate nu sunt dovadă. Sursa actuală nu are o asemenea dovadă structurată; Understory nu emite acest outcome în implementarea offline aprobată.
- **`unknown`:** efectul sau finalitatea nu sunt suficient cunoscute. Include timeout, deconectare, crash, răspuns pierdut, rezultat ambiguu și erori după intrarea în calea mutativă.

## 5. Exemple JSON și conformitate

Exemplele de mai jos sunt fixtures normative pentru validarea structurală și semantică. Toate folosesc `atomicity=durability=not_asserted`.

### Exemplul 1 — `memory_add`, succes raportat dar efect durabil neverificat

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-7f3b",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b01",
  "operation": "memory_add",
  "outcome": "unknown",
  "no_op": false,
  "changed_paths": ["concepts/example.md"],
  "evidence": {
    "execution": "completed",
    "execution_path": "mutating",
    "effect": "reported_applied",
    "effect_scope": "reported_paths_only",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "unknown_internal"
}
```

Răspunsul agentului și paths sunt raport, nu dovadă durabilă. De aceea envelope-ul emite `unknown`, nu `applied`; Rendiv păstrează `unknown/unknown`.

### Exemplul 2 — `memory_update`, finalizare agent fără dovadă suficientă

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-a18c",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b02",
  "operation": "memory_update",
  "outcome": "unknown",
  "no_op": false,
  "changed_paths": [],
  "evidence": {
    "execution": "completed",
    "execution_path": "mutating",
    "effect": "unknown",
    "effect_scope": "unknown",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "unknown_internal"
}
```

`runMutation()` poate încheia fără paths; nu se deduce că operația a fost aplicată sau că a fost no-op. Rezultatul rămâne `unknown/unknown`.

### Exemplul 3 — `memory_maintain`, healthy no-op raportat

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-91d2",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b03",
  "operation": "memory_maintain",
  "outcome": "no_op",
  "no_op": true,
  "changed_paths": [],
  "evidence": {
    "execution": "completed",
    "execution_path": "healthy_no_op",
    "effect": "reported_none",
    "effect_scope": "operation_scope",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  }
}
```

Envelope-ul singur nu e suficient pentru `succeeded`: trebuie versiune contract aprobată pentru producție, corelare exactă, implementarea/buildul identificat și dovada că această cale a verificat starea fără a intra în nicio ramură de mutație. Până la aceste gate-uri și aprobarea operatorului pentru producție, Rendiv rămâne `unknown/unknown`.

### Exemplul 4 — `memory_add`, respins înainte de orice scriere

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-1be4",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b04",
  "operation": "memory_add",
  "outcome": "rejected_before_write",
  "no_op": false,
  "changed_paths": [],
  "evidence": {
    "execution": "not_completed",
    "execution_path": "rejected_pre_write",
    "effect": "reported_none",
    "effect_scope": "operation_scope",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "invalid_arguments"
}
```

Fixture structural ipotetic, nu rezultat emis de implementarea actuală: `failed/none` este permis numai dacă upstream dovedește/enforcează că reject-ul a avut loc înaintea oricărui write. `isError=true` singur nu este dovadă; în sursa actuală nu există această ramură cu proof.

### Exemplul 5 — `memory_add`, rezultat incert raportat de Understory

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-7f3b",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b05",
  "operation": "memory_add",
  "outcome": "unknown",
  "no_op": false,
  "changed_paths": [],
  "evidence": {
    "execution": "unknown",
    "execution_path": "unknown",
    "effect": "unknown",
    "effect_scope": "unknown",
    "read_back": "unknown",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "upstream_timeout"
}
```

Valid ca rezultat structurat în care Understory raportează timeout intern și efect incert; rămâne `unknown/unknown`, blochează FIFO și nu se reîncearcă. Dacă răspunsul MCP însuși s-a pierdut și nu a ajuns la Rendiv, nu există acest envelope: Rendiv creează local rezultatul incert, fără să atribuie un `operation_id` upstream.

Toate cele cinci exemple se validează în §10 față de regulile din §3–4. ID-urile exemplificative sunt distincte în afară de stringul `request_id` reutilizat între două fixture-uri independente; fiecare fixture reprezintă un request separat. Într-un exchange real, duplicarea aceluiași răspuns este tratată după regulile fail-closed de mai jos.

## 6. Maparea Rendiv și blocarea FIFO

| Rezultat | Mapare Rendiv | FIFO / retry |
|---|---|---|
| `applied` structural valid (rezervat; producerul actual nu îl emite fără proof durabil) | `unknown/unknown`; nu se promovează din envelope/paths | Blochează, fără retry automat |
| `no_op` pentru `memory_maintain` valid și toate gate-urile demonstrate | `unknown/unknown` acum; `succeeded/complete` numai după gate-urile de producție și aprobare separată | Până la terminalizarea aprobată blochează; fără retry |
| `no_op` pentru `memory_add` / `memory_update` | `unknown/unknown`; semantica no-op nu este confirmată | Blochează, fără retry |
| `rejected_before_write` valid și upstream guarantee verificată | `failed/none` poate fi permis | Terminal fără retry al aceluiași job; următorul FIFO poate porni |
| `partial`, timeout, disconnect, crash, `unknown` | `unknown/unknown` | Blochează inclusiv după restart, fără retry |
| Legacy text-only, malformed, duplicate JSON keys, unknown fields/version, mismatch IDs/operation, contradiction, duplicate/conflicting result | `unknown/unknown` | Blochează, fără heuristic fallback și fără retry |
| JSON-RPC `error`, lipsă/mai multe rezultate structured sau rezultat mixt contradictoriu | `unknown/unknown` | Blochează, fără retry |
| MCP tool result cu `isError=true` și V1 `unknown` pentru `MutationOutcome.failed` legacy | `unknown/unknown`; textul și flagul legacy se păstrează, flagul nu dovedește no-effect | Blochează, fără retry |

**Semantica `succeeded`:** în Rendiv actual, workerul persistă `succeeded/complete` numai când executorul returnează explicit `SUCCEEDED`. Contractul v1 nu poate autoriza asta prin outcome `applied`; `applied` rămâne unknown. Pentru `memory_maintain` no-op, terminalizarea poate fi luată în considerare numai când toate condițiile sunt adevărate:

1. răspunsul include `structuredContent` exact conform V1 aprobat, fără chei lipsă/duplicate/necunoscute;
2. JSON-RPC id și `request_id` corespund exact requestului curent, iar `operation` este `memory_maintain`;
3. versiunea contractului este allowlisted și buildul Understory este identificat/provenance verificată;
4. outcome este `no_op`, `no_op=true`, `execution=completed`, `execution_path=healthy_no_op`, `effect=reported_none`, `effect_scope=operation_scope`, paths `[]`;
5. implementarea upstream demonstrează că healthy check este read-only și că nicio cale mutativă nu a fost invocată pentru acea cerere;
6. operatorul aprobă explicit maparea `memory_maintain no_op -> succeeded/complete`.

Dacă oricare condiție lipsește, rezultatul este `unknown/unknown`. `rejected_before_write -> failed/none` cere în mod similar contract și enforcement verificabil înainte de primul write; mesajul de eroare sau lista goală nu ajung.

## 7. Răspuns MCP, compatibilitate și erori

### Envelope exterior

- JSON-RPC 2.0 response trebuie să aibă exact un `id` și exact unul din `result` sau `error`.
- Pentru rezultat normal de tool, `result` include un singur `structuredContent` object V1; text `content` poate fi prezent ca text display legacy, dar nu este folosit la clasificare.
- `isError` absent este echivalent cu false. Pentru `applied`, `no_op` și `partial` este false. **Compatibilitate legacy aprobată:** `MutationOutcome.failed` continuă să întoarcă `isError=true` și textul legacy neschimbat; dacă este atașat un envelope V1 `unknown`, combinația este validă și se clasifică tot `unknown/unknown`. `isError=true` nu dovedește no-effect. Pentru `rejected_before_write`, `isError=true` este permis numai cu envelope valid și proof de zero scrieri verificabil; implementarea actuală nu îl emite.
- JSON-RPC `error` fără `structuredContent` clasifică unknown. Nu extrage outcome din mesajul error. Validatorul Rendiv existent respinge în prezent `isError=true` cu outcome `unknown`; contractul normativ este corectat prin decizia 6B.2K-A, iar paritatea validatorului este un gate separat înaintea integrării, fără schimbare în acest checkpoint.
- Lipsa răspunsului, zero sau mai multe candidate result envelopes, duplicate/conflict în același exchange, mismatch între JSON-RPC id și `request_id`, mismatch operation, invalid JSON, chei duplicate JSON sau tipuri invalide clasifică unknown.

### Câmpuri și rezultate invalide

V1 consumer folosește strict allowlistul de chei din §3. Câmpuri obligatorii lipsă, `reason_code` incorect prezent/absent, enum necunoscut, array/boolean/string cu tip greșit, paths duplicate/neordonate/necanonice, câmpuri extra, chei duplicate, ID invalid sau combinații contradictorii invalidează întregul rezultat. Nicio parte validă a unui rezultat invalid nu este folosită pentru `succeeded` sau `failed`.

### Clienți vechi

Textul `content` și valoarea legacy `isError` se păstrează pentru clienții existenți. Clientul vechi poate ignora `structuredContent`; SDK 1.29.0 a demonstrat că cele două câmpuri coexistă. Clientul poate continua să trateze `isError=true` ca eroare de tool, dar nu trebuie să îl interpreteze ca dovadă că nicio scriere nu a avut loc. Rendiv care cere V1 nu face fallback semantic la text `Files changed`; toate răspunsurile legacy text-only rămân unknown. Un timeout/disconnect al transportului poate împiedica livrarea oricărui envelope; în acel caz consumatorul tratează răspunsul absent ca unknown, fără a pretinde că serverul a putut răspunde. Rollout-ul presupus ar fi shadow/fake, apoi compatibilitate verificată; niciun transport real nu este parte din acest checkpoint.

## 8. Separarea contractului de mecanismele de recuperare

### Ce poate rezolva contractul structurat

- parser determinist în loc de prose heuristics;
- corelarea unui response cu exchange-ul curent;
- outcome explicit și no-op explicit;
- paths ca rezultat raportat, delimitat de read-back/durability;
- fail-closed pentru incompatibilitate și ambiguitate.

### Ce cere mecanism upstream separat

- operation journal durabil și lookup după timeout/restart;
- logical idempotency key persistată, deduplicare și returnarea rezultatului inițial la retry;
- fencing/semnalizare pentru a dovedi că operația nu mai rulează;
- manifest exhaustiv, atomicitate multi-file și recovery;
- proof no-effect verificabil după orice eroare care poate urma unui write;
- durability receipt și garanțiile efective ale filesystem/storage.

`operation_id`, JSON-RPC id, `changed_paths` și read-back-ul nu înlocuiesc aceste mecanisme.

## 9. Matrice de teste contractuale — doar proiectare

Matricea de mai jos este criteriu proiectat, nu dovadă de teste executate. Implementarea/testele offline aprobate folosesc fake MCP transport în memorie, fixtures JSON, SQLite numai unde se testează separat workerul, interdicție de socket și fără procese/servicii reale. Testele Understory pentru acest checkpoint nu au nevoie de SQLite.

### Cazuri pozitive per operație

| Fixture | `memory_add` | `memory_update` | `memory_maintain` | Așteptare |
|---|---:|---:|---:|---|
| Envelope `applied` structural valid (numai fixture de parser; producerul nu îl emite fără dovadă durabilă) | Da | Da | Da | Parser poate valida forma; source Understory curentă trebuie să emită `unknown`; Rendiv unknown, FIFO blocat |
| Envelope `applied` valid fără paths | Da | Da | Da | Parser acceptă explicit report-ul; Rendiv unknown, fără inferență din paths |
| `no_op` healthy branch | Nu se aplică | Nu se aplică | Da | Structural valid; înainte de build gate/aprobare unknown; după gate, testul de mapare poate verifica succeeded/complete fără stare nouă |
| `rejected_before_write` valid cu proof verificat (parser fixture) | Da | Da | Da | Parser acceptă; Understory actual nu emite; terminalizarea numai după gate/aprobare de producție |
| `partial` valid cu paths confirmate | Da | Da | Da | Parser acceptă; Understory producer emite numai dacă sursa confirmă efectul parțial; Rendiv unknown, FIFO blocat |
| `unknown` valid pentru response lost | Da | Da | Da | Worker unknown, coada blocată, fără apel executor repetat la restart |

### Cazuri negative per operație

| Caz | `memory_add` | `memory_update` | `memory_maintain` | Așteptare comună |
|---|---:|---:|---:|---|
| applied doar din text/paths legacy | Da | Da | Da | unknown; nu parsăm prose |
| outcome/apel operation mismatch | Da | Da | Da | unknown |
| request ID mismatch cu JSON-RPC / request | Da | Da | Da | unknown |
| operation ID lipsă/invalid/duplicat într-un rezultat | Da | Da | Da | unknown; operation ID nu devine idempotency |
| JSON invalid, chei duplicate, fields lipsă/extra | Da | Da | Da | unknown; nu logăm raw body |
| enums/tipuri/path malformate sau `no_op` contradictoriu | Da | Da | Da | unknown |
| rejected cu `execution=unknown` sau paths neempty | Da | Da | Da | schema invalidă, unknown; niciodată failed/none |
| no_op pe operation/path incompatibil | Da | Da | Da | unknown |
| partial, timeout înainte/după efect fake | Da | Da | Da | unknown, fără retry |
| disconnect, crash înainte/după claim, response duplicat/conflict | Da | Da | Da | unknown; recovery nu reexecută |
| `isError=true` legacy cu V1 unknown, JSON-RPC error, result lipsă/mai multe | Da | Da | Da | unknown; blochează FIFO; niciun indicator nu dovedește no-effect |

### Integrare fake cu worker/SQLite

1. Creează DB temporară prin migrațiile deja existente; nu adaugă sau modifică migrații.
2. Enqueue câte două joburi FIFO per scenariu și livrează envelope prin fake transport injectat.
3. Verifică atomicitatea job+audit pentru unknown, rejected terminal și (numai după gate aprobat) maintain no-op terminal.
4. Pentru unknown, timeout, disconnect, legacy și rezultat invalid, verifică starea `unknown/unknown`, eveniment audit fără payload/raw response, `stop_reason=unknown_blocks_queue`, al doilea job încă queued și restart fără reexecuție.
5. Pentru `rejected_before_write` cu proof fake verificabil, verifică `failed/none`, audit coerent și faptul că următorul FIFO poate fi claim-uit; testează separat că orice lipsă/inconsistență blochează.
6. Simulează două răspunsuri identice și două contradictorii pentru același exchange; transportul/adapterul trebuie să respingă ambiguitatea. Nu deduce dedupe între retry-uri cu JSON-RPC IDs diferite.
7. Verifică zero socketuri și zero apeluri externe; toate DB-urile sunt temporare.

## 10. Criterii de acceptare și decizii pendinte

### Criterii documentare/contractuale

- Schema exactă din §3 este implementabilă fără câmpuri ambigue și toate exemplele din §5 trec validarea structurală și combinațiile semantice.
- Test matrix §9 acoperă fiecare operație, pozitiv/negativ, parser, fake transport, worker, audit, FIFO și recovery.
- Nicio cale legacy/invalidă nu produce succes sau no-effect fail și nu există retry automat.
- Understory nu emite `applied` pentru mutații în această versiune V1; forma este rezervată până când există dovadă durabilă și contractul o poate reprezenta. Rendiv îl păstrează `unknown/unknown`.
- `memory_maintain no_op` poate fi raportat numai pe ramura healthy demonstrabilă; nu autorizează singur `succeeded/complete`.
- `partial` necesită confirmarea explicită a sursei; `rejected_before_write` nu se emite fără proof verificabil de zero scrieri.

### Decizii aprobate pentru implementare offline

- `isError=true` și textul legacy se păstrează pentru `MutationOutcome.failed`; V1 `unknown` poate coexista cu acest flag, iar flagul nu are semnificație de no-effect.
- Paths V1 sunt relative fără slash inițial; numai sentinelul de bundle confirmat se convertește, iar textul și paths interne nu se schimbă.
- Niciun outcome mutativ nu este `applied` fără proof durabil; V1 actual nu poate transporta asemenea proof, deci producerul emite `unknown`. `partial` cere confirmare explicită; `rejected_before_write` cere proof verificabil de zero scrieri.
- `memory_maintain no_op` este permis numai pe ramura healthy demonstrabilă fără mutații.
- Timeout, disconnect, crash și rezultate ambigue rămân unknown; fără retry. Request ID este numai corelare, nu idempotency.

### Decizii încă neaprobate pentru producție

1. Maparea `memory_maintain no_op -> succeeded/complete`; rămâne unknown în Rendiv până la gate-urile de build/provenance și aprobarea separată.
2. Emiterea și consumul `rejected_before_write`: sursa actuală nu are proof structurat; contractul nu definește un mecanism independent prin care consumerul să verifice claim-ul.
3. Orice dovadă de durabilitate și, implicit, utilizarea outcome-ului `applied`; schema V1 actuală are numai `durability=not_asserted`.
4. Provenance runtime: digestul containerului nu este legat verificabil de revision.
5. Journal, idempotency, status, recovery, atomicitate, durability, exactly-once sau retry sigur rămân în afara V1.

Contractul este aprobat numai ca țintă pentru implementare și teste offline. Nu aprobă deployment, integrarea live sau tranziții terminale Rendiv.

## 11. Proveniență și acțiuni

- Dovezi runtime din checkpointul 6B.2E: documentate în §1, fără reinspecție în acest checkpoint.
- Checkout local Understory consemnat anterior la `f6c342332f390a444a8669636b1cf8f9669dd995`; legătura cu imaginea runtime rămâne neconfirmată.
- Codul Rendiv actual din `understory_adapter.py` decodează numai text `content`, clasifică raportul `Files changed` ca unknown și nu recunoaște `structuredContent`/no-op. `worker.py` poate persista unknown și bloca FIFO; `FAILED_NO_EFFECT` fără proof verificabil devine unknown. Acestea sunt comportamente de cod local, nu implementarea V1.
- Validatorul independent adăugat în 6B.2G este numai parser/policy helper pentru fixture testing; nu este importat de adaptor sau worker și nu demonstrează conformitatea runtime Understory.
- În acest checkpoint s-au citit numai fișiere din Rendiv. Fără Docker, Understory extern, endpointuri, secrete, volume, memorie, teste sau operații de schimbare a stării.
