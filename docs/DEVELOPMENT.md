# Dezvoltare și progres

## Etape

| Etapă | Rezultat urmărit | Stare |
|---|---|---|
| 1. Documentarea sistemului | Reguli Codex, arhitectură cunoscută/neconfirmată și plan de lucru | Încheiată prin această inițializare |
| 2. Confirmarea contractelor | Verificarea API-urilor MCP, timeouturilor efective, statusului operațiilor și posibilităților de deduplicare | Neîncepută |
| 3. Proiectarea cozii | Schema persistentă, priorități, serializare, recovery, verificarea după timeout și politica anti-duplicate | Neîncepută |
| 4. Implementarea bufferului Rendiv | Acceptare asincronă, procesare serială și integrare cu sistemele sursă/destinație | Neîncepută; nu este autorizată în această etapă |
| 5. Verificare și operare | Validarea comportamentului, monitorizare, retry și proceduri de recuperare | Neîncepută |

Etapele 2–5 nu au fost executate. Această sarcină a creat doar documentație.

## Decizii și cerințe consemnate

- Procesarea memoriei trebuie scoasă din calea conversației interactive.
- Coada trebuie să fie persistentă și să trimită serial către Understory.
- Inferența conversațională Pithagoras are prioritate față de procesarea AI Understory pe serverul llama.cpp comun.
- Prioritatea relativă între loturile din coadă este o decizie separată și rămâne nedecisă.
- O expirare MCP la 60 s, în timp ce Understory poate lucra câteva minute, cere verificarea stării înainte de orice retry.
- Deduplicarea trebuie să prevină repetarea efectelor după timeout, întrerupere sau restart.
- Home Assistant trimite loturi logice; Understory face organizarea semantică.
- Verificarea runtime Understory raportată de utilizator prin `docker inspect`: `LLM_MODEL=Qwen3.6-35B-A3B-Q5_K_M` și `LLM_API_BASE_URL=http://192.168.20.30:8080/v1`.
- Pithagoras folosește aceeași configurație conform contextului anterior, dar nu a fost reverificat în această etapă.
- Detectarea activității llama.cpp nu este confirmată ca implementată și trebuie investigată ca parte a proiectării priorității inferenței.
- Nicio componentă externă și nicio memorie existentă nu se modifică în etapa de documentare.

## Jurnalul acestei inițializări

- Rendiv-project era gol, cu excepția metadatelor Git.
- Au fost inspectate read-only fragmente relevante din codul Pithagoras și README/codul Understory, fără citirea configurațiilor de secrete.
- Codul Pithagoras confirmă integrarea MCP Understory existentă și rutarea modelului pentru unele cereri Understory; nu confirmă coada Rendiv cerută.
- Nu au fost rulate teste, apeluri MCP, servicii sau comenzi de deployment. Nu s-au modificat proiectele externe și nu s-a făcut commit.

## Corectare documentară ulterioară

- Separată prioritatea inferenței conversaționale Pithagoras față de Understory de ordinea loturilor din coadă, care rămâne nedecisă.
- Înregistrată verificarea runtime Understory prin `docker inspect`, precum și faptul că runtime-ul Pithagoras nu a fost reverificat în această etapă.
- Marcată investigarea detectării activității llama.cpp drept lucru deschis; nu se afirmă că este deja implementată.
