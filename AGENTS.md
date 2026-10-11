# Reguli pentru Codex în Rendiv

Aceste reguli se aplică întregului proiect și au prioritate pentru orice activitate Codex în acest spațiu.

## Domeniu și siguranța datelor

- Lucrează numai în `Rendiv-project`, cu excepția inspecțiilor strict read-only autorizate explicit pentru proiectele Pithagoras și Understory.
- Pithagoras (`~/ai-stack/pithagoras`), Understory (`~/ai-stack/understory`), Agentbox, Docker, Home Assistant și memoria existentă sunt sisteme externe. Nu le modifica și nu rula comenzi care le schimbă starea.
- Nu citi, copia, afișa sau include în documentație secrete, tokenuri, parole, chei API, fișiere `.env` ori configurații care le pot conține. Dacă o valoare secretă apare accidental, nu o reproduce.
- Nu executa apeluri MCP care modifică date. Nu invoca `memory_add`, `memory_update`, `memory_maintain` sau operații echivalente.
- Nu implementa bufferul/coada de procesare a memoriei până când utilizatorul nu cere explicit implementarea.
- Nu face deployment. Pentru rapoarte și analize Rendiv, aplică regula de salvare și publicare automată de mai jos; pentru celelalte sarcini documentare, nu face commit sau push decât dacă utilizatorul cere explicit.

## Rigoare tehnică

- Separă explicit comportamentul verificat în cod/documentație de cerințe, ipoteze și aspecte neconfirmate.
- Nu deduce că o coadă persistentă există doar pentru că Pithagoras are mecanisme generale de joburi în fundal.
- Tratează drept cerință de proiectare, nu funcționalitate implementată, prioritatea inferenței conversaționale Pithagoras față de procesarea AI Understory pe serverul llama.cpp comun. Prioritatea între loturile din buffer rămâne nedecisă. Nu întrerupe brutal operațiile Understory deja începute pentru a aplica prioritatea conversațională.
- Tratează timeoutul MCP implicit de 60 s și posibilitatea ca Understory să lucreze câteva minute ca date de context furnizate de utilizator; confirmă implementarea și configurația concretă înainte de a le documenta ca proprietăți ale runtime-ului.
- Home Assistant trimite loturi logice. Understory decide organizarea semantică; nu impune o taxonomie paralelă în Rendiv.
- La modificări documentare, păstrează starea de progres și deciziile consecvente între `docs/ARCHITECTURE.md` și `docs/DEVELOPMENT.md`.

## Verificare și raportare

- Nu rula teste, servicii, comenzi MCP sau operații de deployment decât dacă utilizatorul cere verificarea respectivă.
- La final, raportează concis fișierele create/modificate și verificările efectuate. Oprește-te când sarcina cerută este îndeplinită.

## Rapoarte și analize Rendiv

### REGULĂ PERMANENTĂ — RAPOARTE CODEX

La orice cerere de raport, analiză, audit sau investigație pentru Rendiv:

1. Salvează rezultatul în `docs/LATEST-REPORT.md`, suprascriind integral raportul precedent.
2. Păstrează în raport data, subiectul, constatările, dovezile, problemele și recomandările. Distinge faptele verificate de contextul furnizat, ipoteze și recomandări.
3. Rulează automat `git diff --check`; dacă trece, fă commit și push pe `origin/main` numai pentru `docs/LATEST-REPORT.md`.
4. Nu cere aprobare suplimentară pentru salvarea și publicarea raportului.
5. Nu actualiza `docs/DEVELOPMENT.md` la fiecare raport; actualizează-l numai când există progres real de dezvoltare.
6. Nu publica secrete, credențiale sau informații sensibile.
7. Respectă restricțiile read-only asupra sistemelor și serviciilor investigate.
8. Nu include modificări preexistente ori fără legătură, nu modifica alte repository-uri și nu folosi force push. Dacă push-ul eșuează, raportează eșecul.
