# Checkpoint 6B.2I — MCP SDK 1.29.0: verificare de tipuri și probă locală

Data: 2026-10-12
Statut: confirmare experimentală cu SDK-ul npm exact 1.29.0; fără servicii reale și fără integrare Rendiv.

## Mediu și izolare

- Repository: curat înainte de modificări, `main` la `18c22bdb4f7a1586fa71d06fd70587b1c6727114`, în sincron cu `origin/main`.
- Node: `v22.23.3`; npm: `10.9.9`.
- SDK instalat într-un director dedicat `/tmp/rendiv-cp6b2i-sdk129`, cu `npm install --save-exact --ignore-scripts --no-audit --no-fund @modelcontextprotocol/sdk@1.29.0`.
- `npm ls --prefix /tmp/rendiv-cp6b2i-sdk129 @modelcontextprotocol/sdk --depth=0` a raportat `@modelcontextprotocol/sdk@1.29.0`; manifestul instalat raportează tot `1.29.0`. npm a instalat pachetul și dependențele sale numai în directorul temporar.
- Probe server/client au folosit `McpServer`, `Client` și `InMemoryTransport.createLinkedPair()` din același proces Node. Tool-urile au fost fake și nu au accesat date externe. Nu s-au pornit servere de rețea, procese Understory, MCP extern sau LLM.

## API public și dovezi din SDK

Sursele de mai jos sunt fișierele distribuției publicate în pachetul exact 1.29.0, instalat temporar:

| API/constatare | Referință în distribuția 1.29.0 | Rezultat |
|---|---|---|
| Înregistrarea callbackului | `dist/esm/server/mcp.d.ts:150-157`, `McpServer.registerTool(..., cb: ToolCallback<InputArgs>)` | Callbackul este API-ul public high-level |
| Semnătura callbackului și contextul | `dist/esm/server/mcp.d.ts:250-258`, `ToolCallback` include `args, extra: RequestHandlerExtra<...>` | Handlerul primește contextul `extra` |
| ID-ul cererii în context | `dist/esm/shared/protocol.d.ts:173-195`, câmp documentat `requestId: RequestId`, descris ca JSON-RPC ID al cererii curente | **Accesibil handlerului prin API public tipizat/documentat** |
| Schema resultului tool | `dist/esm/types.d.ts:2501-2603` și `dist/esm/types.js:1289-1304` | `content` și `structuredContent` sunt câmpuri distincte; `structuredContent` este opțional și este `Record<string, unknown>` |
| Transport in-memory | `dist/esm/inMemory.js`, `InMemoryTransport.createLinkedPair()` | Transport local în același proces |
| Client high-level | `dist/esm/client/index.js`, `Client.callTool()` | Returnează `CallToolResult`; ID-ul JSON-RPC exterior nu este inclus în obiectul returnat |

Tipurile sunt API-ul exportat al pachetului, nu detalii private. Implementarea probei a confirmat comportamentul acelei versiuni; aceasta nu confirmă că imaginea Understory activă conține aceeași versiune. Runtime-ul Understory rămâne nelegat de versiunea lockfile-ului prin provenance verificată.

## Rezultatele probei

Serverul de test a înregistrat `memory_add`, `memory_update` și `memory_maintain`. Fiecare handler a primit `extra.requestId`, l-a pus în fixture-ul `structuredContent.request_id` și a întors simultan `content` text și `structuredContent`. Clientul a apelat fiecare tool prin `Client.callTool()`.

