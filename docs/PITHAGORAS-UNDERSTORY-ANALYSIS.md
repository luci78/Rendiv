# Analiză read-only: integrarea Pithagoras–Understory

Data documentării: 2026-10-11. Această notă consemnează analiza read-only deja efectuată și propune o arhitectură pentru Rendiv. Nu descrie o coadă implementată. Nu au fost accesate servicii active sau executate operații de memorie în această etapă.

## CONFIRMAT în codul Pithagoras

- `server/src/features.ts` definește intrarea MCP Understory cu `lifecycle: "lazy"` și `directTools: true`; nu adaugă `requestTimeoutMs`. `server/src/api/mcp.ts` fixează `pi-mcp-adapter@2.18.0`, iar `server/src/pi/sdk-client.ts` încarcă adaptorul prin resource loader. `UNDERSTORY_RULE` intră în promptul sesiunilor principale când integrarea este activă. Skillurile sunt încărcate separat prin `additionalSkillPaths`; un skill sau o regulă de prompt nu pot impune serializare tehnică.
- `server/src/extensions/understory-service.ts` are o coadă `exclusive` numai în memoria procesului pentru operațiile pornite de portal (de exemplu editare/reindexare/reparare). Apelurile MCP directe ale agentului nu trec prin această coadă. Timeouturile de aici nu reprezintă timeoutul MCP direct; operațiile cu model au limită de 30 de minute, iar alte scripturi 60 de secunde.
- Programarea `dream` folosește `scheduleDreams()` și un timer în proces, apoi apelează `dreamNow()`. Nu este o coadă persistentă de joburi. Codul salvează rezultatul ultimei sesiuni de dreaming, nu un registru durabil de operații MCP `add/update`.
- `server/src/session-manager.ts` vede `agent_start` și `agent_settled`, care marchează un tur mai larg decât o inferență. Fluxul primește și evenimente de mesaj assistant și de execuție a uneltelor, dar nu există un contor global verificat al inferențelor către un endpoint/model comun. `server/src/memory-llm.ts` urmărește apelurile tool Understory pentru a determina conversația al cărei model este folosit; nu reprezintă contorul tuturor inferențelor Pithagoras.
- `server/src/db.ts` oferă SQLite persistent și migrații. `server/src/routines/supervisor.ts` arată un pattern existent pentru scheduler, stări persistate și marcarea run-urilor întrerupte; aceste mecanisme nu înseamnă că există deja o coadă de memorie.

