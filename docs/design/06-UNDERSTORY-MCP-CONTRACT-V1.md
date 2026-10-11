# Contract MCP Understory V1 — propunere

- **Checkpoint:** 6B.2E
- **Stare:** PROPUS; neimplementat și neaprobat pentru producție
- **Data:** 2026-10-11
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

## 2. Scopul și principiile V1

V1 propune un envelope JSON structurat în `structuredContent` al rezultatului MCP `tools/call`; textul `content` poate rămâne pentru clienți existenți. Contractul păstrează numele și argumentele actuale ale tool-urilor. El face explicit rezultatul raportat și dovezile disponibile, fără a pretinde atomicitate sau durabilitate.

- `operation_id` identifică o singură încercare în Understory. Fără journal persistent și deduplicare, el **nu** este cheie idempotentă și nu promite status disponibil după restart.
- `request_id` echo-ează exact ID-ul JSON-RPC primit (string sau integer în V1) și leagă envelope-ul de răspunsul protocolar. Nu reprezintă singur identitate logică pentru retry.
- `contract_version` este șirul constant `understory-mcp-result/1`.
- `changed_paths` sunt paths raportate de codul Understory, normalizate relativ la bundle; nu sunt automat manifest exhaustiv.
- `evidence` descrie strict ce observă serverul. `reported` nu înseamnă read-back; read-back nu înseamnă commit durabil.
- Răspunsurile trebuie să fie complete, corelate, valide și singulare. Lipsă, contradicție, versiune necunoscută, ID neconcordant sau parsare greșită înseamnă `unknown` în Rendiv.

### Argumentele tool-urilor păstrate

| Operație | Arguments MCP existente |
|---|---|
| `memory_add` | `content: string` obligatoriu; `suggested_path?: string` |
| `memory_update` | `instruction: string` obligatoriu |
| `memory_maintain` | `{}` |

V1 nu adaugă câmpuri la aceste argumente fără o schimbare separată de schema tool-ului. Serverul generează `operation_id`; clientul corelează prin JSON-RPC `id`. Introducerea unui client-supplied idempotency key ar aparține unei versiuni/extensii ulterioare.