| Verificare | Rezultat experimental |
|---|---|
| JSON-RPC ID văzut de handler | Egal cu ID-ul requestului `tools/call` observat la transport pentru fiecare din cele trei operații |
| ID outer în răspunsul JSON-RPC | Același ID cu requestul, conform instrumentării transportului local; protocolul clientului îl folosește pentru corelare |
| `request_id` din structuredContent | Handlerul l-a setat din `extra.requestId`; valoarea a egalat ID-ul outer în toate cele trei probe |
| Rezultatul `Client.callTool()` | A conținut `content` și `structuredContent`; nu a conținut proprietatea `id` |
| Client text-only | Consumarea numai a `result.content[].text` a reușit și a ignorat `structuredContent` |
| Formă MCP invalidă | `structuredContent` care nu este obiect a fost respins de validarea schema SDK/protocol |
| Semantică V1 invalidă | Obiect cu `request_id` diferit a fost acceptat de schema generică SDK și livrat clientului; SDK nu validează regulile V1 fără o schemă de output aplicată |

`request_id` rămâne numai corelare de protocol. Nu este `operation_id`, cheie de idempotency, receipt durabil sau garanție de efect. Tool-urile fake au folosit un `operation_id` sintetic, fără persistență și fără semantică upstream.

## Evaluare contract V1 și recomandare

Cererea V1 de a echo `request_id` ca JSON-RPC ID poate fi implementată la server fără argument MCP nou: handlerul poate utiliza `extra.requestId`, câmp public din `RequestHandlerExtra`. Prin urmare **nu este necesară o corecție de schemă V1 pentru obținerea ID-ului în handler**. Checkout-ul Understory curent însă nu folosește acel câmp și încă întoarce numai `content`; va trebui modificat într-o etapă de integrare aprobată pentru a adăuga `structuredContent` și echo-ul. Acest checkpoint nu modifică sursa Understory sau contractul 06.

Clientul high-level primește numai resultul MCP, fără JSON-RPC ID exterior. Protocolul SDK potrivește răspunsul la requestul outstanding înainte de rezolvarea `callTool`, dar aplicația nu poate compara independent `structuredContent.request_id` cu ID-ul exterior doar din valoarea returnată. Dacă implementarea cere comparație explicită, corelația poate fi observată printr-un wrapper peste interfața publică `Transport.send` și comparată cu `request_id`; wrapperul trebuie să păstreze comportamentul și timeouturile transportului. Alternativ, aplicația poate documenta că se bazează pe corelarea protocolară a clientului SDK și validează separat echo-ul V1. Alegerea modului de verificare independentă rămâne **decizie de integrare**, nu schimbare aprobată a contractului.

SDK-ul validează forma generică de `CallToolResult`, nu semantica Rendiv V1. Validatorul V1 trebuie păstrat: versiunile, identitățile, outcome/evidence, combinațiile și paths nevalide trebuie să eșueze fail-closed. Exemplul semantic-invalid arată de ce simpla acceptare MCP nu echivalează cu acceptarea V1.

Deciziile de certitudine nu se schimbă: `applied`, `partial`, `unknown`, timeout/disconnect și orice rezultat insuficient rămân `unknown/unknown`; `memory_maintain no_op` și `rejected_before_write` rămân de asemenea `unknown/unknown` fără aprobările/dovezile stabilite. Niciun rezultat nu justifică retry automat sau deblocarea FIFO.

## Limite

- Proba folosește SDK-ul 1.29.0 instalat din registry și transport in-memory, nu transportul, buildul sau versiunea de SDK din Understory activ.
- Nu validează proveniența imaginii, outputSchema Understory, autentificare, tool schemas reale, timpi de execuție, efecte parțiale, durabilitate, atomicitate, idempotency sau comportament la crash.
- Răspunsul text-only al sursei Understory locale și lipsa integrării V1 rămân neschimbate.
- Clientul text-only din probă demonstrează doar că poate citi `content` din resultul SDK; nu acoperă orice client MCP terț.
- Scriptul de probă și instalarea npm sunt temporare și se elimină după verificări; nu sunt dependințe sau artefacte ale repository-ului.

## Verificare de proiect

Rezultatul probei Node, testele Rendiv, `pip check`, `git diff --check`, cleanup-ul directorului `/tmp` și publicarea sunt consemnate în `docs/LATEST-REPORT.md`.
