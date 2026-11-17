"""anix-snap: beautiful code screenshots right from your terminal."""
from __future__ import annotations

import argparse
import base64
import io
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from pygments.style import Style
from pygments.token import Comment, Generic, Keyword, Name, Number, Operator, String, Text, Token
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound
from rich.console import Console
from rich.syntax import PygmentsSyntaxTheme, Syntax
from rich.terminal_theme import TerminalTheme

__version__ = "0.3.3"

# ---------- i18n: (ru, en) ----------
STRINGS = {
    "desc": ("Красивые скриншоты кода в SVG/PNG", "Beautiful code screenshots to SVG/PNG"),
    "target": ("файл[:начало-конец] или - для stdin", "file[:start-end] or - for stdin"),
    "theme": ("тема: peach, noir, neon, своя из папки тем или путь к .json",
              "theme: peach, noir, neon, a user theme or a path to .json"),
    "out": ("файл результата: .svg или .png", "output file: .svg or .png"),
    "lang": ("язык кода, если не угадался: python, js, rust...", "code language if not detected: python, js, rust..."),
    "title": ("заголовок окна (по умолчанию имя файла)", "window title (file name by default)"),
    "hl": ("отметить строки: 12,15-17", "mark lines: 12,15-17"),
    "nolines": ("без номеров строк", "hide line numbers"),
    "width": ("ширина в символах", "width in characters"),
    "copy": ("скопировать картинку в буфер обмена", "copy the image to the clipboard"),
    "diff": ("снимок git diff вместо файла", "snapshot of git diff instead of a file"),
    "rev": ("с чем сравнивать в --diff: HEAD~1, main...", "what to compare in --diff: HEAD~1, main..."),
    "staged": ("в --diff брать staged-изменения", "use staged changes in --diff"),
    "font": ("встроить шрифт Fira Code в SVG (работает оффлайн)", "embed Fira Code into the SVG (works offline)"),
    "scale": ("масштаб PNG (по умолчанию 2)", "PNG scale (default 2)"),
    "list": ("показать темы", "list themes"),
    "ui": ("язык интерфейса: ru или en", "interface language: ru or en"),
    "need_target": ("укажи файл, - для stdin или --diff", "give a file, - for stdin or --diff"),
    "not_found": ("файл не найден: {path}", "file not found: {path}"),
    "too_short": ("в файле всего {n} строк", "the file has only {n} lines"),
    "unknown_theme": ("нет такой темы: {name}. Список: --list-themes", "unknown theme: {name}. See --list-themes"),
    "bad_ext": ("поддерживаются только .svg и .png", "only .svg and .png are supported"),
    "no_png": ("для PNG нужен cairosvg (pip install anix-snap[png]) или resvg в PATH",
               "PNG needs cairosvg (pip install anix-snap[png]) or resvg in PATH"),
    "no_clip": ("не нашёл, чем копировать: поставь wl-clipboard или xclip",
                "no clipboard tool: install wl-clipboard or xclip"),
    "clip_fail": ("не получилось скопировать в буфер: {err}", "copy to clipboard failed: {err}"),
    "clip_svg": ("PNG недоступен, в буфер скопирован SVG-файл", "PNG unavailable, copied the SVG file instead"),
    "no_git": ("git не найден в PATH", "git not found in PATH"),
    "git_failed": ("git diff упал: {err}", "git diff failed: {err}"),
    "no_changes": ("изменений нет", "no changes"),
    "font_fail": ("шрифт не скачался, оставляю ссылку на CDN: {err}", "font download failed, keeping the CDN link: {err}"),
    "saved": ("готово: {path}", "saved: {path}"),
    "copied": ("скопировано в буфер обмена", "copied to the clipboard"),
    "themes": ("темы:", "themes:"),
    "unknown_word": ("не понял «{word}». Подсказка: asnap -h", "did not get \"{word}\". Help: asnap -h"),
}
STRINGS.update({
    "unknown_word": ("не понял «{word}»: такого файла нет, и это не тема и не язык. Подсказка: asnap -h",
                     "did not get \"{word}\": no such file, theme or language. Help: asnap -h"),
    "unknown_diff_word": ("не понял «{word}»: это не файл и не коммит/ветка",
                          "did not get \"{word}\": not a file and not a commit/branch"),
    "ambiguous": ("«{word}» это и ветка/коммит, и файл. Для файла напиши ./{word}",
                  "\"{word}\" is both a branch/commit and a file. For the file write ./{word}"),
    "bad_range": ("строки считаются с 1: «{r}»", "lines start at 1: \"{r}\""),
    "dup_range": ("диапазон строк указан дважды", "the line range is given twice"),
    "two_files": ("два файла сразу: «{a}» и «{b}», нужен один", "two files at once: \"{a}\" and \"{b}\", need one"),
    "two_langs": ("два языка сразу: «{a}» и «{b}»", "two languages at once: \"{a}\" and \"{b}\""),
    "two_modes": ("diff и themes вместе не работают", "diff and themes do not go together"),
    "themes_alone": ("asnap themes пишется без других слов", "asnap themes takes no other words"),
    "not_in_diff": ("«{word}» не работает с diff", "\"{word}\" does not work with diff"),
    "hl_ignored": ("отметки строк видны только с номерами строк, пропускаю их", "line marks need line numbers, skipping them"),
    "no_png": ("PNG не сделать: {hint}", "can't make PNG: {hint}"),
    "png_hint_win": ("поставь resvg (GitHub Releases или cargo install resvg) и добавь в PATH; cairosvg на Windows без отдельного cairo не работает",
                     "install resvg (GitHub Releases or cargo install resvg) and add it to PATH; cairosvg needs a separate cairo on Windows"),
    "png_hint": ("pip install cairosvg или resvg в PATH", "pip install cairosvg or resvg in PATH"),
    "not_git_repo": ("тут нет git-репозитория: asnap diff работает внутри него",
                     "not inside a git repository: run asnap diff inside one"),
    "stdin_tty": ("ждал код через пайп: cat code.py | asnap -", "expected code from a pipe: cat code.py | asnap -"),
    "empty_stdin": ("входной поток пуст: нечего скриншотить", "stdin is empty: nothing to snap"),
    "empty_file": ("в «{name}» пусто: нечего скриншотить", "\"{name}\" is empty: nothing to snap"),
    "empty_range": ("строки {s}-{e} в «{name}» пустые: нечего скриншотить", "lines {s}-{e} of \"{name}\" are blank: nothing to snap"),
    "clip_need_png": ("в буфер кладу только PNG, а его сейчас не сделать: {hint}",
                      "the clipboard needs a PNG, which can't be made right now: {hint}"),
})
UI = "en"


