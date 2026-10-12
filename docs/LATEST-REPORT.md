# Raport Rendiv — Checkpoint 6B.2I: verificare reală MCP SDK 1.29.0

Data: 2026-10-12

## Domeniu și fișiere

S-a instalat și probat `@modelcontextprotocol/sdk@1.29.0` într-un director temporar dedicat. S-a folosit un server și client MCP de test cu transport in-memory și trei tool-uri complet fictive. Nu s-au conectat servicii active și nu s-au modificat codul de producție, Understory, Pithagoras, infrastructura, API-ul, baza Rendiv sau schema.

Fișierele repository-ului modificate pentru checkpoint:

- `docs/design/08-MCP-SDK-129-RUNTIME-TEST.md` — referințe SDK, rezultate experimentale, evaluarea V1 și recomandare.
- `docs/DEVELOPMENT.md` — progresul checkpointului.
- `docs/LATEST-REPORT.md` — raportul curent.

## Mediu și verificare SDK

- Preflight: repository curat la `18c22bdb4f7a1586fa71d06fd70587b1c6727114`; Node `v22.23.3`; npm `10.9.9`.
- Instalare: `/tmp/rendiv-cp6b2i-sdk129`, comandă `npm install --save-exact --ignore-scripts --no-audit --no-fund @modelcontextprotocol/sdk@1.29.0`. `npm ls` și `package.json` instalat au confirmat exact `1.29.0`. Pachetul și dependențele au fost instalate numai acolo.
- Tipurile publice din distribuție arată `McpServer.registerTool` cu `ToolCallback`; semnătura callbackului include `RequestHandlerExtra`, al cărui `requestId: RequestId` este documentat drept JSON-RPC ID al cererii curente.
- `CallToolResultSchema` permite `structuredContent?: Record<string, unknown>` împreună cu `content`; implementarea și proba in-memory confirmă că ambele ajung la client.

## Probe experimentale

Cu `McpServer`, `Client` și `InMemoryTransport.createLinkedPair()` în același proces local:

- Handlers fake pentru `memory_add`, `memory_update` și `memory_maintain` au primit `extra.requestId`; valoarea a coincis cu ID-ul JSON-RPC request/response observat la transport și a fost inclusă în `structuredContent.request_id`.
- `Client.callTool()` a returnat `content` plus `structuredContent`, dar nu câmpul exterior `id`.
- Citirea numai a `content[].text` a funcționat, simulând un client care ignoră `structuredContent`.
- Un `structuredContent` care nu era obiect a fost respins de schema SDK/protocol.
- Un obiect de forma generică MCP, dar cu `request_id` V1 diferit de ID-ul handlerului, a fost acceptat de SDK. SDK-ul nu verifică semantica Rendiv V1 fără validarea specifică a aplicației.
- Nu s-au folosit porturi, rețea către servicii, MCP real, LLM ori date/memorie reale.

## Decizie contractuală

Handlerul poate obține JSON-RPC ID prin API public, deci V1 nu necesită câmp nou de argument doar pentru a popula `request_id`. Codul Understory local nu folosește încă `extra.requestId` și produce în prezent numai `content`; nu a fost modificat.

Clientul high-level nu returnează ID-ul outer în `CallToolResult`. Protocolul SDK corelează răspunsul înainte să rezolve `callTool`, dar o comparație independentă cu echo-ul `structuredContent.request_id` ar necesita un wrapper peste interfața publică `Transport.send` care observă ID-ul requestului. Alegerea acestui control pentru integrarea viitoare rămâne deschisă; V1 nu a fost schimbat.

SDK-ul acceptă doar forma generică MCP, nu regulile semantice V1. Validatorul Rendiv rămâne necesar. Outcome-urile `applied`, `partial`, `unknown`, timeout/disconnect și rezultatele ambigue rămân `unknown/unknown`; `no_op` și `rejected_before_write` rămân de asemenea `unknown/unknown`. Nu apare retry automat sau deblocare FIFO.

## Verificări și curățare

- Suita completă: **239 passed** cu Python 3.12.3 în `/tmp/rendiv-stage1-venv`.
- `pip check`: PASS — `No broken requirements found`.
- `git diff --check`: PASS.
- Proba MCP SDK 1.29.0: PASS pentru verificările enumerate.
- Instalarea și scriptul temporar au fost eliminate exclusiv din `/tmp/rendiv-cp6b2i-sdk129` după verificări.

## Limite rămase

Proba confirmă SDK npm 1.29.0, nu versiunea sau configurația din imaginea Understory activă. Nu demonstrează efecte Understory, idempotency, atomicitate, durability, autentificare, timeouturi runtime sau compatibilitatea tuturor clienților terți. Contractul V1 rămâne propus, iar integrarea reală neîncepută.

Nu începe checkpointul următor și nu conecta Rendiv la Understory.
