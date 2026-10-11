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

La orice cerere de raport, analiză, audit, investigație sau sinteză pentru proiectul Rendiv:

- Salvează automat rezultatul într-un fișier Markdown potrivit din `docs/`.
- Actualizează `docs/DEVELOPMENT.md` cu rezultatul și starea verificărilor.
- Rulează `git diff --check`. Dacă verificările trec, fă automat commit și push către `origin/main`, incluzând numai documentația aferentă cererii.
- Nu cere aprobare separată pentru salvarea sau publicarea acestei documentații.
- Nu include secrete, credențiale, date sensibile, modificări preexistente sau modificări fără legătură.
- Dacă push-ul eșuează, nu folosi force push; raportează eșecul.
- Păstrează inspecțiile sistemelor și serviciilor investigate strict read-only și nu modifica alte repository-uri.