class SnapError(Exception):
    pass


def tr(key: str, **kw) -> str:
    ru, en = STRINGS[key]
    return (ru if UI == "ru" else en).format(**kw)


def detect_ui(argv: list[str]) -> str:
    if "--ui" in argv:
        i = argv.index("--ui")
        if i + 1 < len(argv):
            return "ru" if argv[i + 1].lower().startswith("ru") else "en"
    env = os.environ.get("ANIX_LANG", "")
    if env:
        return "ru" if env.lower().startswith("ru") else "en"
    if sys.platform == "win32":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ru" if (lang_id & 0x3FF) == 0x19 else "en"
        except Exception:
            pass
    loc = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
    return "ru" if loc.startswith("ru") or "russian" in loc else "en"


# ---------- paths ----------
def config_dir() -> Path:
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    return Path(base) / "anix-snap" if base else Path.home() / ".config" / "anix-snap"


def cache_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        d = Path(os.environ["LOCALAPPDATA"]) / "anix-snap"
    else:
        d = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "anix-snap"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- themes ----------
# Цвета примерные: подставь точные hex из тем anixcode / PRISM
THEMES = {
    "peach": dict(bg="#1c1917", fg="#f5e6dc", kw="#ffab91", fn="#ffd3b6", str="#c5e1a5", num="#ffcc80",
                  comment="#8d7b72", op="#ef9a9a", builtin="#f8bbd0", add="#a5d6a7", rm="#ef9a9a"),
    "noir": dict(bg="#0d0d0d", fg="#e6e6e6", kw="#ffffff", fn="#d0d0d0", str="#a8a8a8", num="#bdbdbd",
                 comment="#5c5c5c", op="#9e9e9e", builtin="#cfcfcf", add="#ffffff", rm="#6e6e6e"),
    "neon": dict(bg="#0b0f1a", fg="#d6e2ff", kw="#ff4fd8", fn="#00e5ff", str="#7dff7a", num="#ffe14d",
                 comment="#4b5b80", op="#ff8a3d", builtin="#b388ff", add="#39ff14", rm="#ff3b5c"),
}


def user_themes() -> dict[str, Path]:
    d = config_dir() / "themes"
    return {p.stem: p for p in d.glob("*.json")} if d.is_dir() else {}


