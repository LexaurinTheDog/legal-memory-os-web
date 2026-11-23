"""Sestaví video, titulky a přepis z naměřených výstupů lmo (video/demo.json).

Vše běží lokálně: snímky vykreslí Chromium (Playwright), hlas je syntéza macOS (`say`, hlas Zuzana),
video složí ffmpeg. Metadata (kodér, čas vytvoření) se do souboru nezapisují.

Použití: python3 video/build.py   (výstup: media/legal-memory-os.mp4, .vtt, poster.jpg, přepis v index.html)
"""

import hashlib
import html
import json
import re
import shutil
import string
import subprocess
import textwrap
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
MEDIA = ROOT / "media"
DEMO = json.loads((ROOT / "video" / "demo.json").read_text(encoding="utf-8"))
STEP = {s["name"]: s for s in DEMO["steps"]}
ESTEP = {s["name"]: s for s in DEMO["espis"]}
VERZE = DEMO["verze"]
OVERENI = json.loads((ROOT / "video" / "overeni.json").read_text(encoding="utf-8"))
LEAD, TAIL = 0.35, 0.75
VOICE, RATE = "Zuzana", 172

# Výslovnost cizích názvů pro český hlas; titulky zůstávají ve správném pravopisu.
SAY = [
    ("Legal Memory OS", "Lígl memory ou es"), ("Claude Code", "Klód kód"), ("GitHub Copilot", "Gitchab Kopajlot"),
    ("Copilot CLI", "Kopajlot cé el í"), ("Copilot", "Kopajlot"), ("Codex", "Kodex"), ("Cursor", "Kurzor"),
    ("OpenCode", "Oupn kód"), ("Claude", "Klód"), ("Obsidian", "Obsidián"), ("Pamet", "Paměť"), ("lmo", "elemó"),
    ("AI", "ej áj"), ("skill", "skil"), ("Pythonu", "Pajtnu"), ("e-mailu", "ímejlu"), ("ESpis", "éspis"), ("Cloudový", "Klaudový"), ("cloudového", "klaudového"), ("cloudový", "klaudový"),
    ("Ollamu", "Olamu"), ("YOLO", "jólo"), ("SharePoint", "Šérpojnt"), ("Dropbox", "Dropbox"),
]

AGENTS = "Claude Code, Codex, Cursor, GitHub Copilot, Copilot CLI, OpenCode a aplikace Claude"
WHO = {"cloud": ("cloud", "Cloudový agent (Claude Code), bez přístupu ke složce osobních údajů"),
       "lokalni": ("local", "Lokální strana: člověk s přístupem ke složce osobních údajů")}


def speech(text):
    for a, b in SAY:
        text = re.sub(r"(?<!\w)" + re.escape(a) + r"(?!\w)", b, text)
    return text


def esc(s):
    return html.escape(s, quote=False)


def delimiter(name):
    abc = [c for c in string.ascii_letters + string.digits if c not in "ilIoO01"]
    h = hashlib.sha256(name.encode()).digest()
    return "LMO_" + "".join(abc[b % len(abc)] for b in h[:8])


def shell_words(args):
    out, i = [], 0
    q = lambda v: v if re.fullmatch(r"[A-Za-z0-9._/~-]+", v) else ("''" if v == "" else '"' + v + '"')
    while i < len(args):
        a = args[i]
        if a.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
            out.append(a + " " + q(args[i + 1]))
            i += 2
        else:
            out.append(q(a))
            i += 1
    return out


def command(step, width=66):
    prog = {"lmo.py": "lmo", "sed": "sed"}.get(step.get("prog", "lmo.py"), step.get("prog"))
    words = [prog] + shell_words(step["args"])
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur + " \\")
            cur = "    " + w
        else:
            cur = (cur + " " + w) if cur else w
    if step["body"]:
        cur += " <<'" + delimiter(step["name"]) + "'"
    lines.append(cur)
    return lines


OK_START = ("založeno", "založen", "zapsáno", "zapsána", "lmo check", "schváleno", "rezervována", "oddělení zapnuto")


def out_class(line):
    if line.startswith("<<<"):
        return "env"
    if line.startswith("[blok"):
        return "dim"
    if line.startswith(OK_START) or (line.startswith("lmo overit") and " 0 problémů" in line):
        return "ok"
    if line.startswith(("NARUŠENO", "POZOR")):
        return "err"
    return "o"