## 3. Schema propusă pentru rezultat

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-7f3b",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b01",
  "operation": "memory_add",
  "outcome": "applied",
  "no_op": false,
  "changed_paths": ["concepts/example.md"],
  "evidence": {
    "execution": "completed",
    "effect": "reported_applied",
    "effect_scope": "reported_paths_only",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  }
}
```

Câmpurile sunt obligatorii. `changed_paths` poate fi `[]`; pentru `applied` gol trebuie totuși să existe explicit dovada că aplicația a terminat cu outcome applied. Fiecare path trebuie să fie normalizat, relativ, fără `..`, absolute path, NUL sau secret. Schema v1 nu trebuie să returneze payload, conținut de memorie, tokenuri, prompturi sau detalii de eroare sensibile.

Valorile `evidence` sunt enums, nu afirmații libere:

- `execution`: `completed`, `not_completed` sau `unknown`;
- `effect`: `reported_applied`, `reported_none`, `reported_partial`, `unknown`;
- `effect_scope`: `reported_paths_only`, `operation_scope`, `none`, `unknown`;
- `read_back`: `not_performed`, `observed_match`, `observed_mismatch`, `unknown`;
- `atomicity` și `durability`: V1 permite numai `not_asserted` până când implementarea upstream are mecanisme care pot demonstra afirmația.

`read_back` este opțional semantic și aici rămâne `not_performed`; includerea lui nu schimbă clasificarea. Chiar `observed_match` arată doar conținut curent. Dacă upstream nu poate furniza toate câmpurile sau dovada necesară pentru outcome-ul declarat, trebuie întoarsă `unknown` sau eroare MCP, iar Rendiv rămâne fail-closed.

## 4. Semantica outcome-urilor

| Outcome | Semnificație contractuală propusă | Condiții minime de validare | Limită |
|---|---|---|---|
| `applied` | Handlerul a ajuns la finalul operației și Understory raportează că acțiunea solicitată a fost aplicată | Envelope valid/corelat; `execution=completed`, `effect=reported_applied`; pentru paths, listă normalizată. Nu poate fi dedus numai din `changed_paths` | Succes raportat de aplicație. Fără afirmație de atomicitate, fsync, commit durabil sau supraviețuire la crash |
| `no_op` | Handlerul s-a încheiat explicit și confirmă că nu a fost necesară/aplicată nicio modificare pentru această invocare | `no_op=true`, `execution=completed`, `effect=reported_none`, `effect_scope=operation_scope`, `changed_paths=[]`; only for operation paths whose semantics define no-op. Pentru maintain trebuie rezultat structurat, nu matching prose în Rendiv | Confirmă rezultatul operației la nivelul handlerului, nu durabilitatea bundle-ului |
| `partial` | Handlerul observă că o parte din acțiune s-a aplicat sau că au existat efecte incomplete | `execution=completed` sau `not_completed`, `effect=reported_partial`; paths cunoscute pot fi listate | Fără rollback/receipt exhaustiv; Rendiv îl tratează incert și blochează FIFO |
| `rejected_before_write` | Cererea a fost refuzată înainte să înceapă orice operație de scriere | `execution=not_completed`, `effect=reported_none`, `effect_scope=operation_scope`, `no_op=false`, paths goale; reject reason enum non-sensitive; implementarea upstream trebuie să enforce-ască rejection înaintea primului write | Nu este generalizabil la erori după pornirea agentului; nu se emite dintr-un simplu `failed` |
| `unknown` | Nu există suficiente dovezi pentru alt outcome, ori efectul poate fi parțial/neclar | Folosit explicit pentru timeout intern, disconnect, crash, eroare după începutul operației, răspuns ambiguu/invalid și orice câmp/proveniență lipsă | Terminal în Rendiv până la reconciliere umană; fără retry automat |

Pentru `no_op`, `applied` și `rejected_before_write`, `no_op` trebuie să fie coerent cu outcome-ul: true numai pentru `no_op`, false pentru celelalte. Pentru `partial` și `unknown` câmpul este false; incertitudinea nu poate fi codificată drept no-op.

## 5. Exemple JSON

Exemplele sunt payloadul `structuredContent`, nu afirmații despre răspunsul runtime actual.

### `memory_update` applied — succes raportat, nu durable

```json
{
  "contract_version": "understory-mcp-result/1",
  "request_id": "rendiv-call-a18c",
  "operation_id": "0199c0a4-6b3a-7f20-a019-fc6f1d2a8b02",
  "operation": "memory_update",
  "outcome": "applied",
  "no_op": false,
  "changed_paths": ["concepts/example.md"],
  "evidence": {
    "execution": "completed",
    "effect": "reported_applied",
    "effect_scope": "reported_paths_only",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  }
}
```

### `memory_maintain` healthy no-op explicit

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
    "effect": "reported_none",
    "effect_scope": "operation_scope",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  }
}
```

### `memory_add` rejected before write

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
    "execution": "unknown",
    "effect": "reported_none",
    "effect_scope": "operation_scope",
    "read_back": "not_performed",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "invalid_arguments"
}
```

### `memory_add` rezultat incert

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
    "execution": "not_completed",
    "effect": "unknown",
    "effect_scope": "unknown",
    "read_back": "unknown",
    "atomicity": "not_asserted",
    "durability": "not_asserted"
  },
  "reason_code": "response_lost"
}
```

`reason_code` trebuie să aparțină unei allowlist non-sensitive. Răspunsul JSON-RPC/MCP însuși trebuie să aibă ID egal cu `request_id`; diferența dintre cele două ID-uri invalidează envelope-ul.