def load_theme(name: str) -> dict:
    if name in THEMES:
        return THEMES[name]
    path = user_themes().get(name) or (Path(name) if Path(name).is_file() else None)
    if not path:
        raise SnapError(tr("unknown_theme", name=name))
    return {**THEMES["peach"], **json.loads(path.read_text(encoding="utf-8"))}


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def pygments_style(p: dict) -> type[Style]:
    return type("AnixStyle", (Style,), {
        "background_color": p["bg"],
        "styles": {
            Token: p["fg"], Text: p["fg"],
            Keyword: f"bold {p['kw']}",
            Name.Builtin: p["builtin"], Name.Decorator: p["builtin"],
            Name.Function: p["fn"], Name.Class: f"bold {p['fn']}",
            String: p["str"], Number: p["num"], Operator: p["op"],
            Comment: f"italic {p['comment']}",
            Generic.Inserted: p["add"], Generic.Deleted: p["rm"],
            Generic.Heading: f"bold {p['fn']}", Generic.Subheading: p["kw"],
        },
    })


def terminal_theme(p: dict) -> TerminalTheme:
    ansi = [hex_rgb(p[k]) for k in ("bg", "op", "str", "num", "fn", "kw", "builtin", "fg")]
    return TerminalTheme(hex_rgb(p["bg"]), hex_rgb(p["fg"]), ansi, ansi)


# ---------- input ----------
RANGE = re.compile(r"^(\d+)(?:-(\d+))?$")
HL = re.compile(r"^\+(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)$")
KEYWORDS = ("diff", "themes")


def make_range(a: str, b: str | None = None) -> tuple[int, int]:
    s, e = int(a), int(b or a)
    if s < 1 or e < 1:
        raise SnapError(tr("bad_range", r=f"{a}-{b}" if b else a))
    return (s, e) if s <= e else (e, s)


def parse_target(target: str) -> tuple[str, int | None, int | None]:
    path, sep, rng = target.rpartition(":")
    m = RANGE.match(rng) if sep and path else None
    if m:
        return (path, *make_range(m[1], m[2]))
    return target, None, None


def parse_hl(spec: str | None) -> set[int]:
    out: set[int] = set()
    for part in filter(None, (spec or "").split(",")):
        a, _, b = part.partition("-")
        s, e = make_range(a, b or None)
        out.update(range(s, e + 1))
    return out


def looks_like_path(w: str) -> bool:
    return "/" in w or "\\" in w or Path(w).exists()


def pick_lexer(name: str, code: str, lang: str | None) -> str:
    if lang:
        return lang
    if name == "stdin":  # no file name: guess from the code itself
        try:
            return guess_lexer(code).aliases[0]
        except (ClassNotFound, IndexError):
            return "text"
    return Syntax.guess_lexer(name, code)


def read_source(path: str) -> tuple[str, str]:
    if path == "-":
        if sys.stdin is None or sys.stdin.isatty():  # no pipe: read() would just hang
            raise SnapError(tr("stdin_tty"))
        return sys.stdin.read(), "stdin"
    p = Path(path)
    if not p.is_file():
        raise SnapError(tr("not_found", path=path))
    return p.read_text(encoding="utf-8", errors="replace"), p.name