def term_step(s, show_output=True):
    parts = []
    for i, line in enumerate(command(s)):
        parts.append('<span class="p">' + ("$ " if i == 0 else "  ") + '</span><span class="c">' + esc(line) + "</span>")
    if s.get("tty"):
        lines = s["stdout"].rstrip("\n").split("\n")
        for line in lines:
            m = re.match(r"^(> )(.*)$", line) or re.match(r"^(.*?(?:kód \d{4}|\[n\]e): )(.*)$", line)
            if m:
                parts.append('<span class="p">' + esc(m.group(1)) + '</span><span class="c">' + esc(m.group(2)) + "</span>")
            else:
                parts.append('<span class="' + out_class(line.strip()) + '">' + esc(line) + "</span>")
        return "\n".join(parts)
    if s["body"]:
        rows = []
        for line in s["body"].rstrip("\n").split("\n"):
            rows.append('<span class="b">' + esc(line).replace(chr(0x200B), '<span class="zw"></span>') + "</span>")
            if chr(0x200B) in line:
                # Popisek mimo text terminálu: ukazuje sloupec neviditelného znaku.
                rows.append(" " * line.index(chr(0x200B)) + '<span class="ann">^ neviditelný znak U+200B</span>')
        parts.append("\n".join(rows))
        parts.append('<span class="b">' + delimiter(s["name"]) + "</span>")
    if show_output:
        for line in s["stdout"].rstrip("\n").split("\n") if s["stdout"].strip() else []:
            parts.append('<span class="' + out_class(line) + '">' + esc(line) + "</span>")
        for line in s["stderr"].rstrip("\n").split("\n") if s["stderr"].strip() else []:
            parts.append('<span class="err">' + esc(line) + "</span>")
    return "\n".join(parts)


def mem(name, show_output=True):
    return term_step(STEP[name], show_output)


def es(name, show_output=True):
    return term_step(ESTEP[name], show_output)


def note():
    if DEMO_PART[0] == "espis":
        return ('<div class="note">Ukázka se smyšleným Okresním soudem ve Vzorově a smyšlenými osobami, '
                "skutečné výstupy lmo " + VERZE + "</div>")
    return '<div class="note">Ukázka se smyšleným klientem Ukázka s.r.o., skutečné výstupy lmo ' + VERZE + "</div>"


DEMO_PART = ["pamet"]


def term(*blocks, stamp=False, comment=None, small=False, who=None, tiny=False):
    body = ('<span class="dim"># ' + esc(comment) + "</span>\n" if comment else "")
    body += '\n<span class="gap"></span>'.join(blocks)
    st = '<div class="stamp"><b>ODMÍTNUTO</b><span>nic se nezapsalo</span></div>' if stamp else ""
    badge = ""
    if who:
        cls, text = WHO[who] if who in WHO else who
        badge = '<div class="who ' + cls + '">' + esc(text) + "</div>"
    size = " tiny" if tiny else (" small" if small else "")
    return badge + '<div class="term' + size + '">' + body + "</div>" + st + note()


def raw_term(lines):
    out = []
    for kind, text in lines:
        if kind == "cmd":
            out.append('<span class="p">$ </span><span class="c">' + esc(text) + "</span>")
        else:
            out.append('<span class="' + kind + '">' + esc(text) + "</span>")
    return '<div class="term">' + "\n".join(out) + "</div>"


