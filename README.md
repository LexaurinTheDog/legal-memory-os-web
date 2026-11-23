# Legal Memory OS: prezentační stránka

Statická stránka s videem, která popisuje skill Legal Memory OS: společnou paměť a pracovní zápisy AI agentů (Claude Code, Codex, Cursor, GitHub Copilot, Copilot CLI, OpenCode) v trezoru Obsidian a od verze 2 elektronický spis s rejstříkem osob, oddělením osobních údajů od cloudového agenta a schvalováním úkonů člověkem. Zdrojový kód skillu je v samostatném soukromém repozitáři.

Stránka nenačítá nic z jiných serverů, nemá cookies ani měření návštěvnosti. Písmo Recursive je uložené ve složce `fonts/` (SIL Open Font License 1.1, text licence v `fonts/OFL.txt`).

## Obsah

- `index.html`, `styles.css`: stránka.
- `media/`: video (`legal-memory-os.mp4`), české titulky (`legal-memory-os.vtt`) a náhledový obrázek.
- `video/capture.py`: spustí skripty skillu v dočasném trezoru se smyšleným klientem a smyšleným soudem a uloží příkazy, těla a výstupy do `video/demo.json`. Cloudového agenta představuje běh bez přístupu ke složce osobních údajů, lokální stranu běh s přístupem; dialogy v terminálu běží přes pseudoterminál.
- `video/overeni.json`: výsledky testů, auditu a fuzzování z repozitáře skillu, které video ukazuje.
- `video/build.py`, `video/frame.css`: z `demo.json` vykreslí snímky, namluví text a složí video s titulky. Do `index.html` doplní přepis videa, ukázku poznámky, výpis spisu, verzi a délku videa (mezi značky `<!--…-->`).

## Jak video vzniklo

Vše běží lokálně:

- snímky vykreslí Chromium přes Playwright;
- hlas je syntéza řeči macOS (`say`, hlas Zuzana);
- video složí ffmpeg bez metadat (kodér, čas vytvoření).

Všechny výstupy ve videu i na stránce jsou skutečné výstupy skriptů skillu nad smyšlenými daty: klient Ukázka s.r.o., Okresní soud ve Vzorově, spisy z roku 2099, rodná čísla s neexistujícím datem (31. 2. 2030, 30. 2. 1975), IČO s neplatným kontrolním součtem a PSČ, které v Česku neexistují. Verzi skriptu uvádí `demo.json`.

```sh
python3 -I video/capture.py ~/.agents/skills/legal-memory-os/scripts video/demo.json   # instalovaný skill, Ollama s qwen3:1.7b
python3 video/build.py                                         # potřebuje ffmpeg, Playwright a Pillow
```