def _git(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise SnapError(tr("no_git")) from None


def git_is_rev(w: str) -> bool:
    if ".." in w:  # main..feature, main...feature, HEAD~3..; but not ../shared/api.py
        parts = [p for p in re.split(r"\.{2,3}", w) if p]
        return bool(parts) and all(git_is_rev(p) for p in parts)
    return _git("rev-parse", "--verify", "--quiet", f"{w}^{{commit}}").returncode == 0


def ensure_repo() -> None:
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        raise SnapError(tr("not_git_repo"))


def git_is_path(w: str) -> bool:
    if Path(w).exists():
        return True
    r = _git("log", "-1", "--format=%h", "--", w)  # deleted files still have history
    return r.returncode == 0 and bool(r.stdout.strip())


def git_diff(revs: list[str], paths: list[str], staged: bool) -> str:
    args = ["--no-pager", "diff", "--no-color", "--no-ext-diff"]
    if staged:
        args.append("--cached")
    args += revs
    if paths:
        args += ["--", *paths]
    r = _git(*args)
    if r.returncode != 0:
        first = (r.stderr.strip().splitlines() or ["?"])[0]  # one line, not git's whole usage text
        raise SnapError(tr("git_failed", err=first))
    return r.stdout


def clean_diff(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith(("diff --git", "index ")))


# ---------- render ----------
def render_svg(code: str, lexer: str, pal: dict, *, title: str, first: int = 1,
               line_numbers: bool = True, hl: set[int] | None = None, width: int | None = None) -> str:
    code = code.rstrip("\n")
    syntax = Syntax(
        code, lexer,
        theme=PygmentsSyntaxTheme(pygments_style(pal)),
        line_numbers=line_numbers, start_line=first,
        highlight_lines=hl or set(), padding=(1, 2), word_wrap=True,
    )
    code = code.rstrip("\n")
    lines = code.splitlines() or [""]
    gutter = len(str(first + len(lines))) + 3 if line_numbers else 0
    auto = min(max(len(l) for l in lines) + gutter + 6, 120)
    w = width or max(auto, len(title) + 10, 30)
    console = Console(record=True, file=io.StringIO(), width=w,
                      force_terminal=True, force_jupyter=False, color_system="truecolor")
    console.print(syntax)
    return console.export_svg(title=title, theme=terminal_theme(pal))


WOFF2 = re.compile(r'url\("(https://[^"]+?\.woff2)"\)')
WOFF = re.compile(r',\s*url\("https://[^"]+?\.woff"\)\s*format\("woff"\)')


def _font_bytes(url: str, f: Path) -> bytes:
    if f.exists():
        data = f.read_bytes()
        if data[:4] == b"wOF2":
            return data
    with urllib.request.urlopen(url, timeout=10) as r:
        data = r.read()
    if data[:4] != b"wOF2":
        raise OSError(f"not a woff2 font: {url}")
    tmp = f.with_name(f.name + ".part")  # write fully, then rename: no half files in the cache
    tmp.write_bytes(data)
    os.replace(tmp, f)
    return data


def embed_fonts(svg: str) -> str:
    fonts = cache_dir() / "fonts"
    fonts.mkdir(exist_ok=True)

    def inline(m: re.Match) -> str:
        data = _font_bytes(m[1], fonts / m[1].rsplit("/", 1)[-1])
        return f'url("data:font/woff2;base64,{base64.b64encode(data).decode()}")'

    try:
        return WOFF2.sub(inline, WOFF.sub("", svg))
    except (OSError, ValueError) as e:
        print(tr("font_fail", err=e), file=sys.stderr)
        return svg


def png_hint() -> str:
    return tr("png_hint_win") if sys.platform == "win32" else tr("png_hint")


def svg_to_png(svg_path: Path, png_path: Path, scale: float = 2) -> None:
    try:
        import cairosvg  # on Windows raises OSError when the cairo DLL is missing
    except (ImportError, OSError):
        cairosvg = None
    if cairosvg:
        cairosvg.svg2png(bytestring=Path(svg_path).read_bytes(), write_to=str(png_path), scale=scale)
        return
    resvg = shutil.which("resvg")
    if resvg:
        subprocess.run([resvg, "--zoom", str(scale), str(svg_path), str(png_path)],
                       check=True, capture_output=True)
        return
    raise SnapError(tr("no_png", hint=png_hint()))


# ---------- clipboard ----------
def copy_to_clipboard(path: Path) -> None:
    p = str(Path(path).resolve())
    png = p.lower().endswith(".png")
    stdin = None
    if sys.platform == "win32":
        q = p.replace("'", "''")
        if png:
            ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                  f"[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{q}'))")
        else:
            ps = ("Add-Type -AssemblyName System.Windows.Forms; "
                  "$c = New-Object System.Collections.Specialized.StringCollection; "
                  f"[void]$c.Add('{q}'); [System.Windows.Forms.Clipboard]::SetFileDropList($c)")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", ps]
    elif sys.platform == "darwin":
        script = (f'set the clipboard to (read (POSIX file "{p}") as «class PNGf»)' if png
                  else f'set the clipboard to (POSIX file "{p}" as alias)')
        cmd = ["osascript", "-e", script]
    else:
        mime = "image/png" if png else "image/svg+xml"
        if shutil.which("wl-copy"):
            cmd, stdin = ["wl-copy", "--type", mime], open(p, "rb")
        elif shutil.which("xclip"):
            cmd = ["xclip", "-selection", "clipboard", "-t", mime, "-i", p]
        else:
            raise SnapError(tr("no_clip"))
    try:
        subprocess.run(cmd, check=True, stdin=stdin, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise SnapError(tr("clip_fail", err=e)) from None
    finally:
        if stdin:
            stdin.close()


# ---------- cli ----------
HELP = {
    "ru": """asnap: скриншоты кода

  asnap api.py                 весь файл, картинка сразу в буфере обмена
  asnap api.py 10-40           строки 10-40
  asnap api.py 10-40 neon      тема: peach, noir, neon или своя
  asnap api.py +12 +15-17      отметить строки
  asnap api.py png             формат: png или svg (по умолчанию сам выберет)
  asnap diff                   текущий git diff
  asnap diff api.py staged     diff одного файла, staged-изменения
  asnap diff HEAD~1            сравнить с коммитом
  cat x.rs | asnap - rust      код из stdin, язык словом
  asnap themes                 список тем

Ещё: -o ФАЙЛ, --title ТЕКСТ, --no-lines, --no-copy, -w N, --scale N, --cdn-font, --ui ru|en, -V
""",
    "en": """asnap: code screenshots

  asnap api.py                 whole file, image goes straight to the clipboard
  asnap api.py 10-40           lines 10-40
  asnap api.py 10-40 neon      theme: peach, noir, neon or your own
  asnap api.py +12 +15-17      mark lines
  asnap api.py png             format: png or svg (picked automatically by default)
  asnap diff                   current git diff
  asnap diff api.py staged     diff of one file, staged changes
  asnap diff HEAD~1            compare with a commit
  cat x.rs | asnap - rust      code from stdin, language as a word
  asnap themes                 list themes

More: -o FILE, --title TEXT, --no-lines, --no-copy, -w N, --scale N, --cdn-font, --ui ru|en, -V
""",
}


def is_lexer(name: str) -> bool:
    try:
        get_lexer_by_name(name)
        return True
    except ClassNotFound:
        return False


def png_available() -> bool:
    try:
        import cairosvg  # noqa: F401
        return True
    except (ImportError, OSError):
        return shutil.which("resvg") is not None


def parse_words(words: list[str]) -> dict:
    """Turn plain words like `api.py 10-40 neon +12 png` into options, in any order.

    Keywords (diff, themes, theme names, png/svg, staged) always win over files:
    for a file with such a name write ./diff or .\\diff.
    """
    o = dict(mode="file", file=None, start=None, end=None, theme="peach", hl=set(),
             fmt=None, lang=None, revs=[], paths=[], staged=False)
    modes = {w.lower() for w in words if w.lower() in KEYWORDS}
    if len(modes) > 1:
        raise SnapError(tr("two_modes"))
    if modes:
        o["mode"] = modes.pop()
    themes = {t.lower(): t for t in [*THEMES, *user_themes()]}

    rest = []
    for w in words:
        low = w.lower()
        if low in KEYWORDS:
            continue
        if low in themes:
            o["theme"] = themes[low]
        elif low in ("png", "svg"):
            o["fmt"] = low
        elif HL.match(w):
            o["hl"] |= parse_hl(w[1:])
        elif low == "staged" and o["mode"] == "diff":
            o["staged"] = True
        elif RANGE.match(w) and o["mode"] == "file":
            if o["start"]:
                raise SnapError(tr("dup_range"))
            o["start"], o["end"] = make_range(*RANGE.match(w).groups())
        else:
            rest.append(w)

    if o["mode"] == "themes":
        if rest:
            raise SnapError(tr("themes_alone"))
        return o

    if o["mode"] == "diff":  # ask git itself what each word is
        if rest:
            ensure_repo()
        for w in rest:
            if w == "-":
                raise SnapError(tr("not_in_diff", word=w))
            is_rev, is_path = git_is_rev(w), git_is_path(w)
            if is_rev and is_path:
                raise SnapError(tr("ambiguous", word=w))
            if is_rev:
                o["revs"].append(w)
            elif is_path:
                o["paths"].append(w)
            else:
                raise SnapError(tr("unknown_diff_word", word=w))
        return o

    # file mode: one file (or -) and maybe a language, in any order
    files, others = [], []
    for w in rest:
        is_file = w == "-" or looks_like_path(parse_target(w)[0])
        (files if is_file else others).append(w)
    if len(files) > 1:  # "python api.py" while a file named python exists
        lex = [f for f in files if is_lexer(f.lower()) and not ("/" in f or "\\" in f)]
        if len(files) - len(lex) == 1:
            files = [f for f in files if f not in lex]
            others += lex
    if len(files) > 1:
        raise SnapError(tr("two_files", a=files[0], b=files[1]))
    for w in others:
        if not is_lexer(w.lower()):
            raise SnapError(tr("unknown_word", word=w))
        if o["lang"]:
            raise SnapError(tr("two_langs", a=o["lang"], b=w.lower()))
        o["lang"] = w.lower()
    if files:
        path, start, end = ("-", None, None) if files[0] == "-" else parse_target(files[0])
        o["file"] = path
        if start:
            if o["start"]:
                raise SnapError(tr("dup_range"))
            o["start"], o["end"] = start, end
    return o


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="asnap", add_help=False)
    ap.add_argument("words", nargs="*")
    ap.add_argument("-o", "--out")
    ap.add_argument("--title")
    ap.add_argument("--no-lines", action="store_true")
    ap.add_argument("--no-copy", action="store_true")
    ap.add_argument("-w", "--width", type=int)
    ap.add_argument("--scale", type=float, default=2)
    ap.add_argument("--cdn-font", action="store_true")
    ap.add_argument("--ui", choices=["ru", "en"])
    ap.add_argument("-h", "--help", action="store_true")
    ap.add_argument("-V", "--version", action="version", version=f"anix-snap {__version__}")
    return ap