def sheet(path):
    text = DEMO["notes"][path].rstrip("\n")
    lines = text.split("\n")
    end = lines.index("---", 1)
    keys = ", ".join(l.split(":")[0] for l in lines[1:end] if l and not l.startswith(" "))
    out, code = ['<span class="skip">[vlastnosti poznámky vynechány: ' + esc(keys) + ']</span>'], False
    lines = lines[end + 1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    for line in lines:
        e = esc(line)
        if line.startswith("```"):
            code = not code
            out.append('<span class="fm">' + e + "</span>")
        elif code:
            out.append('<span class="code">' + e + "</span>")
        elif line.startswith("## "):
            out.append('<span class="h2">' + e + "</span>")
        elif line.startswith("# "):
            out.append('<span class="h1">' + e + "</span>")
        elif line.startswith("### "):
            out.append('<span class="h3">' + e + "</span>")
        elif line.startswith("> "):
            out.append('<span class="ext">' + e + "</span>")
        else:
            out.append(e)
    return '<div class="sheet"><span class="path">' + esc(path) + "</span>" + "\n".join(out) + "</div>" + note()


def card(h2, items=(), out=()):
    lis = "".join('<li class="out">' + i + "</li>" for i in out) + "".join("<li>" + i + "</li>" for i in items)
    return '<div class="card"><h2>' + h2 + "</h2>" + ("<ul>" + lis + "</ul>" if lis else "") + "</div>"


TITLE = ('<div class="title"><h1>Legal Memory OS</h1><p>Paměť AI agentů a elektronický spis v trezoru Obsidian</p>'
         '<p class="agents">' + AGENTS + "</p></div>")

TWO_PARTS = ('<div class="parts">'
             '<div class="box lmo" style="grid-row: 1 / 3">' '<h3>lmo</h3><p>jediný zapisující skript, běží lokálně</p></div>'
             '<div class="wire"></div><div class="box vault"><h3>Pamet/</h3><p>paměť a pracovní zápisy agentů</p></div>'
             '<div class="wire" style="grid-column: 2"></div>'
             '<div class="box vault"><h3>ESpis/</h3><p>spisy, rejstřík osob, dokumenty, lhůty, schvalování</p></div>'
             "</div>")

FLOW_LMO = ('<div class="flow"><div class="agents-col"><div class="agent">AI agent</div></div><div class="wire"></div>'
            '<div class="box lmo"><h3>lmo</h3><p>skryté znaky, hesla, rodná čísla, aktivní obsah, přesný klient</p></div>'
            '<div class="wire"></div><div class="box vault"><h3>Pamet/</h3><p>zápis se jen připojí</p></div></div>')

SEPARATION = ('<div class="sep"><div class="side">'
              '<div class="actor">Cloudový agent<p>Claude Code, Codex, Cursor, Copilot, aplikace Claude</p></div>'
              '<div class="down"></div>'
              '<div class="store">Trezor<p>identifikátory osob, začerněné texty, doručovací údaje</p></div></div>'
              '<div class="wall"><span>úložiště nepustí</span></div>'
              '<div class="side">'
              '<div class="actor local">Lokální strana<p>člověk, místní model, vytěžení dokumentů</p></div>'
              '<div class="down"></div>'
              '<div class="store pii">Složka osobních údajů<p>rejstřík osob, originály dokumentů, klíč schválení</p>'
              "</div></div></div>")

VERIFY = raw_term([
    ("cmd", "python3 -B -m unittest discover -s tests"),
    ("o", OVERENI["testy"]), ("ok", "OK"), ("gap", ""),
    ("cmd", "python3 -B tools/audit.py --history"),
    ("ok", OVERENI["audit"]), ("gap", ""),
    ("cmd", "python3 verify/fuzz_render.py 2000 7"),
    ("ok", OVERENI["fuzz"]), ("gap", ""),
    ("dim", "# testy i pod Pythonem 3.9 a v sandboxu macOS se zakázanou sítí"),
    ("dim", "# nezávislá revize AI agenty: 14 nálezů, automatická bezpečnostní revize: 3, opraveno"),
])

PAMET = [
    ("Legal Memory OS je skill pro AI agenty. Verze 2 přidává k paměti advokátní kanceláře elektronický spis, "
     "navržený tak, aby ho mohly používat i soudy, státní zastupitelství a další orgány veřejné moci.", [(TITLE, 1)]),
    ("Skill má dvě části: paměť agentů ve složce Pamet a elektronický spis ve složce ESpis. "
     "Do obou zapisuje jen skript lmo, který běží lokálně a sám nic nikam neposílá.", [(TWO_PARTS, 1)]),
    ("Claude Code, Codex, Cursor, Copilot i OpenCode zapisují do jedné paměti. "
     "Skript každý zápis zkontroluje dřív, než ho uloží.",
     [(FLOW_LMO, 0.4), (term(mem("stav-pamet"), mem("pripad"), comment="lmo = python3 -I " + DEMO["lmo"]), 0.6)]),
    ("Na začátku práce agent načte, co o věci víme. Výstup ohraničují značky s náhodným kódem "
     "a poznámky klienta skript vydá jen se zadaným klientem.",
     [(term(mem("najit"), small=True), 0.6), (term(mem("najit-bez-klienta")), 0.4)]),
    ("Skryté znaky, hesla a rodná čísla skript odmítne a nic nezapíše. "
     "Agent dostane přesné místo chyby.",
     [(term(mem("skryty-znak"), stamp=True), 0.5), (term(mem("heslo"), mem("rodne-cislo"), stamp=True), 0.5)]),
    ("Text z e-mailu nebo z webu skript uloží doslovně jako cizí citaci. "
     "Obsidian z něj nic nevykreslí a agent dostane upozornění, že jde o data, ne o pokyny.",
     [(term(mem("externi")), 0.4), (sheet("Pamet/zapis_ukazka-s-r-o_email-protistrany.md"), 0.6)]),
    ("Zápisy se jen připojují jako datované bloky s označením agenta. "
     "Na konci práce agent zapíše deník a zkontroluje celou složku.",
     [(sheet("Pamet/pripad_ukazka-s-r-o_najem-skladu.md"), 0.6), (term(mem("denik"), mem("kontrola")), 0.4)]),
]

DEMO_PART[0] = "espis"
ESPIS = [
    ("Teď elektronický spis. Zakládá se jedním příkazem, v ukázce pro smyšlený Okresní soud ve Vzorově. "
     "Hned se zapne i oddělení osobních údajů.",
     [(term(es("init"), es("oddelit"), who="lokalni"), 0.45), (term(es("stav"), who="cloud"), 0.55)]),
    ("Osobní údaje leží ve zvláštní složce mimo trezor. Cloudový agent běží pod účtem, který do ní nemá přístup. "
     "Nevynucuje to jen skript, ale úložiště: disk, Dropbox, SharePoint nebo server.", [(SEPARATION, 1)]),
    ("Cloudový agent spis založí. Údaje fyzické osoby ale zapsat nesmí. "
     "Osobu jen rezervuje a dostane bezvýznamový identifikátor.",
     [(term(es("spis-zalozit"), es("osoba-fo-odmitnuto"), who="cloud", stamp=True), 0.55),
      (term(es("spis-zalozit"), es("osoba-fo-odmitnuto"), es("osoba-rezervovat"), who="cloud"), 0.45)]),
    ("Došlou žalobu zpracuje lokální strana. Pravidla rozpoznají účastníky, zapíšou je do rejstříku osob "
     "a do spisu založí začerněný text.", [(term(es("vytezeni"), who="lokalni"), 1)]),
    ("Ve spisu pak účastníci vystupují jen pod identifikátorem. Deník spisu osobní údaje neobsahuje.",
     [(term(es("spis-ukazat"), who="cloud", small=True), 1)]),
    ("Text dokumentu čte cloudový agent jen začerněný. Původní text mu skript nevydá.",
     [(term(es("dokument-cist"), who="cloud", small=True), 0.6),
      (term(es("dokument-puvodni"), who="cloud", stamp=True), 0.4)]),
    ("Osobní údaje se vydávají po úrovních. Cloudový agent smí nejvýš doručovací údaje, vždy s uvedeným účelem. "
     "Rodné číslo nedostane.", [(term(es("uroven-1"), es("uroven-3"), who="cloud"), 1)]),
    ("Údaje zadává a čte člověk s lokálním agentem. Malý model běží v počítači přes Ollamu, "
     "údaje čtou pravidla a každý zápis člověk potvrdí.",
     [(term(es("lokalni"), who="lokalni"), 0.65), (term(es("hledat"), who="cloud"), 0.35)]),
    ("Úkony s právními účinky agent jen navrhuje: rozhodnutí, lhůtu nebo vypravení písemnosti. "
     "Každý návrh dostane otisk.",
     [(term(es("navrh-rozhodnuti"), es("navrh-lhuta"), es("navrhy"), who="cloud", small=True), 1)]),
    ("Schválit může jen člověk. Agent bez terminálu a bez přístupu k podpisovému klíči to nedokáže. "
     "Člověk v terminálu opíše náhodný kód.",
     [(term(es("schvalit-agent"), who="cloud", stamp=True), 0.45), (term(es("schvalit-clovek"), who="lokalni"), 0.55)]),
    ("Místo terminálu jde schvalovat i potvrzením nástroje v aplikaci, třeba v Claude Code, v Codexu nebo v aplikaci "
     "Claude. V režimu YOLO se návrh schválí hned a zapíše se to.",
     [(card("Kdo schvaluje úkony", [
         "<b>Terminál:</b> člověk opíše náhodný kód",
         "<b>Aplikace:</b> člověk potvrdí nástroj lmo_schvalit (MCP)",
         "<b>YOLO:</b> nikdo, schválení se zapíše jako yolo"]), 1)]),
    ("Deník spisu je řetěz otisků. Když někdo změní zápis mimo skript, kontrola to odhalí "
     "a výpis spisu na to upozorní.",
     [(term(es("upravit-mimo"), who=("cloud", "Agent s vlastním shellem upraví deník přímo, mimo lmo")), 0.25),
      (term(es("overit"), who="lokalni"), 0.35), (term(es("spis-naruseny"), who="cloud", small=True), 0.4)]),
    ("Každé vložení i nahlédnutí do osobních údajů se zapíše do protokolu přístupů: kdo, kdy, proč a komu. "
     "U trestního spisu je účel povinný i pro nahlédnutí.",
     [(term(es("protokol"), who="lokalni", tiny=True), 0.6), (term(es("trestni"), es("trestni-bez-ucelu"), who="cloud"), 0.4)]),
    ("Záruky platí pro skript. Začerňování stojí na pravidlech, ne na rozpoznávání jmen, a co člověk sám napíše "
     "do chatu cloudového agenta, odchází poskytovateli modelu.",
     [(card("Co skript neovlivní", out=[
         "Co člověk napíše do chatu cloudového agenta, odchází poskytovateli modelu",
         "Jméno mimo roli strany a mimo rejstřík osob začerněné být nemusí",
         "Aplikace Claude běží pod účtem člověka, strop jí drží jen skript"]), 1)]),
    ("Verzi 2 ověřuje " + OVERENI["pocet"] + " automatických testů a audit celé historie repozitáře. "
     "Nálezy nezávislé revize AI agenty jsou opravené.", [(VERIFY, 1)]),
    ("Legal Memory OS. Paměť agentů a elektronický spis, v trezoru Obsidian.", [(TITLE, 1)]),
]

SCENES = [("pamet", s) for s in PAMET] + [("espis", s) for s in ESPIS]


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       check=True, capture_output=True, text=True)
    return float(p.stdout.strip())


