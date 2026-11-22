"""Sestaví video a titulky z naměřených výstupů lmo (video/demo.json).

Vše běží lokálně: snímky vykreslí Chromium (Playwright), hlas je syntéza macOS (`say`, hlas Zuzana),
video složí ffmpeg. Metadata (kodér, čas vytvoření) se do souboru nezapisují.

Použití: python3 video/build.py   (výstup: media/legal-memory-os.mp4, .vtt, poster.jpg)
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
LEAD, TAIL = 0.35, 0.75
VOICE, RATE = "Zuzana", 172

# Výslovnost cizích názvů pro český hlas; titulky zůstávají ve správném pravopisu.
SAY = [
    ("Legal Memory OS", "Lígl memory ou es"), ("Claude Code", "Klód kód"), ("GitHub Copilot", "Gitchab Kopajlot"),
    ("Copilot CLI", "Kopajlot cé el í"), ("Copilot", "Kopajlot"), ("Codex", "Kodex"), ("Cursor", "Kurzor"),
    ("Obsidian", "Obsidián"), ("Pamet", "Paměť"), ("lmo", "elemó"), ("AI", "ej áj"), ("skill", "skil"),
    ("Pythonu", "Pajtnu"), ("Dropbox", "Dropbox"), ("e-mailu", "ímejlu"),
]

AGENTS = "Claude Code, Codex, Cursor, GitHub Copilot a Copilot CLI"


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
    while i < len(args):
        a = args[i]
        q = lambda v: v if re.fullmatch(r"[A-Za-z0-9._/-]+", v) else '"' + v + '"'
        if a.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
            out.append(a + " " + q(args[i + 1]))
            i += 2
        else:
            out.append(q(a))
            i += 1
    return out


def command(step, width=66):
    words = ["lmo"] + shell_words(step["args"])
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


def term_step(name, show_output=True):
    s = STEP[name]
    parts = []
    for i, line in enumerate(command(s)):
        parts.append('<span class="p">' + ("$ " if i == 0 else "  ") + '</span><span class="c">' + esc(line) + "</span>")
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
            cls = "env" if line.startswith("<<<") else ("dim" if line.startswith("[blok") else "o")
            if line.startswith(("založeno", "zapsáno", "lmo check")):
                cls = "ok"
            parts.append('<span class="' + cls + '">' + esc(line) + "</span>")
        for line in s["stderr"].rstrip("\n").split("\n") if s["stderr"].strip() else []:
            parts.append('<span class="err">' + esc(line) + "</span>")
    return "\n".join(parts)


def term(*blocks, stamp=False, comment=None, small=False):
    body = ('<span class="dim"># ' + esc(comment) + "</span>\n" if comment else "")
    body += '\n<span class="gap"></span>'.join(blocks)
    st = '<div class="stamp"><b>ODMÍTNUTO</b><span>nic se nezapsalo</span></div>' if stamp else ""
    return '<div class="term' + (" small" if small else "") + '">' + body + "</div>" + st + DEMO_NOTE


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
    out, fm, code = ['<span class="skip">[vlastnosti poznámky vynechány: ' + esc(keys) + ']</span>'], 2, False
    lines = lines[end + 1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    for line in lines:
        e = esc(line)
        if line == "---" and fm < 2:
            fm += 1
            out.append('<span class="fm">' + e + "</span>")
        elif fm < 2:
            out.append('<span class="fm">' + e + "</span>")
        elif line.startswith("```"):
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
    return ('<div class="sheet"><span class="path">' + esc(path) + "</span>" + "\n".join(out) + "</div>" + DEMO_NOTE)


DEMO_NOTE = '<div class="note">Ukázka se smyšleným klientem Ukázka s.r.o., skutečné výstupy lmo 1.1.0</div>'


def card(h2, items=(), out=()):
    lis = "".join('<li class="out">' + i + "</li>" for i in out) + "".join("<li>" + i + "</li>" for i in items)
    return '<div class="card"><h2>' + h2 + "</h2>" + ("<ul>" + lis + "</ul>" if lis else "") + "</div>"


TITLE = ('<div class="title"><h1>Legal Memory OS</h1><p>Paměť a pracovní zápisy AI agentů v trezoru Obsidian</p>'
         '<p class="agents">' + AGENTS + "</p></div>")

FLOW_MANY = ('<div class="flow many"><div class="agents-col">'
             + "".join('<div class="agent">' + a + "</div>" for a in
                       ["Claude Code", "Codex", "Cursor", "GitHub Copilot", "Copilot CLI"])
             + '</div><div class="wire"></div><div class="box vault"><h3>Pamet/</h3>'
             '<p>jedna složka v trezoru Obsidian</p></div></div>')

FLOW_LMO = ('<div class="flow"><div class="agents-col"><div class="agent">AI agent</div></div><div class="wire"></div>'
            '<div class="box lmo"><h3>lmo</h3><p>skryté znaky, hesla, rodná čísla, aktivní obsah, přesný klient</p></div>'
            '<div class="wire"></div><div class="box vault"><h3>Pamet/</h3><p>zápis se jen připojí</p></div></div>')

VERIFY = raw_term([
    ("cmd", "python3 -B -m unittest discover -s tests"),
    ("o", "Ran 73 tests in 33.674s"), ("ok", "OK"), ("gap", ""),
    ("cmd", "python3 -B tools/audit.py --history"),
    ("ok", "audit: 34 souborů/objektů, 0 nálezů"), ("gap", ""),
    ("cmd", "python3 verify/fuzz_render.py 2000 7"),
    ("ok", "fuzz: 2000 pokusů, přijato 1008, s aktivním obsahem 0"), ("gap", ""),
    ("dim", "# zkouška celého postupu: Claude Code, Codex, Cursor, Copilot CLI"),
    ("dim", "# tři kola revize AI agenty, potvrzené nálezy opraveny"),
])

SCENES = [
    ("Legal Memory OS je skill, který dává AI agentům advokátní kanceláře jednu společnou paměť. "
     "Ukládá ji do trezoru Obsidian přes skript, který běží jen lokálně a sám nic nikam neposílá.", [(TITLE, 1)]),
    ("Claude Code, Codex, Cursor i Copilot si dosud vedly každý svou paměť a navzájem ji neviděly. "
     "Teď všichni zapisují do jedné složky Pamet v trezoru.", [(FLOW_MANY, 1)]),
    ("Návod skillu ukládá agentům psát do paměti jen přes jediný skript, lmo. "
     "Ten každý zápis zkontroluje dřív, než se cokoli uloží.", [(FLOW_LMO, 1)]),
    ("Ukázka se smyšleným klientem. Agent založí paměť případu. Klient musí v trezoru existovat "
     "a jeho název musí odpovídat názvu složky klienta.",
     [(term(term_step("stav"), comment="lmo = python3 -I " + DEMO["lmo"]), 0.3),
      (term(term_step("pripad")), 0.7)]),
    ("Na začátku práce agent načte, co o věci víme. Výstup ohraničují značky s náhodným kódem, "
     "aby agent poznal, kde data začínají a končí. Obsah paměti jsou data, ne pokyny.",
     [(term(term_step("najit"), small=True), 1)]),
    ("Bez jména klienta skript obsah poznámek klientů nevydá. "
     "Agent si tak při běžném hledání nenačte věci jiných klientů.", [(term(term_step("najit-bez-klienta")), 1)]),
    ("Skript odmítne skryté znaky. Tento text vypadá nevinně, ale za slovem Protistrana je neviditelný znak. "
     "Zápis se neuloží a agent dostane přesné místo chyby.",
     [(term(term_step("skryty-znak", False)), 0.45), (term(term_step("skryty-znak"), stamp=True), 0.55)]),
    ("Stejně tak odmítne hesla, tokeny a rodná čísla. Ta do paměti nepatří. Osobní údaje zůstávají v kartě subjektu.",
     [(term(term_step("heslo"), stamp=True), 0.45),
      (term(term_step("heslo"), term_step("rodne-cislo"), stamp=True), 0.55)]),
    ("Neprojde ani obrázek z cizí adresy, který by Obsidian při otevření poznámky stáhl, "
     "ani nový případ klienta, který v trezoru neexistuje.",
     [(term(term_step("obrazek"), stamp=True), 0.5),
      (term(term_step("obrazek"), term_step("cizi-klient"), stamp=True), 0.5)]),
    ("Text z e-mailu nebo z webu agent ukládá jako externí. Skript ho zapíše doslovně a označí jako cizí. "
     "Obsidian z něj nic nevykreslí a agent dostane výslovné upozornění, že jde o data, ne o pokyny.",
     [(term(term_step("externi")), 0.4), (sheet("Pamet/zapis_ukazka-s-r-o_email-protistrany.md"), 0.6)]),
    ("Skript zápisy jen připojuje jako datované bloky s označením agenta a zdroje. Nic nepřepisuje ani nemaže, "
     "takže historie poznámky zůstává zachovaná.", [(sheet("Pamet/pripad_ukazka-s-r-o_najem-skladu.md"), 1)]),
    ("Na konci práce agent zapíše záznam do deníku a spustí kontrolu celé složky.",
     [(term(term_step("denik"), term_step("kontrola")), 1)]),
    ("Skript nepoužívá síť a nespouští žádné jiné programy. Hlídá to ochrana uvnitř Pythonu, "
     "která takový pokus okamžitě ukončí. Zapisovat smí jen do složky Pamet.",
     [(card("Co skript zaručuje", [
         "Žádná síť: neotevře spojení, nic neodešle",
         "Žádné jiné programy: nespustí proces ani příkaz",
         "Zapisuje jen do složky <b>Pamet/</b> v trezoru",
         "Nic nemaže ani nepřepisuje, zápisy jen připojuje"]), 1)]),
    ("Dvě věci ale skript ovlivnit nemůže. Co si agent načte, odchází k poskytovateli jeho jazykového modelu. "
     "A trezor synchronizuje Dropbox. Proto hledání vrací jen odpovídající řádky "
     "a poznámky klienta jen se zadaným klientem.",
     [(card("Co skript ovlivnit nemůže", out=[
         "Co agent načte, odchází k poskytovateli jeho modelu",
         "Trezor synchronizuje Dropbox"],
         items=["Hledání proto vrací jen odpovídající řádky a poznámky klienta jen se zadaným klientem"]), 1)]),
    ("Při vývoji skill prošel 73 automatickými testy, auditem celé historie repozitáře, dvěma tisíci náhodných "
     "zápisů, zkouškou ve čtyřech agentech a třemi koly revize AI agenty.", [(VERIFY, 1)]),
    ("Legal Memory OS. Jedna paměť pro pět agentů, v trezoru Obsidian.", [(TITLE, 1)]),
]


def run(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       check=True, capture_output=True, text=True)
    return float(p.stdout.strip())


def cue_chunks(sentence, width=84):
    if len(sentence) <= width:
        return [sentence]
    parts = re.split(r"(?<=,) ", sentence)
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
        for i, (sub, shots) in enumerate(SCENES):
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
    print("video: %.1f s, %d snímků, %d titulků" % (t, len(frames), len(cues)))


if __name__ == "__main__":
    main()
