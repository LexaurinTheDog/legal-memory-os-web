# Legal Memory OS: prezentační stránka

Statická stránka s videem, která popisuje skill Legal Memory OS: společnou paměť a pracovní zápisy AI agentů (Claude Code, Codex, Cursor, GitHub Copilot, Copilot CLI) v trezoru Obsidian. Zdrojový kód skillu je v samostatném soukromém repozitáři.

Stránka nenačítá nic z jiných serverů, nemá cookies ani měření návštěvnosti. Písmo Recursive je uložené ve složce `fonts/` (SIL Open Font License 1.1, text licence v `fonts/OFL.txt`).

## Obsah

- `index.html`, `styles.css`: stránka.
- `media/`: video (`legal-memory-os.mp4`), české titulky (`legal-memory-os.vtt`) a náhledový obrázek.
- `video/capture.py`: spustí skript `lmo` v dočasném trezoru se smyšleným klientem a uloží příkazy, těla a výstupy do `video/demo.json`.
- `video/build.py`, `video/frame.css`: z `demo.json` vykreslí snímky, namluví text a složí video s titulky.

## Jak video vzniklo

Vše běží lokálně:

- snímky vykreslí Chromium přes Playwright;
- hlas je syntéza řeči macOS (`say`, hlas Zuzana);
- video složí ffmpeg bez metadat (kodér, čas vytvoření).

Všechny výstupy ve videu i na stránce jsou skutečné výstupy `lmo` 1.1.0 nad smyšlenými daty (klient Ukázka s.r.o., spis 999/2099, rodné číslo s neexistujícím datem 31. 2. 2030).

```sh
python3 -I video/capture.py <cesta k lmo.py> video/demo.json   # potřebuje kopii skillu
python3 video/build.py                                         # potřebuje ffmpeg, Playwright a Pillow
```
