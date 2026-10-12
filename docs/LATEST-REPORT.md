# Raport Rendiv — Checkpoint 6B.2H: compatibilitate MCP SDK și integrare simulată

Data: 2026-10-12

## Domeniu și fișiere

A fost verificată offline versiunea MCP SDK indicată de checkout-ul Understory și a fost adăugat un harness exclusiv de test pentru traseul simulabil: răspuns MCP fake → validator V1 → clasificare Rendiv → poarta FIFO în SQLite temporar.

Fișiere modificate:

- `tests/test_mcp_contract_fifo_simulation.py` — transport fake în memorie, tabel SQLite creat sub `tmp_path`, cazuri pentru operații/outcome-uri și răspunsuri invalide.
- `docs/design/07-MCP-SDK-COMPATIBILITY.md` — dovezi, limitele verificării SDK și deciziile necesare.
- `docs/DEVELOPMENT.md` — progresul checkpointului.
- `docs/LATEST-REPORT.md` — raportul curent.

Nu au fost modificate codul de producție, adaptorul, workerul, schema, API-ul, migrațiile, configurația deploymentului sau infrastructura. Nu s-au folosit Docker, servicii active, rețea, MCP/LLM, secrete, tokenuri ori memorie reală.

## Compatibilitate SDK și contract

- `packages/server/package.json` din checkout-ul local declară `@modelcontextprotocol/sdk: ^1.12.0`.
- `pnpm-lock.yaml` rezolvă pachetul la **1.29.0**, integrity `sha512-zo37mZA9hJWpULgkRpowewez1y6ML5GsXJPY8FI0tBBCd77HEvza4jDqRKOXgHNn867PVGCyTdzqpz0izu5ZjQ==`. Aceasta confirmă versiunea lockfile-ului local, nu versiunea imaginii Understory active.
- Pachetul nu este instalat în `understory/node_modules`; sursele/distribuția SDK nu au fost găsite în checkout. Suportul concret pentru `structuredContent`, forma rezultatului `tools/call`, serializarea alături de `content` și accesul handlerului la JSON-RPC ID sunt **NECONFIRMATE**. Nu s-au instalat pachete și nu s-a accesat rețeaua.
- În `packages/server/src/mcp/server.ts`, handlers-urile locale `memory_add`, `memory_update` și `memory_maintain` întorc explicit numai `content` text-only. Argumentele existente nu includ `request_id`, iar codul handlerelor inspectat nu propagă JSON-RPC ID. V1 cere `structuredContent.request_id` egal cu ID-ul JSON-RPC și păstrează argumentele neschimbate. Sursa locală nu demonstrează cum se poate satisface această cerință; accesul eventual prin contextul SDK/middleware rămâne necunoscut.
- Clienții care consumă numai `content` ar putea rămâne compatibili dacă textul este păstrat, însă această ipoteză nu a fost verificată cu SDK-ul sau clienții reali. Documentul V1 rămâne PROPUS.

## Traseul simulat și rezultate

Harness-ul nou nu importă și nu execută adaptorul sau workerul de producție. Transportul fake oferă fixtures sau ridică timeout/disconnect; validatorul și clasificatorul sunt cele existente; tabelul SQLite minimal există numai în `tmp_path`.

Au fost acoperite toate trei operațiile (`memory_add`, `memory_update`, `memory_maintain`), outcome-urile valide `applied`, `partial`, `unknown`, `rejected_before_write` și `memory_maintain no_op`, plus no-op invalid la add/update. Au fost simulate răspuns legacy text-only, ID mismatch, JSON invalid/răspuns invalid, timeout și disconnect.

În fiecare caz acceptat sau eșuat, primul job este `unknown/unknown`, al doilea rămâne `queued`, FIFO este blocat și transportul fake este apelat exact o dată. Nu există retry automat. Niciun rezultat nu este promovat la `succeeded/complete` sau `failed/none`.

Testele demonstrează numai comportamentul fixtures, validatorului și politicii harness-ului. Nu demonstrează interoperabilitate cu MCP SDK/Understory, durabilitate, atomicitate, idempotency, autentificare sau efecte runtime.

## Verificări

- Suita completă: **239 passed** cu Python 3.12.3 în `/tmp/rendiv-stage1-venv`.
- `pip check`: PASS — `No broken requirements found`.
- `git diff --check`: PASS.

## Limite și următorii gate-uri

1. Inspectarea sursei exacte a SDK 1.29.0 pentru tipurile/implementarea rezultatului MCP și contextul handlerului.
2. Demonstrarea unei căi de corelare JSON-RPC ID → `request_id` fără modificarea implicită a schemei argumentelor; dacă nu există, contractul și compatibilitatea trebuie revizuite explicit.
3. Confirmarea că SDK-ul serializează simultan `structuredContent` și textul `content` și că clienții text-only continuă să funcționeze.
4. Proveniența runtime Understory este în continuare neconfirmată; nu s-a verificat containerul ori serviciul activ.

Nu începe checkpointul 6B.2I și nu porni integrarea reală.
