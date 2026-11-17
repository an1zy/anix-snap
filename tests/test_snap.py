import io
import shutil
import subprocess
from pathlib import Path

import pytest

import anix_snap as s


def test_parse_target():
    assert s.parse_target("api.py:10-40") == ("api.py", 10, 40)
    assert s.parse_target("api.py:7") == ("api.py", 7, 7)
    assert s.parse_target("api.py") == ("api.py", None, None)


def test_parse_target_windows():
    assert s.parse_target(r"C:\proj\api.py") == (r"C:\proj\api.py", None, None)
    assert s.parse_target(r"C:\proj\api.py:3-4") == (r"C:\proj\api.py", 3, 4)


def test_parse_hl():
    assert s.parse_hl("1,3-5") == {1, 3, 4, 5}
    assert s.parse_hl(None) == set()


@pytest.mark.parametrize("name", list(s.THEMES))
def test_render_all_themes(name):
    svg = s.render_svg("def f():\n    return 1\n", "python", s.THEMES[name], title="t.py")
    assert svg.lstrip().startswith("<svg") and "t.py" in svg


def test_custom_theme(tmp_path):
    f = tmp_path / "mine.json"
    f.write_text('{"bg": "#000000", "kw": "#ff0000"}', encoding="utf-8")
    pal = s.load_theme(str(f))
    assert pal["kw"] == "#ff0000" and pal["fg"] == s.THEMES["peach"]["fg"]


def test_unknown_theme():
    with pytest.raises(s.SnapError):
        s.load_theme("no-such-theme")


def test_clean_diff():
    text = "diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b"
    assert s.clean_diff(text).splitlines()[0] == "--- a/x"


def test_embed_fonts_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "cache_dir", lambda: tmp_path)
    svg = s.render_svg("x = 1", "python", s.THEMES["noir"], title="x")
    (tmp_path / "fonts").mkdir()
    for url in s.WOFF2.findall(svg):
        (tmp_path / "fonts" / url.rsplit("/", 1)[-1]).write_bytes(b"wOF2fake")
    out = s.embed_fonts(svg)
    assert "data:font/woff2;base64," in out and "cdnjs" not in out


def test_embed_fonts_redownloads_broken_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "cache_dir", lambda: tmp_path)
    svg = s.render_svg("x = 1", "python", s.THEMES["noir"], title="x")
    (tmp_path / "fonts").mkdir()
    for url in s.WOFF2.findall(svg):
        (tmp_path / "fonts" / url.rsplit("/", 1)[-1]).write_bytes(b"")  # broken half download
    calls = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=0):
        calls.append(url)
        return Resp(b"wOF2good")

    monkeypatch.setattr(s.urllib.request, "urlopen", fake_urlopen)
    out = s.embed_fonts(svg)
    assert calls and "cdnjs" not in out
    assert all(f.read_bytes() == b"wOF2good" for f in (tmp_path / "fonts").glob("*.woff2"))


def test_ranges_validated():
    assert s.make_range("40", "10") == (10, 40)
    for bad in (("0", "10"), ("0", None)):
        with pytest.raises(s.SnapError):
            s.make_range(*bad)
    with pytest.raises(s.SnapError):
        s.parse_target("api.py:0-3")


def test_hl_commas():
    assert s.parse_words(["+12,15-17", "-"])["hl"] == {12, 15, 16, 17}


def test_words_any_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("api.py").write_text("x = 1\n", encoding="utf-8")
    for words in (["api.py", "10-40", "neon", "+12", "png"], ["png", "+12", "neon", "10-40", "api.py"]):
        o = s.parse_words(words)
        assert (o["file"], o["start"], o["end"], o["theme"], o["hl"], o["fmt"]) == ("api.py", 10, 40, "neon", {12}, "png")
    assert s.parse_words(["NOIR", "api.py:3-5"])["start"] == 3


def test_language_before_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("api.py").write_text("x = 1\n", encoding="utf-8")
    o = s.parse_words(["python", "api.py"])
    assert o["file"] == "api.py" and o["lang"] == "python"
    Path("python").write_text("", encoding="utf-8")  # a file named like a language
    assert s.parse_words(["python", "api.py"])["lang"] == "python"


def test_stdin_language_any_order():
    for words in (["-", "rust"], ["rust", "-"]):
        o = s.parse_words(words)
        assert o["file"] == "-" and o["lang"] == "rust"


def test_keywords_win_over_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("themes", "diff", "neon"):
        Path(name).mkdir()
    Path("api.py").write_text("x = 1\n", encoding="utf-8")
    assert s.parse_words(["themes"])["mode"] == "themes"
    assert s.parse_words(["api.py", "neon"])["theme"] == "neon"
    assert s.parse_words(["./diff"])["file"] == "./diff"


