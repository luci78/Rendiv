# Raport Rendiv — Checkpoint 6B.2E: identitate runtime Understory și contract MCP V1

Data: 2026-10-11

## Subiect și metodă

Am verificat metadate Docker read-only pentru identitatea runtime Understory și am redactat o propunere de contract MCP structurat/versionat V1. Raportul de proiectare detaliat este `docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md`.

S-au folosit numai `docker ps`, `docker inspect` formatat și `docker image inspect` formatat, fără câmpuri environment. Nu s-au folosit exec, logs, Compose, build, pull, healthcheck sau endpointuri; nu s-au accesat volumele, secretele ori memoria și nu s-au efectuat operații de schimbare a stării.

## Dovezi runtime confirmate

Containerul observat este `ai-understory`, ID `2cb642db5307f38fb0f43fc41c3298f3b75f6f81fc0c537848ba2a1439bbd6e6`, creat la `2026-10-09T20:41:24Z`. Image reference este `ai-stack-understory`; image ID și repo digest local sunt `sha256:ad0699e1644f7ec75393c3335696be677b05a1c845e917e3a610a3a07f20ba7c`. Imaginea este linux/amd64, creată la `2026-10-09T17:10:41Z`.

Containerul pornește cu entrypoint `docker-entrypoint.sh` și argumentele `node server/dist/index.js`; restart policy este `unless-stopped`. Metadatele indică bind mount read-write către `/bundle`, rețeaua `ai-stack_default` și `3800/tcp` publicat pe host `0.0.0.0:3800`. Raportul de proiectare conține sursa mount-ului host; conținutul nu a fost citit.

Image labels nu conțin OCI source/revision/version. Labelul containerului `com.docker.compose.image` indică un alt digest (`sha256:07615849ff7bade28438d3f3f22b47f301870deea76770735715a14982b04266`) față de image ID-ul inspectat. Această neconcordanță nu a fost investigată prin config Compose și nu poate servi ca proveniență. Tagul și timestampurile nu identifică commitul.

Checkout-ul local Understory este curat la commit `f6c342332f390a444a8669636b1cf8f9669dd995`, dar nu există legătură verificabilă între checkout și digest. **Versiunea Understory runtime rămâne NECONFIRMATĂ.**

## Contract MCP V1 propus

`docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md` definește un envelope `structuredContent` cu `contract_version`, `request_id`, `operation_id`, `operation`, `outcome`, `no_op`, `changed_paths` și evidence strict tipizată. Contractul păstrează argumentele existente ale tool-urilor și textul MCP pentru clienții vechi.

Outcome-urile sunt `applied`, `no_op`, `partial`, `rejected_before_write` și `unknown`. Răspunsurile legacy text-only, invalide, necorelate sau contradictorii rămân `unknown` în Rendiv și blochează FIFO. `changed_paths` singur nu este suficient. `applied` ar însemna raport explicit terminal al handlerului, fără afirmație de atomicitate ori durabilitate. Propunerea de a-l mapa la `succeeded/complete` necesită aprobarea semanticii acestei stări înainte de implementare.

Envelope-ul poate clarifica raportarea și corelarea unui exchange și poate exprima no-op explicit. Nu furnizează deduplicare, status după restart, dovadă no-effect după începerea scrierii, journal exhaustiv, atomicitate multi-fișier sau durability. Acestea cer mecanisme upstream separate: journal durabil, idempotency/status și o strategie verificabilă de commit/staging.

## Verificări și limite

- Linkurile locale din documentele Markdown modificate: PASS.
- Cele cinci exemple JSON din propunerea V1: parse PASS.
- `git diff --check`: PASS.
- Nu s-au executat teste; livrabilul este documentație/proiectare și audit read-only.
- Nu s-a inspectat environment, configuration file extern, build context, filesystem-ul imaginii sau conținutul volumului. Nu s-a verificat MCP/API/LLM runtime.
- Contractul este propus, neimplementat. Implementarea necesită confirmarea provenance a imaginii, aprobarea outcome-urilor și compatibilității `structuredContent` cu clienții MCP existenți.

## Fișiere Rendiv

- `docs/design/06-UNDERSTORY-MCP-CONTRACT-V1.md` — dovezile runtime și propunerea contractuală.
- `docs/DEVELOPMENT.md` — progres 6B.2E consemnat.
- `docs/ARCHITECTURE.md` — starea identității runtime și a proiectării V1 aliniată cu progresul.
- `docs/LATEST-REPORT.md` — acest raport.

Nu au fost modificate containere, imagini, rețele, volume, servicii sau cod. Nu începe checkpointul următor.
