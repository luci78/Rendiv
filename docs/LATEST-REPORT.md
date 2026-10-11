# Raport Rendiv — Etapa 6B.2B: transport MCP simulat

Data: 2026-10-11

## Subiect și domeniu

A fost adăugat protocolul MCP JSON-RPC în adaptorul Rendiv, cu schimb de mesaje exclusiv prin transport injectat și fake in-memory pentru teste. Nu există client HTTP/stdio și nu a fost contactat Understory.

## Modificări

- src/rendiv_api/understory_adapter.py: validarea argumentelor documentate, serializarea tools/call, transportul abstract injectabil, decodarea rezultatului MCP și clasificarea conservatoare în ExecutionResult pentru worker.
- tests/test_understory_adapter.py: peer MCP in-memory, scenarii de protocol, rezultate și integrare cu workerul.
- docs/DEVELOPMENT.md: progresul Etapei 6B.2B.
- docs/LATEST-REPORT.md: prezentul raport.

Nu s-au schimbat API-ul Rendiv, schema SQLite, migrațiile, workerul, Dockerfile sau Compose.

## Contract și comportament

Validarea urmează docs/design/03-UNDERSTORY-CONTRACT.md:

- memory_add acceptă content string obligatoriu și suggested_path string opțional.
- memory_update acceptă instruction string obligatoriu.
- memory_maintain acceptă doar obiect gol.
- Câmpuri nedeclarate și valori neconforme sunt respinse înainte de transport.

Adaptorul serializează un JSON-RPC tools/call cu numele tool-ului și arguments, apoi validează versiunea envelope-ului, id-ul corelat și rezultatul MCP text. Singurul transport testat este fake in-memory.

Clasificări:
- Confirmat succes → numai un răspuns fără isError, fără marker de mutație parțială și cu cel puțin o cale listată în Files changed; se mapează la succeeded/complete. Aceasta este dovada limitată descrisă de contract: metodele de scriere au raportat completare și căi schimbate.
- Failed/isError fără dovadă no-effect → unknown.
- Marker partial, text fără căi, Files changed: none, răspuns ambiguu sau răspuns malformed → unknown. Healthy no-op la memory_maintain este unknown deoarece modelul workerului nu are stare no-op cu effect certainty none.
- Timeout înainte sau după efectul fake → rezultatul executorului timeout, pe care workerul 6A îl persistă unknown.
- Disconnect/eroare de transport → unknown.
- Nu există în contract o dovadă generală no-effect; adaptorul nu emite FAILED_NO_EFFECT. Nu există retry sau reconciliere automată.

Workerul 6A nu a fost modificat. Testele de integrare confirmă FIFO existent, audit atomic al tranzițiilor, blocarea cozii la unknown și lipsa reexecuției după repornire.

## Verificări

- Suita completă: 100 teste PASS.
- pip check: PASS, fără cerințe defecte.
- git diff --check: PASS.
- Testul adaptorului blochează crearea socketului; peer-ul fake doar parsează și produce șiruri JSON în memorie.
- Testele folosesc SQLite temporar. Nu s-au rulat Docker/Compose, servicii, MCP/HTTP/stdio către Understory sau operații externe.

## Limitări înainte de integrarea reală

Contractul local nu oferă receipt durabil, job status, idempotency, confirmare generală de no-effect sau reconciliere. Files changed confirmă numai căile raportate de metode, nu că intenția semantică a fost satisfăcută integral. Rezultatele failed, partial, timeout, disconnect și crash rămân unknown și blochează coada. Potrivirea dintre checkout-ul local Understory și runtime, auth activă, timeouturi și comportamentul de anulare rămân neconfirmate. Integrarea reală necesită aceste garanții și aprobare separată; nu a început în această etapă.