def run(a: argparse.Namespace) -> None:
    o = parse_words(a.words)
    if o["mode"] == "themes":
        print(tr("themes"))
        for name in [*THEMES, *user_themes()]:
            print("  " + name)
        return
    if o["mode"] == "file" and not o["file"]:
        raise SnapError(tr("need_target"))
    pal = load_theme(o["theme"])

    if o["mode"] == "diff":
        paths = o["paths"]
        ensure_repo()
        code = clean_diff(git_diff(o["revs"], paths, o["staged"])).expandtabs(4)
        if not code.strip():
            raise SnapError(tr("no_changes"))
        one = Path(paths[0]) if len(paths) == 1 else None
        name = one.name if one else "git diff"
        stem = (one.stem if one else "changes") + ".diff"
        if o["hl"]:
            print(tr("hl_ignored"), file=sys.stderr)
        lexer, first, numbers, hl = "diff", 1, False, set()
    else:
        code, name = read_source(o["file"])
        lines = code.expandtabs(4).splitlines()
        start, end = o["start"], o["end"]
        if start:
            if start > len(lines):
                raise SnapError(tr("too_short", n=len(lines)))
            lines = lines[start - 1:end]
        code, first, stem = "\n".join(lines), start or 1, Path(name).stem
        if not code.strip():  # no empty black frame in the clipboard
            if o["file"] == "-":
                raise SnapError(tr("empty_stdin"))
            if start:
                raise SnapError(tr("empty_range", s=start, e=end, name=name))
            raise SnapError(tr("empty_file", name=name))
        lexer = pick_lexer(name, code, o["lang"])
        numbers, hl = not a.no_lines, o["hl"]
        if hl and not numbers:
            print(tr("hl_ignored"), file=sys.stderr)
            hl = set()

    svg = render_svg(code, lexer, pal, title=a.title or name, first=first,
                     line_numbers=numbers, hl=hl, width=a.width)
    if not a.cdn_font:
        svg = embed_fonts(svg)

    if a.out:
        out = Path(a.out)
    else:
        fmt = o["fmt"] or ("png" if png_available() else "svg")
        out = Path(f"{stem}.snap.{fmt}")
    ext = out.suffix.lower()
    if ext not in (".svg", ".png"):
        raise SnapError(tr("bad_ext"))
    if ext == ".svg":
        out.write_text(svg, encoding="utf-8")
    else:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "snap.svg"
            tmp.write_text(svg, encoding="utf-8")
            svg_to_png(tmp, out, a.scale)
    print(tr("saved", path=out))

    if a.no_copy:
        return
    try:  # copying is a bonus: a failure here only warns
        target = out
        if ext == ".svg":
            png = cache_dir() / "last.png"
            try:
                svg_to_png(out, png, a.scale)
                target = png
            except SnapError:
                if sys.platform not in ("win32", "darwin"):  # Linux apps can't paste image/svg+xml
                    raise SnapError(tr("clip_need_png", hint=png_hint())) from None
                print(tr("clip_svg"))
        copy_to_clipboard(target)
        print(tr("copied"))
    except SnapError as e:
        print(f"anix-snap: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    global UI
    argv = sys.argv[1:] if argv is None else argv
    UI = detect_ui(argv)
    args = build_parser().parse_intermixed_args(argv)
    if args.help or not args.words:
        print(HELP[UI])
        return
    try:
        run(args)
    except SnapError as e:
        print(f"anix-snap: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
