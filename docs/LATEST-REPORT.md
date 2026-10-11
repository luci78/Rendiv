# Raport Rendiv — Checkpoint 6B.2D: audit read-only al contractului Understory

Data: 2026-10-11

## Subiect și domeniu

Audit static al contractului local Understory pentru `memory_add`, `memory_update` și `memory_maintain`, cu accent pe dovezile efectelor și pe limitele clasificării Rendiv. Raportul detaliat, cu referințe exacte la fișiere și funcții, este `docs/design/05-UNDERSTORY-CONTRACT-AUDIT.md`.

Sursa locală inspectată: `/home/luci78/ai-stack/understory`, commit `f6c342332f390a444a8669636b1cf8f9669dd995`, curată la verificarea read-only. Acest commit nu confirmă codul sau configurația serviciului activ.

## Constatări confirmate în sursa locală

- `memory_add` acceptă `content` și opțional `suggested_path`; `memory_update` acceptă `instruction`; `memory_maintain` primește obiect gol. Primele două trec prin agentul intern și tool-uri de scriere KB.
- `ok` și `Files changed` constituie succes raportat. Paths înregistrate nu sunt manifest complet și nu dovedesc commit durabil. Scrierea conceptului poate preceda eșecul regenerării indexului sau logului, iar callback-ul poate raporta listă goală în acea situație.
- Pentru codul local, `memory_maintain` are markerul exact healthy no-op `Memory is healthy — N concepts, N links, no orphans, no broken links. Nothing to repair.` Ramura face lint read-only și revine fără `runMutation`. Markerul este dovadă la nivelul acelei versiuni de cod numai când răspunsul complet este valid și corelat. Adaptorul Rendiv actual nu îl recunoaște, deci persistă `unknown`.
- `failed`, `isError` sau paths goale nu demonstrează absența efectului; `FAILED_NO_EFFECT` nu poate fi justificat fără dovadă structurată și verificabilă.
- În traseul inspectat nu există operation ID/status durabil, idempotency upstream, revision per mutație, tranzacție multi-fișier sau receipt de commit. Read-back-ul poate observa conținut curent, dar nu dovedește operația care l-a produs ori durabilitatea.
- Codul nu configurează timeout explicit pentru mutație și nu propagă anularea la `runMutation`. Fallback-ul de model poate repeta generarea în unele condiții, dar nu oferă idempotency mutației. Timeoutul, retry-urile SDK/provider și comportamentul runtime rămân neconfirmate.

## Metodă și limitări

Au fost citite sursele locale Understory și codul/documentația Rendiv relevantă. Nu s-au executat teste, build, servicii, Docker, HTTP, MCP sau stdio. Nu s-au apelat API-uri read-only deoarece identitatea buildului, autentificarea, bundle-ul activ și riscul de expunere a memoriei nu puteau fi demonstrate. Nu s-au accesat baze de date, secrete sau conținutul memoriei și nu s-a modificat repository-ul Understory.

## Recomandare

Păstrați `unknown` și blocarea cozii pentru timeout, disconnect, răspuns invalid/ambiguu, eșec fără proof și succes raportat fără receipt suficient. Primul pas recomandat pentru contractul viitor este un rezultat structurat/versionat cu outcome explicit și operation ID, inclusiv `no_op` numai pentru calea confirmată de maintain. Pentru replay și reconciliere după timeout sunt necesare separat journal durabil, idempotency și status lookup. Read-back-ul singur nu justifică retry sau durabilitate.

Decizii necesare înainte de integrarea reală: ce format/versionare va avea outcome-ul; cum se vor lega operation ID, journal și idempotency de efectele filesystem; ce receipt poate susține succes terminal; și cum se verifică versiunea și configurarea serviciului activ fără a expune datele memoriei.

## Fișiere Rendiv

- `docs/design/05-UNDERSTORY-CONTRACT-AUDIT.md` — matricea pe operații, dovezi, clasificări, necunoscute și opțiuni de contract.
- `docs/DEVELOPMENT.md` — checkpointul și progresul actualizat.
- `docs/ARCHITECTURE.md` — statusul adaptorului și al markerului no-op aliniat cu DEVELOPMENT.
- `docs/LATEST-REPORT.md` — acest raport.

## Verificări

- Documentație: linkurile locale din cele patru fișiere Rendiv modificate au fost verificate; toate țintele există (PASS).
- `git diff --check`: PASS.
- Teste: nu au fost rulate; sarcina este audit/documentație read-only și AGENTS.md nu autorizează rularea lor implicită.

Nu a început integrarea reală.
