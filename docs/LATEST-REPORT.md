# Raport: analiza Pithagoras–Understory

- **Data:** 2026-10-11 (data analizei documentate)
- **Subiect:** Integrarea Pithagoras–Understory și coordonarea procesării memoriei prin Rendiv
- **Bază:** analiza read-only din `docs/PITHAGORAS-UNDERSTORY-ANALYSIS.md`, arhitectura din `docs/ARCHITECTURE.md` și contextul runtime furnizat anterior de utilizator

## Constatări

### Confirmate în codul analizat

- Pithagoras integrează Understory prin MCP cu `directTools: true`. Instrucțiunile de prompt descriu utilizarea memoriei, dar nu impun serializarea tehnică a apelurilor.
- Coada `exclusive` din `server/src/extensions/understory-service.ts` deservește anumite operații pornite de portal. Apelurile MCP directe ale agentului nu trec prin acea coadă.
- Programarea `dream` folosește un timer în proces. Analiza nu a identificat o coadă persistentă pentru operațiile MCP `add`/`update`.
- `agent_start` și `agent_settled` descriu un tur Pithagoras mai larg, nu o măsurare confirmată a tuturor inferențelor către serverul llama.cpp comun. Urmărirea apelurilor Understory din `memory-llm.ts` determină conversația asociată unei cereri Understory; nu este un contor global al inferențelor Pithagoras.
- Pithagoras are SQLite persistent și un model de supervisor pentru routines, dar acestea sunt precedente tehnice, nu dovada unei cozi Rendiv implementate.
- Understory oferă operații MCP de citire și mutație care pot rula un agent intern. Analiza nu a confirmat status consultabil ori idempotency pentru mutațiile respective.

### Context furnizat de utilizator

- Understory a fost verificat anterior prin `docker inspect` pentru modelul Qwen3.6-35B-A3B-Q5_K_M și un endpoint llama.cpp comun. Adresa exactă este omisă din acest raport ca detaliu de infrastructură.
- Pithagoras a fost raportat ca folosind aceeași configurație, dar runtime-ul său nu a fost reverificat în analiza documentată.
- Timeoutul MCP de 60 s este context furnizat, nu măsurătoare confirmată a runtime-ului. Operațiile Understory pot dura câteva minute.

## Dovezi

Analiza read-only citează următoarele fișiere din Pithagoras:

- `server/src/features.ts`, `server/src/api/mcp.ts` și `server/src/pi/sdk-client.ts` pentru configurarea MCP și încărcarea adaptorului.
- `server/src/extensions/understory-service.ts` pentru coada în memorie a anumitor acțiuni de portal și programarea operațiilor de mentenanță.
- `server/src/session-manager.ts` și `server/src/memory-llm.ts` pentru evenimentele de tur și asocierea cererilor Understory cu conversația.
- `server/src/db.ts` și `server/src/routines/supervisor.ts` pentru SQLite și patternul de persistență/supraveghere al routines.

Sinteza și delimitarea constatărilor sunt documentate în `docs/PITHAGORAS-UNDERSTORY-ANALYSIS.md`; cerințele și aspectele deschise sunt consemnate în `docs/ARCHITECTURE.md`. Acest raport nu reprezintă o nouă inspecție a runtime-urilor.

## Probleme și riscuri deschise

- Timeoutul sau întreruperea transportului poate lăsa neclar dacă o mutație Understory a fost aplicată. Nu este confirmată o cale de status sau de deduplicare la destinație.
- Activitatea inferenței către modelul comun nu este măsurată global în codul analizat. Detectarea ei și acoperirea subagenților, routines și a altor clienți trebuie investigate.
- Dacă o inferență Pithagoras începe după ce Understory a pornit deja, simpla verificare înainte de pornirea jobului nu elimină cursa. Operațiile Understory începute nu trebuie întrerupte brutal.
- Configurația MCP efectivă, timeoutul runtime și toate căile de scriere către Understory rămân de confirmat. Configurația Pithagoras nu a fost reverificată.
- Coada persistentă Rendiv, recuperarea după restart și comportamentul anti-duplicate nu sunt implementate sau confirmate.

## Recomandări din analiză

- Proiectați Rendiv ca poartă de enqueue pentru scrieri, cu joburi persistente, ID stabil, răspuns asincron și status consultabil. Nu tratați aceste funcții ca existente.
- Folosiți un singur worker serial pentru scrieri și mentenanță. Înainte de retry după timeout sau restart, reconciliați starea; păstrați un rezultat incert fără retry automat dacă efectul nu poate fi stabilit.
- Investigați o măsură fiabilă a inferențelor conversaționale Pithagoras și modul de amânare a noilor joburi Understory. Prioritatea inferenței Pithagoras nu implică o prioritate decisă între loturile bufferului.
- Inventariați toate căile MCP de scriere înainte de a considera Rendiv singura poartă. Păstrați loturile Home Assistant ca unități logice și lăsați organizarea semantică în seama Understory.
- Confirmați timeoutul runtime, statusul/idempotency la destinație și configurația efectivă înainte de implementarea cozii.

## Verificări și stare

- Analiza de bază a fost read-only; nu au fost accesate servicii active și nu au fost executate operații de memorie.
- Nu s-au rulat teste runtime în acea analiză. Contractele, configurațiile runtime și proiectarea detaliată rămân de verificat.
- Nu s-a implementat coada Rendiv și nu s-au modificat Pithagoras, Understory sau memoria existentă.
