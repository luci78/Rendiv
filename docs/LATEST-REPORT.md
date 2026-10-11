# Raport Rendiv — Etapa 6B.2A: investigare read-only Understory

Data: 2026-10-11

## Scop și metodă

Sarcina a fost identificarea contractului real în sursele locale Understory, fără mutații sau conectare la servicii.

Pre-flight: repository-ul Rendiv este /home/luci78/Rendiv-project, iar git status era curat înaintea modificărilor. Checkout-ul local Understory a fost găsit în /home/luci78/ai-stack/understory, la commit f6c342332f390a444a8669636b1cf8f9669dd995; statusul său read-only era curat. Au fost inspectate static fișierele server MCP, auth, wiring Express, agent, tool-uri interne, KnowledgeBase, Bundle, indexer, logger, trace, dreamer și package.json. Nu s-au rulat teste sau cod Understory, Docker, servicii, MCP ori HTTP. Nu s-au citit fișiere .env sau valori credentiale.

Contractul și proveniența simbol-cu-simbol sunt documentate în docs/design/03-UNDERSTORY-CONTRACT.md.

## Confirmat în codul local

- În packages/server/src/mcp/server.ts, buildMcpServer definește memory_add cu content obligatoriu string și suggested_path opțional string; memory_update cu instruction obligatoriu string; memory_maintain cu argumente goale. Schema directă nu impune lungimi minime/maxime pentru șirurile de text.
- memory_add și memory_update creează instrucțiuni pentru runMutation; acesta folosește agentul LLM și tool-urile interne definite în packages/core/src/agent/tools.ts. memory_maintain întoarce no-op dacă lint-ul indică graf sănătos, altfel execută agentul de reparație.
- Tool-urile interne pot scrie, patch-ui sau șterge concepte Markdown. KnowledgeBase serializează mutațiile numai în coada in-process a instanței sale. Bundle scrie fișiere, iar afterMutation poate prune directoare, reface indexurile, adăuga în log și face Git autocommit best-effort.
- Transportul implementat în checkout include MCP Streamable HTTP stateless la /mcp și MCP stdio. Aplicația Express setează body limit de 4 MB și bind la 0.0.0.0. Acestea sunt proprietăți ale codului local, nu confirmări ale topologiei runtime.
- Bearer auth HTTP pentru /mcp și /api este condițional de AUTH_TOKEN. Nu s-a verificat dacă variabila este definită. Stdio nu folosește middleware-ul HTTP.
- Outcome-ul agentului poate fi success, partial sau failed. Partial expune text cu fișierele raportate ca scrise, dar nu este atomic și nu are rollback. Failed fără cale în filesChanged nu dovedește universal lipsa efectului: lista este actualizată după rezolvarea completă a operației KnowledgeBase, care poate scrie fișierul principal înainte de index/log.
- Nu au fost găsite cheie de idempotency, job ID/status durabil sau operație de reconciliere. Trace-urile JSON sunt best-effort și nu sunt transaction log.
- În sursele locale există alte căi mutative: POST /api/chat, dreamer periodic dacă DREAM_INTERVAL este configurat, CLI mutate și orice acces de scriere directă la bundle. Activarea lor runtime nu a fost verificată.

## Necunoscute

- Dacă commitul local corespunde serviciului/imaginii active, transportul folosit de client, ruta și identitatea de rețea.
- Dacă bearer auth este activă, ce bundle este montat și ce permisiuni are. Nicio valoare secretă nu a fost citită.
- Timeouturile efective ale clientului MCP, serverului/proxy-ului și providerului LLM; dacă deconectarea anulează agentul sau scrierile deja începute.
- Versiunile efectiv instalate ale SDK-urilor și dacă dreamer este activ.
- Nu există suficiente date din cod pentru a demonstra no-effect după o eroare, timeout sau crash. Aceste rezultate trebuie tratate ca unknown.

## Riscuri și condiții pentru integrare

Răspunsul MCP cu isError ori statusul local failed nu este, singur, dovadă sigură că nu s-a scris nimic. Partial poate include doar căile pe care callback-ul a apucat să le înregistreze. Persistența este compusă din operații de filesystem separate, iar serializarea locală nu coordonează procese diferite.

Înainte de executorul Rendiv sunt necesare: confirmarea versiunii deployate și a configurației non-secrete relevante; contract request/response versionat cu receipt și rezultat mașinabil; idempotency și status lookup; probă verificabilă de no-effect; comportament explicit pentru partial/crash; timeouturi și anulare măsurate; inventarierea și coordonarea MCP direct, /api/chat, dreamer, CLI și accesului filesystem. Orice credential trebuie doar verificat ca prezență/absență, fără citirea sau publicarea valorii.

Nu s-a implementat executor real. Etapa 6B.2B nu a început.

## Verificare și publicare

- git diff --check: PASS.
- Teste: neexecutate, conform scopului strict read-only și interdicției de a atinge servicii active.
- Fișiere Rendiv modificate: docs/design/03-UNDERSTORY-CONTRACT.md, docs/DEVELOPMENT.md, docs/LATEST-REPORT.md.
- Nicio sursă Understory sau altă infrastructură nu a fost modificată.