Documentația upstream a adaptorului fixat descrie `requestTimeoutMs` global sau per server și aprobări pentru tool-uri: [README pi-mcp-adapter v2.18.0](https://github.com/nicobailon/pi-mcp-adapter/blob/v2.18.0/README.md#server-options). Posibilitatea de configurare nu confirmă valoarea runtime efectivă.

## CONFIRMAT din contextul furnizat, nu reverificat aici

Utilizatorul a confirmat anterior că agenții Pithagoras folosesc același endpoint llama.cpp `http://192.168.20.30:8080/v1` și modelul `Qwen3.6-35B-A3B-Q5_K_M`. Documentația Rendiv existentă consemnează verificarea runtime Understory prin `docker inspect` cu aceleași valori. Configurația efectivă a runtime-ului Pithagoras nu a fost reverificată; endpointul și modelul nu sunt prezentate aici ca citire directă din configurația sa.

## NECONFIRMAT / verificări runtime rămase

- `mcp.json` și versiunea adaptorului instalate efectiv în runtime-ul Pithagoras; în analiza anterioară Docker nu a fost accesibil, iar fișierul local găsit aparținea Agentbox. Nu s-au expus secrete.
- Timeoutul MCP efectiv, eventuale suprascrieri, comportamentul transportului la timeout și dacă anularea cererii oprește operația deja începută în Understory. Valoarea de 60 s este context/documentație a SDK-ului, nu o măsurătoare a runtime-ului.
- Existența unei chei idempotente sau a unui status consultabil pentru operațiile de scriere Understory. Fără acestea, o eroare de transport poate lăsa rezultatul ambiguu.
- Dacă evenimentele de mesaj Pi sunt suficient de timpurii și complete pentru a detecta toate inferențele către modelul comun, inclusiv subagenți/routines, și ce alți clienți folosesc llama.cpp sau MCP Understory.
- Dacă Pithagoras poate începe o inferență după ce o operație Understory a început. Fără coordonare la admiterea cererilor în backend, detectarea unei ferestre libere înainte de job nu elimină această cursă.

## RECOMANDARE pentru Rendiv

Păstrați coada și workerul în serviciul Rendiv deja prevăzut de arhitectură, folosind stocarea persistentă existentă a Rendiv; nu adăugați un serviciu separat numai pentru coadă. Un apel de scriere de la Pithagoras sau Home Assistant trebuie să persiste imediat un job cu ID stabil și să răspundă cu identificatorul/starea `queued`, astfel conversația nu așteaptă procesarea semantică. Un singur worker procesează serial toate scrierile, inclusiv mentenanța nocturnă, și oferă status/citire pentru verificare.

Rendiv trebuie să fie poarta tehnică: dezactivați/filtrați tool-urile directe Understory de scriere în integrarea Pithagoras și rutați-le prin interfața Rendiv de enqueue. Ascunderea tool-urilor directe nu este suficientă dacă proxy-ul MCP sau un alt client poate încă invoca mutațiile. Inventariați și controlați fiecare cale de acces la Understory înainte de a afirma că nu există bypass.

Workerul poate amâna pornirea unui job cât timp există inferențe conversaționale Pithagoras raportate active. Nu folosiți simpla stare `agent_start`–`agent_settled` drept sinonim pentru inferență; validați evenimentele de mesaj assistant și filtrarea după model. Aceasta este o regulă de prioritizare de proiectat, nu funcționalitate existentă. Un job Understory deja pornit nu trebuie întrerupt brutal. Fără backend cu prioritizare/preempție sau alt model separat, există o cursă dacă Pithagoras începe ulterior o inferență: prioritate absolută pentru Pithagoras și absența oricărei întârzieri pentru conversație nu pot fi garantate numai de un scheduler Rendiv.

Modelul de stări recomandat este `queued → running → succeeded/failed`, cu `unknown` pentru timeout sau restart în timpul execuției. Nu retrimiteți automat un job `unknown`. Faceți read-back/reconciliere; dacă nu se poate demonstra dacă efectul a fost aplicat, păstrați-l pentru decizie explicită. O cheie stabilă ajută la deduplicarea enqueue-urilor, dar nu oferă exactly-once în Understory fără suport idempotent la destinație. Loturile Home Assistant rămân unități logice; Understory răspunde de organizarea semantică. Ordinea/prioritatea relativă între loturi rămâne o decizie separată.

## Etape și teste propuse înainte de implementare

1. Confirmați configul runtime MCP fără a afișa tokenuri, timeoutul efectiv și toate căile Pithagoras/Home Assistant către Understory.
2. Verificați contractul de status/idempotency și efectul timeoutului pe o instanță de test izolată înaintea oricărui retry.
3. Proiectați apoi tabela/coada Rendiv, lease/claim unic, recuperarea `running → unknown`, statusul pentru caller și integrarea de activitate llama.cpp.
4. Testați concurența a doi enqueue simultani, serializarea, restart între claim și răspuns, timeout după efect aplicat fără retry/duplicat, reconcilierea, lipsa blocării conversației la enqueue, job nocturn unic și refuzul apelurilor MCP directe de scriere.

Nu s-au rulat teste și nu s-au efectuat verificări runtime prin servicii în etapa de documentare. Etapele de confirmare a contractelor, proiectare detaliată, implementare și operare rămân deschise.