def test_diff_keyword_anywhere():
    o = s.parse_words(["staged", "neon", "diff"])
    assert o["mode"] == "diff" and o["staged"] and o["theme"] == "neon"


def test_unknown_words():
    for words in (["kaka"], ["-", "kaka"]):
        with pytest.raises(s.SnapError, match="kaka"):
            s.parse_words(words)
    with pytest.raises(s.SnapError):
        s.parse_words(["diff", "themes"])


def test_stdin_lexer_guess():
    assert s.pick_lexer("stdin", "#!/usr/bin/env python\nprint(1)\n", None) == "python"
    assert s.pick_lexer("stdin", "x", "rust") == "rust"


def test_cli_words(tmp_path, capsys):
    src = tmp_path / "demo.py"
    src.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    out = tmp_path / "shot.svg"
    s.main([str(src), "2-3", "neon", "+2", "-o", str(out), "--no-copy", "--cdn-font", "--ui", "en"])
    assert out.exists() and "saved" in capsys.readouterr().out


def test_cli_help(capsys):
    s.main(["--ui", "en"])
    assert "asnap diff" in capsys.readouterr().out


def test_cli_errors(tmp_path):
    src = tmp_path / "demo.py"
    src.write_text("a = 1\n", encoding="utf-8")
    for extra in (["10"], ["0-3"], ["-o", str(tmp_path / "x.jpg")]):
        with pytest.raises(SystemExit):
            s.main([str(src), *extra, "--no-copy", "--cdn-font", "--ui", "en"])


git_only = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        subprocess.run(["git", *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    Path("x.py").write_text("a = 1\n", encoding="utf-8")
    Path("gone.py").write_text("b = 1\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "init")
    return git


@git_only
def test_cli_diff(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    Path("x.py").write_text("a = 2\n", encoding="utf-8")
    s.main(["x.py", "diff", "svg", "--no-copy", "--cdn-font", "--ui", "en"])
    assert "<svg" in Path("x.diff.snap.svg").read_text(encoding="utf-8")


@git_only
def test_diff_words_resolved_by_git(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    Path("gone.py").unlink()  # deleted file is still a path, not a branch
    o = s.parse_words(["diff", "gone.py", "HEAD"])
    assert o["paths"] == ["gone.py"] and o["revs"] == ["HEAD"]
    assert s.parse_words(["diff", "main"])["revs"] == ["main"]
    Path("main").write_text("", encoding="utf-8")  # a file named like the branch
    with pytest.raises(s.SnapError):
        s.parse_words(["diff", "main"])
    assert s.parse_words(["diff", "./main"])["paths"] == ["./main"]


def test_version_matches_pyproject():
    import re as _re
    text = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert _re.search(r'^version = "([^"]+)"', text, _re.M)[1] == s.__version__


def test_dotdot_path_is_not_a_rev(monkeypatch):
    monkeypatch.setattr(s, "_git", lambda *a: subprocess.CompletedProcess(a, 1, "", ""))
    assert not s.git_is_rev("../shared/api.py")
    assert not s.git_is_rev("..")


def test_stdin_without_pipe(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(s.sys, "stdin", Tty(""))
    with pytest.raises(s.SnapError):
        s.read_source("-")


@git_only
def test_diff_outside_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        s.main(["diff", "--no-copy", "--cdn-font", "--ui", "en"])


@git_only
def test_diff_ranges_and_parent_paths(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = _repo(repo, monkeypatch)
    git("checkout", "-qb", "feature/login")
    assert s.git_is_rev("main..feature/login") and s.git_is_rev("main...feature/login")
    assert s.git_is_rev("feature/login") and not s.git_is_rev("main..nope")
    (repo / "sub").mkdir()
    monkeypatch.chdir(repo / "sub")
    o = s.parse_words(["diff", "../x.py"])
    assert o["paths"] == ["../x.py"] and o["revs"] == []


def test_empty_inputs(tmp_path, monkeypatch):
    def run(*words):
        s.main([*words, "-o", str(tmp_path / "x.svg"), "--no-copy", "--cdn-font", "--ui", "en"])

    monkeypatch.setattr(s.sys, "stdin", io.StringIO("  \n\n"))  # grep found nothing
    with pytest.raises(SystemExit):
        run("-")
    empty = tmp_path / "empty.py"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(str(empty))
    blank = tmp_path / "blank.py"
    blank.write_text("a = 1\n\n\n\nb = 2\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run(str(blank), "2-4")
    assert not (tmp_path / "x.svg").exists()
    run(str(blank), "1-2")  # a range with some code is fine
    assert (tmp_path / "x.svg").exists()