`reason_code` este obligatoriu pentru `rejected_before_write` și `unknown`, opțional pentru `partial` și interzis pentru `applied`/`no_op`. Allowlist-ul V1 include numai coduri statice fără text liber, de exemplu `invalid_arguments`, `policy_rejected`, `operation_failed`, `partial_effect`, `response_lost`, `upstream_timeout`, `transport_lost`, `invalid_upstream_result` și `unknown_internal`; mesajele excepțiilor nu se includ.

## 6. Matricea rezultat → Rendiv

| Operație și răspuns | Verificări | Mapare Rendiv propusă | FIFO/retry |
|---|---|---|---|
| Oricare: `applied` V1 valid și corelat | `execution=completed`, `effect=reported_applied`, operation se potrivește, schema/version/ID valide | `succeeded`, `effect_certainty=complete` în sensul strict „Understory a raportat outcome terminal applied”; nu înseamnă durability/atomicity. Păstrați evidence în audit metadata numai în formă sigură | Avansează; fără retry |
| Oricare: `applied` doar cu paths, fără explicit evidence | Incomplet sau inconsistent față de V1 | `unknown/unknown` | Blochează FIFO; fără retry |
| `memory_maintain`: `no_op` V1 valid | Explicit `execution=completed`, `reported_none`, operation-scope și no paths | `succeeded/complete`; rezultat terminal fără mutație raportată | Avansează; fără retry |
| `memory_add`/`memory_update`: `no_op` V1 valid | Doar dacă semantics upstream declară că no-op este rezultat valid pentru această operație | Până la aprobarea semanticii operației: `unknown/unknown`; v1 consumer conservator poate respinge outcome-ul ca nesuportat | Blochează FIFO |
| `rejected_before_write` valid | Structurat, corelat și upstream garantează respingere înainte de primul write | `failed/none` | Job terminal, următorul poate rula; fără retry automat al aceluiași job |
| `partial` | Indiferent de paths; inclusiv paths goale | `unknown/unknown` | Blochează FIFO; reconciliere umană; fără retry |
| `unknown`, timeout, disconnect, crash, răspuns absent | Orice lipsește sau efectul nu e clar | `unknown/unknown` | Blochează FIFO inclusiv după restart; fără retry |
| Legacy text-only, versiune necunoscută, JSON invalid, ID/operation mismatch, câmpuri contradictorii/extra-sensitive | Nu satisface V1 strict | `unknown/unknown` | Blochează FIFO; nu încerca heuristic parsing |
| `isError=true` fără un envelope V1 valid `rejected_before_write` | Nu există proof de no-effect | `unknown/unknown` | Blochează FIFO |

Maparea `applied -> succeeded/complete` este o **propunere contractuală** care ridică succesul raportat la terminalitatea explicită a handlerului, nu la durability. Înainte de acceptare, operatorul trebuie să aprobe această definiție de `succeeded` pentru Rendiv. Dacă `succeeded/complete` în schema actuală este interpretat ca durabil/atomic, rămâne incompatibil și e necesară o decizie arhitecturală sau o stare/field semantic suplimentar; nu se implementează implicit.

## 7. Compatibilitate și fail-closed

- V1 poate păstra tool names, input schemas și MCP text `content` existent, adăugând `structuredContent` pentru clienți capabili să îl consume.
- Clienții MCP existenți care ignoră `structuredContent` ar trebui să continue să vadă textul; această compatibilitate trebuie verificată contra versiunii reale a SDK/protocolului înainte de implementare.
- Rendiv V1 strict acceptă doar `structuredContent` complet, versionat și corelat. Fallback-ul vechi pe `Files changed` sau prose nu poate produce `succeeded` ori `failed/none`; el devine `unknown`.
- Downgrade/rollout: Understory poate servi V1 și textul simultan, dar Rendiv rămâne în shadow/fake până la verificarea contractului pe buildul identificat și la aprobarea operatorului. Nu se activează writerul real doar pentru că imaginea răspunde cu JSON.
- `rejected_before_write` necesită contract/server enforcement care garantează că reject-ul precede toate efectele. `isError` singur nu este fallback suficient.