def cue_chunks(sentence, width=84):
    if len(sentence) <= width:
        return [sentence]
    parts = re.split(r"(?<=[,:]) ", sentence)
    chunks, cur = [], ""
    for part in parts:
        if cur and len(cur) + 1 + len(part) > width:
            chunks.append(cur)
            cur = part
        else:
            cur = (cur + " " + part) if cur else part
    chunks.append(cur)
    out = []
    for c in chunks:
        # Dlouhý úsek bez čárky rozdělit na vyrovnané části, aby nevznikl osiřelý titulek o jednom slově.
        words, n = c.split(), -(-len(c) // width)
        per = -(-len(words) // n)
        out.extend(" ".join(words[k:k + per]) for k in range(0, len(words), per))
    return out


def ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return "%02d:%02d:%06.3f" % (h, m, s)


def fill(text, name, content):
    """Obsah stránky mezi značkami <!--name--> a <!--/name-->."""
    rx = r"(<!--%s-->).*?(<!--/%s-->)" % (name, name)
    if not re.search(rx, text, flags=re.S):
        raise SystemExit("index.html: chybí značka " + name)
    return re.sub(rx, lambda m: m.group(1) + content + m.group(2), text, flags=re.S)


def page_note(path):
    out, fm = [], 0
    for line in DEMO["notes"][path].rstrip("\n").split("\n"):
        e = esc(line)
        if fm < 2:
            fm += line == "---"
            out.append('<span class="fm">' + e + "</span>")
        elif line.startswith("## "):
            out.append('<span class="blk">' + e + "</span>")
        elif line.startswith("# "):
            out.append('<span class="h1">' + e + "</span>")
        elif line.startswith("### "):
            out.append('<span class="h3">' + e + "</span>")
        else:
            out.append(e)
    return ('\n        <div class="sheet">\n          <span class="path">' + esc(path) + "</span>\n<pre>"
            + "\n".join(out) + "</pre>\n        </div>\n")


def page_refused(step):
    lines = ["$ " + command(step)[0]] + command(step)[1:]
    lines += step["body"].rstrip("\n").split("\n") + [delimiter(step["name"])]
    rows = [esc(l) for l in lines] + ['<span class="err">' + esc(l) + "</span>"
                                       for l in step["stderr"].rstrip("\n").split("\n")]
    return ('        <div class="refused">\n          <span class="stamp" aria-hidden="true"><b>ODMÍTNUTO</b>'
            "<span>nic se nezapsalo</span></span>\n<pre>" + "\n".join(rows) + "</pre>\n        </div>\n")


def page_term(step, label):
    rows = ['<span class="fm">$ ' + esc(" ".join(command(step))) + "</span>"]
    for line in step["stdout"].rstrip("\n").split("\n"):
        rows.append('<span class="fm">' + esc(line) + "</span>" if line.startswith("<<<") else esc(line))
    return ('\n        <div class="sheet">\n          <span class="path">' + esc(label) + "</span>\n<pre>"
            + "\n".join(rows) + "</pre>\n        </div>\n")


def minutes(t):
    n = max(1, round(t / 60))
    return "%d %s" % (n, "minuty" if n in (2, 3, 4) else "minut")


def update_page(t):
    page = ROOT / "index.html"
    text = page.read_text(encoding="utf-8")
    text = fill(text, "prepis", "\n" + "\n".join("        <p>" + esc(sub) + "</p>" for _, (sub, _) in SCENES) + "\n        ")
    text = fill(text, "ledger", page_note("Pamet/pripad_ukazka-s-r-o_najem-skladu.md") + page_refused(STEP["pripad-odmitnuto"]))
    text = fill(text, "spis", page_term(ESTEP["spis-ukazat"], "Výpis spisu pro cloudového agenta"))
    text = fill(text, "verze", VERZE)
    text = fill(text, "verze2", VERZE)
    text = fill(text, "delka", minutes(t))
    page.write_text(text, encoding="utf-8")


def main():
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir()
    MEDIA.mkdir(exist_ok=True)
    css = (ROOT / "video" / "frame.css").as_uri()
    frames, cues, t = [], [], 0.0
    audio = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for i, (part, (sub, shots)) in enumerate(SCENES):
            aiff = BUILD / ("s%02d.aiff" % i)
            run("say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), "--", speech(sub))
            d = duration(aiff)
            length = LEAD + d + TAIL
            wav = BUILD / ("s%02d.wav" % i)
            run("ffmpeg", "-y", "-i", str(aiff), "-af", "adelay=%d:all=1,apad=whole_dur=%.3f" % (LEAD * 1000, length),
                "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(wav))
            audio.append(wav)
            total = sum(w for _, w in shots)
            for k, (body, w) in enumerate(shots):
                png = BUILD / ("f%02d_%d.png" % (i, k))
                doc = ('<!doctype html><html lang="cs"><head><meta charset="utf-8"><link rel="stylesheet" href="'
                       + css + '"></head><body><div class="mark">Legal Memory OS</div>' + body + "</body></html>")
                src = BUILD / ("f%02d_%d.html" % (i, k))
                src.write_text(doc, encoding="utf-8")
                page.goto(src.as_uri())
                page.evaluate("document.fonts.ready")
                page.screenshot(path=str(png))
                frames.append((png, length * w / total))
            sentences = re.split(r"(?<=[.!?])\s+", sub)
            chunks = [c for s in sentences for c in cue_chunks(s)]
            n = sum(len(c) for c in chunks)
            ct = t + LEAD
            for c in chunks:
                cd = d * len(c) / n
                cues.append((ct, ct + cd, "\n".join(textwrap.wrap(c, 46))))
                ct += cd
            t += length
        browser.close()
    lst = BUILD / "frames.txt"
    lst.write_text("".join("file '%s'\nduration %.3f\n" % (p, dur) for p, dur in frames)
                   + "file '%s'\n" % frames[-1][0], encoding="utf-8")
    alst = BUILD / "audio.txt"
    alst.write_text("".join("file '%s'\n" % a for a in audio), encoding="utf-8")
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alst), "-c", "copy", str(BUILD / "voice.wav"))
    out = MEDIA / "legal-memory-os.mp4"
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(BUILD / "voice.wav"),
        "-vf", "fps=30,format=yuv420p,fade=t=in:st=0:d=0.5,fade=t=out:st=%.3f:d=0.6" % (t - 0.6),
        "-c:v", "libx264", "-preset", "slow", "-crf", "22", "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "96k", "-t", "%.3f" % t, "-movflags", "+faststart",
        "-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
        "-flags:a", "+bitexact", "-bsf:v", "filter_units=remove_types=6",
        "-metadata:s:v:0", "encoder=", str(out))
    vtt = "WEBVTT\n\n" + "".join("%d\n%s --> %s\n%s\n\n" % (k + 1, ts(a), ts(b), txt)
                                 for k, (a, b, txt) in enumerate(cues))
    (MEDIA / "legal-memory-os.vtt").write_text(vtt.rstrip("\n") + "\n", encoding="utf-8")
    Image.open(frames[0][0]).convert("RGB").resize((1280, 720), Image.LANCZOS).save(
        MEDIA / "poster.jpg", "JPEG", quality=86, optimize=True, progressive=True)
    update_page(t)
    print("video: %.1f s, %d snímků, %d titulků" % (t, len(frames), len(cues)))


if __name__ == "__main__":
    main()
