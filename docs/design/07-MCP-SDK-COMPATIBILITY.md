# Checkpoint 6B.2H — Compatibilitate MCP SDK și simulare offline

Data verificării: 2026-10-12
Statut: analiză statică și teste locale fake; fără integrare Understory.

## Rezumat

Lockfile-ul checkout-ului local Understory rezolvă `@modelcontextprotocol/sdk` la **1.29.0** (integrity `sha512-zo37mZA9hJWpULgkRpowewez1y6ML5GsXJPY8FI0tBBCd77HEvza4jDqRKOXgHNn867PVGCyTdzqpz0izu5ZjQ==`). `packages/server/package.json` declară intervalul `^1.12.0`. Asta confirmă versiunea rezolvată de lockfile, nu versiunea inclusă în containerul activ; proveniența imaginii rămâne neconfirmată conform documentului 06.

Codul SDK nu este instalat în `understory/node_modules`, iar în checkout nu au fost găsite sursele sau distribuția pachetului. Prin urmare sunt **NECONFIRMATE** forma tipizată reală a rezultatului `tools/call`, suportul/serializarea `structuredContent` în versiunea 1.29.0 și API-ul prin care handlerul serverului ar putea accesa JSON-RPC ID-ul. Nu s-au instalat dependențe și nu s-a folosit rețeaua.

Codul local al aplicației Understory nu emite explicit rezultatul V1: `packages/server/src/mcp/server.ts`, `buildMcpServer`, înregistrează `memory_add`, `memory_update` și `memory_maintain` cu handlers ce întorc obiecte `content` text-only. Argumentele lor nu includ `request_id`, iar callback-urile vizibile nu îl propagă. Așadar sursa locală, așa cum este scrisă și inspectată, nu demonstrează cum ar putea produce `structuredContent.request_id` egal cu JSON-RPC `id`. Aplicarea SDK-ului ar putea adăuga acces la contextul cererii, dar fără sursa SDK aceasta este NECONFIRMATĂ.

## Dovezi inspectate

| Constatare | Dovadă locală | Statut |
|---|---|---|
| Interval declarat de server | `understory/packages/server/package.json`, dependency `@modelcontextprotocol/sdk: ^1.12.0` | Confirmat în checkout |
| Versiune selectată | `understory/pnpm-lock.yaml`, import key `@modelcontextprotocol/sdk@1.29.0`, package key `@modelcontextprotocol/sdk@1.29.0(zod@3.25.76)` | Confirmat de lockfile, nu de runtime |
| Codul pachetului disponibil | `understory/node_modules/@modelcontextprotocol/sdk` absent; nicio cale SDK în fișierele locale inventariate | Confirmat pentru checkout-ul inspectat |
| Tool results explicite | `understory/packages/server/src/mcp/server.ts`, handlers pentru cele trei operații construiesc `content` cu text și nu construiesc `structuredContent` | Confirmat în sursa locală |
| Argumentele existente | același fișier: add primește `content`/`suggested_path`, update `instruction`, maintain `{}` | Confirmat în sursa locală |
| Corelarea JSON-RPC ID | Nu apare în argumentele tool-urilor și nu este propagată explicit în handler-ele inspectate | Confirmată absența propagării explicite în acest fișier; accesul SDK la context rămâne necunoscut |
| Răspunsul MCP wire exact | Ar depinde de SDK-ul rezolvat și de transport | Neconfirmat fără SDK instalat/sursă |
| Compatibilitate client text-only | Contractul propune păstrarea `content`; nu a fost verificată compatibilitatea SDK sau clientului real | Propunere, neconfirmată |

Nu s-au inspectat containere, endpointuri, secrets, bundle-uri sau baze de date în acest checkpoint.

## Corelare și compatibilitate

Contractul 06 cere ca `request_id` din `structuredContent` să fie echo exact al JSON-RPC `id`, dar lasă argumentele MCP existente neschimbate. Fixture-ul contractului include atât ID-ul exterior cât și valoarea din `structuredContent`; asta validează formatul fixture-ului, nu demonstrează că serverul Understory poate obține ID-ul exterior.

Până la inspectarea SDK 1.29.0, nu se poate afirma dacă handler-ul `McpServer.registerTool` primește request ID într-un argument de context, dacă serverul poate să-l citească prin middleware, sau dacă poate asocia ID-ul cu rezultatul când transportul este stateless. Nu modificați contractul și nu adăugați un câmp în input schema implicit. Înainte de integrare este necesară o probă statică a API-ului SDK (tip și implementare pentru handler/context și serializer) și o decizie de compatibilitate asupra modului de transport al corelației.

V1 cere `structuredContent` alături de `content` text pentru clienți vechi. Nu s-a verificat dacă SDK 1.29.0 acceptă această combinație ori cum serializează un tool result care conține ambele câmpuri. Clienții ce citesc numai text pot fi compatibili dacă textul păstrat continuă să existe, dar aceasta rămâne o așteptare de protocol, nu o observație runtime.

## Harness simulat

`tests/test_mcp_contract_fifo_simulation.py` exercită calea:

1. transport fake în memorie returnează un JSON-RPC fixture sau ridică timeout/disconnect;
2. `validate_mcp_response` validează envelope-ul și structuredContent V1;
3. `classify_for_rendiv` sau `unknown_disposition` produce politica fail-closed;
4. un tabel SQLite minimal, creat numai sub `tmp_path`, persistă jobul 1 ca `unknown/unknown`, lasă jobul 2 `queued` și nu face alt apel.

Harness-ul nu instanțiază adaptorul sau workerul de producție și nu constituie test de interoperabilitate SDK. Outcome-urile V1 valide (`applied`, `partial`, `unknown`, `rejected_before_write` și `memory_maintain no_op`) rămân `unknown/unknown`; invalid no-op pentru add/update, text-only legacy, ID mismatch, JSON invalid, timeout și disconnect sunt fail-closed. Fiecare caz confirmă un singur apel fake și FIFO blocat.

Această simulare nu demonstrează Understory runtime, wire serialization SDK, durabilitate, atomicitate, idempotency, autentificare sau persistența efectelor.

## Decizii și condiții înainte de integrare

1. **SDK:** obțineți/inspectați sursa exactă a SDK-ului 1.29.0 din lockfile ori artefactul verificat, fără a deduce că este în imaginea activă.
2. **Corelare:** demonstrați dacă handlerul poate accesa JSON-RPC ID fără a schimba arguments; dacă nu, revizuiți explicit contractul și compatibilitatea input schema înainte de implementare.
3. **Rezultat structurat:** confirmați tipul `CallToolResult`/schema MCP și serializarea concomitentă `structuredContent` + `content` în versiunea fixată.
4. **Clienți legacy:** validați că un consumator `content`-only ignoră câmpul nou și continuă să primească textul așteptat.
5. **Runtime:** legați versiunea verificată de imaginea activă prin provenance înaintea oricărei probe de compatibilitate runtime.

Până atunci V1 rămâne PROPUSĂ, iar transportul real și workerul rămân neconectate.