## 8. Ce rezolvă envelope-ul și ce nu

### Poate rezolva prin contract structurat

- Parse determinist al outcome-ului în locul interpretării prozei.
- Corelarea răspunsului la cererea MCP curentă (`request_id`) și atribuirea rezultatului unei încercări (`operation_id`).
- Explicitarea no-op-ului healthy la `memory_maintain` și delimitarea paths raportate de no-op.
- Distincția explicită între applied, partial, rejected-before-write și unknown.
- Validare fail-closed la răspuns vechi, invalid, necorelat sau contradictoriu.

### Necesită ulterior journal/idempotency/status upstream

- Rezolvarea timeoutului după ce răspunsul s-a pierdut; V1 `operation_id` nu permite lookup după restart.
- Deduplikarea retransmiterilor și retry sigur; `request_id` JSON-RPC corelează un exchange, nu o intenție persistentă.
- Reconcilierea după crash sau deconectare și demonstrarea că handlerul s-a oprit.
- Proof complet no-effect pentru eșecuri după începutul mutației.
- Manifest exhaustiv și boundary atomic pentru efecte concept/index/log.
- Confirmarea durabilității filesystemului (staging/commit/fsync și garanția storage) și recuperarea după crash.

Nu folosiți read-back singur ca substitute pentru journal/idempotency sau durability receipt.

## 9. Criterii de acceptare și plan de testare izolat

Criterii pentru o implementare viitoare, fără servicii reale:

1. Schema strictă validează operation/version/request ID, tipurile, enums, paths și coerența no_op/outcome; payloaduri malformate sunt respinse fără logarea conținutului.
2. Fiecare dintre cele trei tool-uri are teste contractuale pentru `applied`, răspunsuri fără paths, healthy maintain no-op, partial, rejected-before-write și unknown.
3. Cazurile `applied` fără dovada terminală, `failed` fără proof, răspuns text-only, ID mismatch, duplicate/conflict, unknown version, missing/extra contradictory fields și JSON invalid devin `unknown`; nu există retry.
4. Unit tests verifică serializarea/decodarea `structuredContent` prin fake MCP transport și corelarea JSON-RPC. Testele nu deschid socketuri și monkeypatch-uiesc conectivitatea de rețea să eșueze.
5. Integrarea cu workerul folosește SQLite temporar: `unknown` blochează FIFO, `rejected_before_write` poate fi terminal numai cu proof fake valid, iar auditul nu stochează payload sau prose sensibile.
6. Teste de compatibilitate rulează fixtures legacy text-only și un client fake ce ignoră `structuredContent`; nu contactează server activ.
7. Testele de durability/journal/idempotency sunt în afara contractului V1; nu pretind că fake-urile validează comportamentul filesystem/runtime Understory.

Gate de implementare separat: identificarea buildului activ prin provenance verificabilă, aprobarea semanticii Rendiv `succeeded/complete`, aprobarea contractului/schema și verificarea compatibilității SDK MCP. Niciunul nu a fost satisfăcut prin acest document.

## 10. Surse și acțiuni

- Dovezi runtime: metadatele Docker enumerate în §1; environment exclus; nicio cerere către servicii.
- Checkout local: commit `f6c342332f390a444a8669636b1cf8f9669dd995`; legătura cu imaginea activă neconfirmată.
- Referințe statice ale tool schemas, outcome și healthy no-op: `docs/design/05-UNDERSTORY-CONTRACT-AUDIT.md`, secțiunile 3–5 și 9, cu surse din `packages/server/src/mcp/server.ts` ale checkout-ului.
- Reguli existente privind certitudinea și workerul Rendiv: `docs/design/04-EFFECT-CERTAINTY-AUDIT.md`.
- Nu s-au citit environment values, logs, filesystem/volume, DB sau memory contents; nu s-au apelat API/MCP/LLM/health; nu s-au modificat imagini, containere ori servicii.
