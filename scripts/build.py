#!/usr/bin/env python3
"""Generate site/ from the raw store (Teleport Pro capture of the 1997 CITEWEB site).

    python3 -I scripts/build.py [--raw ~/Code/Citeweb/raw] [--out site]

Read-only on the raw store. Deterministic: the output only depends on the inputs.
Everything is lowercased, `.htm` becomes `.html`, `tppabs` attributes are dropped, links are
rewritten to root-absolute paths of the published tree, links that cannot be followed become
plain text, forms are frozen, e-mail addresses are masked.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from posixpath import normpath, join as pjoin, dirname
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parent.parent
ENC = "iso-8859-1"
OJ = "https://orangejuice97.sauthier.family/"

# ---------------------------------------------------------------- sources
# (raw sub-folder, virtual prefix, later sources do not overwrite earlier ones)
MAIN = "Citeweb/Capture/WWW.CITEWEB.NET"
SOURCES = [
    # fuller DefCoN capture first: it wins over the 1997 capture's DEFCON folder
    ("captures/Defcon/www.citeweb.net", ""),
    (MAIN, ""),
    ("Citeweb/Autres/citemag", "citemag/"),
]
# top-level folders of the 1997 capture that are not published
DROP_DIRS = {
    "cgi",  # counter digits, dll error page
    "ojuice",  # replaced by a link page (OrangeJuice97 is its own site)
    # empty "site de membre" stubs
    "bomb", "miko", "pydo", "nekzone", "franck", "fusion", "realteam", "tonicity", "citemag",
}
DROP_FILES = {
    "tppmsgs/msgs0.htm",
    "citeweb/index.ctw.htm",  # alias of the home page (same page, other ad)
    "citeweb/index-1.htm",  # older text-only version of the home page
    "news/serveur/compteur/index.ctw.htm",  # counter styles page: counters are not kept
    "news/serveur/compteur/example2.gif",
    "defcon/frames01.htm",  # frameset whose frames were never captured
}
# engine / binary / source files never published
DROP_EXT = (".psd", ".dll", ".exe", ".bat", ".asp", ".inc", ".cgi")
# link targets (virtual paths, lowercase, as written in the pages) that mean something else
ALIASES = {
    "citeweb/index.ctw.htm": "citeweb/index.htm",
    "citeweb/index-1.htm": "citeweb/index.htm",
    "citeweb": "citeweb/index.htm",
    "defcon/images/essai3.gif": "defcon/dessins/essai3.gif",
    "membres/membres.htm": "membres/index.htm",
    "news/serveur/index.ctw.htm": "news/serveur/index.htm",
}

NOTE_DEPT = " (not part of this archive)"
# The removal footer goes only on pages that show a family name, a full postal address or an
# e-mail with its local part in clear (local＠???? counts); never on pages with nicks only.
POSTAL_PAGES = {"citeweb/contact.htm", "citeweb/contact.ctw.htm"}  # street address of the host company
FAMILY_NAMES = re.compile(r"(?i)\b(?:retif|sauthier)\b")  # names written in running text
EMAIL_CLEAR = re.compile(r"(?<![?])[A-Za-z0-9_.-]&#65312;\?\?\?\?")
MEMBER_ENTRY = re.compile(r'(?is)liste des membres.*bgcolor="#C0C0C0"')  # real names in member lists

REMOVAL_NOTE = (
    '<div id="removal-note" style="clear:both;margin:28px auto 8px;padding:6px 8px 0;width:60%;'
    'border-top:1px solid #808080;text-align:center;font:10px/14px Verdana,Arial,Helvetica,sans-serif;'
    'color:#808080;background:transparent">To be removed from this page, '
    '<a href="mailto:chandra_oj@pm.me" style="color:#808080;text-decoration:underline">contact me</a>.</div>'
)
FORM_BANNER = (
    '<div id="archive-note" style="margin:0 0 12px;padding:6px 8px;border:1px solid #808080;'
    'background:#f0f0f0;color:#404040;text-align:center;font:11px/15px Verdana,Arial,Helvetica,sans-serif">'
    "Archive of CITEWEB (1997): this form is frozen and does nothing.</div>"
)
HOME_NOTE = (
    '<div id="archive-note" style="margin:20px auto 8px;padding:6px 8px 0;width:500px;'
    'border-top:1px solid #808080;text-align:center;font:11px/15px Verdana,Arial,Helvetica,sans-serif;'
    'color:#606060">Archive of CITEWEB, the free web host of 1996-1999, as it was in 1997. Read-only: '
    "forms, logins and counters no longer work. Full list of the old sites: "
    '<a href="https://chanoj.github.io/" style="color:#606060">chanoj.github.io</a>.</div>'
)
NOT_FOUND = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
<title>CITEWEB - page not found</title>
</head>
<body bgcolor="#FFFFFF" link="#004080" vlink="#004080">
<div align="center"><table border="0" width="500"><tr><td>
<p><font face="Verdana" size="4"><strong>Page not found</strong></font></p>
<p><font face="Verdana" size="2">This page is not part of the archive of CITEWEB (1997).
<a href="/">Back to the home page</a>.</font></p>
</td></tr></table></div>
</body>
</html>
"""
OJUICE_PAGE = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
<title>ORANGE JUICE - the magazine of the demoscene</title>
</head>
<body bgcolor="#FFFFFF" link="#004080" vlink="#004080">
<div align="center"><table border="0" width="500"><tr><td>
<p><font face="Verdana" size="5"><strong>ORANGE JUICE</strong></font></p>
<p><font face="Verdana" size="2">Orange Juice was the electronic magazine about the demoscene hosted
on CITEWEB in 1997. It is online as an archive of its own:</font></p>
<p><font face="Verdana" size="3"><a href="%(oj)s"><strong>%(oj)s</strong></a></font></p>
<p><font face="Verdana" size="2"><a href="/">&lt; back to CITEWEB</a></font></p>
</td></tr></table></div>
</body>
</html>
"""

TAG_A = re.compile(r"(?is)<a\b[^>]*>|</a\s*>")
TAG_AREA = re.compile(r"(?is)<area\b[^>]*>")
TAG_IMG = re.compile(r"(?is)<img\b[^>]*>")
TAG_FRAME = re.compile(r"(?is)<(?:frame|iframe|input)\b[^>]*>")
TPPABS = re.compile(r"""(?is)\s+tppabs\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
ATTR = lambda name: re.compile(r"""(?is)(\s%s\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s>]+))""" % name)
HREF, SRC, BACKGROUND = ATTR("href"), ATTR("src"), ATTR("background")
EMAIL = re.compile(r"(?i)\b([A-Za-z0-9._+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
PHONE = re.compile(r"\b(0\d)(?:[. ]\d\d){4}(?:[. ]\d\d)?\b")
STATS_HOST = re.compile(r"(<TD><B> </B><BR>)[A-Za-z0-9.-]+ </TD>")
AGE_TOWN = re.compile(r"(?is)<em>\s*(?:<strong>)?\s*\d{1,3}\s*ans\s*-\s*[^<]*(?:</strong>)?\s*</em>")
AGE_TOWN_B = re.compile(r"(?is)\d{1,3}\s*ans\s*-\s*\d{5}[^<]*")


def rd(p):
    return Path(p).read_bytes().decode(ENC)


def wr(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode(ENC, "xmlcharrefreplace"))


def attr_value(m):
    return next(g for g in m.groups()[1:] if g is not None)


def dest_name(v):
    """Virtual path (lowercase) -> published path."""
    if v.endswith(".htm"):
        return v + "l"
    return v


class Site:
    def __init__(self, raw):
        self.raw = Path(raw).expanduser()
        self.files = {}  # virtual path (lowercase) -> source Path
        self.dest = {}  # virtual path -> published path
        for sub, prefix in SOURCES:
            root = self.raw / sub
            for r, ds, fs in os.walk(root):
                ds.sort()
                for f in sorted(fs):
                    p = Path(r, f)
                    rel = prefix + p.relative_to(root).as_posix().lower()
                    if f == ".DS_Store" or rel.endswith(DROP_EXT) or rel in DROP_FILES:
                        continue
                    if rel.split("/", 1)[0] in DROP_DIRS and not prefix:
                        continue
                    if rel.startswith("membres/mdep") or re.match(r"news/[^/]+/mdep", rel):
                        continue  # lists by département: not published
                    if rel in self.files:
                        # same virtual name in two captures: the 1997 DEFCON files keep a suffix
                        if rel.startswith("defcon/") and rel.endswith((".htm", ".html")):
                            stem, ext = rel.rsplit(".", 1)
                            rel = stem + "-1997." + ext
                            if rel in self.files:
                                continue
                        else:
                            continue
                    self.files[rel] = p
        for rel, p in self.files.items():
            if p.suffix.lower() in (".htm", ".html") and re.fullmatch(r"(?is).*CTW Script: erreur interne.*", self._plain(p)):
                self.dead = getattr(self, "dead", set()) | {rel}
        self.dead = getattr(self, "dead", set())
        for rel in self.dead:
            del self.files[rel]
        # home page and ojuice stub
        for rel in self.files:
            self.dest[rel] = "index.html" if rel == "citeweb/index.htm" else dest_name(rel)
        self.dest["ojuice/index.htm"] = "ojuice/index.html"
        self.unresolved = {}

    @staticmethod
    def _plain(p):
        t = rd(p)
        t = re.sub(r"(?s)<[^>]+>", " ", t)
        t = re.sub(r"\s+", " ", t)
        return t if len(t) < 300 else ""

    # ---- link resolution
    def lookup(self, v):
        """Virtual path -> published URL or None."""
        v = v.lower()
        v = ALIASES.get(v, v)
        if v.startswith("ojuice"):
            return "/ojuice/"
        cands = [v]
        if v == "" or v.endswith("/") or "." not in v.rsplit("/", 1)[-1]:
            base = v.rstrip("/")
            pre = base + "/" if base else ""
            cands = [pre + "index.htm", pre + "index.html", base] if base else ["index.htm"]
        for c in cands:
            c = ALIASES.get(c, c)
            if c in self.dest:
                u = "/" + self.dest[c]
                if u.endswith("/index.html"):
                    u = u[: -len("index.html")]
                return u
        return None

    def resolve(self, page, href, tppabs):
        """Returns ('url', published URL) | ('mail', None) | ('drop', None)."""
        href = href.strip()
        low = href.lower()
        if low.startswith("mailto:"):
            return "mail", None
        if low.startswith(("javascript:", "#", "data:")):
            return ("keep", href) if low.startswith("#") else ("drop", None)
        frag = ""
        if "#" in href and not re.search(r"tppmsgs", low):
            href, _, frag = href.partition("#")
            frag = "#" + frag
        if "tppmsgs" in low or low.startswith(("http:", "https:", "ftp:", "news:", "irc:", "//")):
            u = urlsplit(tppabs if tppabs else href)
            if "tppmsgs" in low and not tppabs:
                return "drop", None
            host = (u.hostname or "").lower()
            if host in ("www.citeweb.net", "citeweb.net", "www.citeweb.com"):
                path = unquote(u.path).strip("/").lower()
                if path.startswith(("cgi/", "cgi-bin", "_vti")):
                    return "drop", None
                r = self.lookup(path)
                return ("url", r + frag) if r else ("drop", None)
            if host.endswith("orangejuice97.sauthier.family"):
                return "url", href
            if "orange" in host or path_is_oj(u):
                return "url", OJ
            return "drop", None
        path = unquote(href.split("?", 1)[0])
        if path == "":
            return "drop", None
        base = dirname(page)
        v = normpath(pjoin(base, path)) if not path.startswith("/") else normpath(path.lstrip("/"))
        if path.endswith("/") and not v.endswith("/"):
            v += "/"
        v = v.lower()
        if v.startswith(".."):
            return "drop", None
        if v == ".":
            v = ""
        r = self.lookup(v)
        if r is None and tppabs:
            u = urlsplit(tppabs)
            if (u.hostname or "").lower() in ("www.citeweb.net", "citeweb.net"):
                r = self.lookup(unquote(u.path).strip("/").lower())
        if r is None:
            self.unresolved.setdefault(v, set()).add(page)
            return "drop", None
        return "url", r + frag

    # ---- page rewrite
    def rewrite(self, rel, text):
        # ImageMap targets from the FrontPage comments, to fix the unresolved tppmsgs areas
        webbot = {}
        for m in re.finditer(r'(?is)<!--webbot\s+bot="ImageMap"(.*?)startspan', text):
            for r in re.finditer(r"rectangle=\"\s*\((\d+),(\d+)\)\s*\((\d+),\s*(\d+)\)\s*([^\"\s]+)", m.group(1)):
                webbot[tuple(int(x) for x in r.groups()[:4])] = r.group(5)

        def anchor_attrs(tag):
            tp = TPPABS.search(tag)
            tppabs = next((g for g in tp.groups() if g), "") if tp else ""
            return TPPABS.sub("", tag), tppabs

        # <area>
        def area(m):
            tag, tppabs = anchor_attrs(m.group(0))
            h = HREF.search(tag)
            if not h:
                return tag
            href = attr_value(h)
            kind, val = self.resolve(rel, href, tppabs)
            if kind == "drop" and "tppmsgs" in href.lower():
                c = re.search(r'(?i)coords\s*=\s*"?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)', tag)
                if c:
                    target = webbot.get(tuple(int(x) for x in c.groups()))
                    if target:
                        kind, val = self.resolve(rel, target, "")
            if kind in ("url", "keep"):
                return HREF.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1)
            return ""  # dead area

        text = TAG_AREA.sub(area, text)

        # <a> ... </a>
        out, pos, unwrap = [], 0, []
        for m in TAG_A.finditer(text):
            out.append(text[pos:m.start()])
            pos = m.end()
            tag = m.group(0)
            if tag.startswith("</"):
                out.append("" if unwrap and unwrap.pop() else "</a>")
                continue
            tag, tppabs = anchor_attrs(tag)
            h = HREF.search(tag)
            if not h:
                out.append(tag)
                unwrap.append(False)
                continue
            kind, val = self.resolve(rel, attr_value(h), tppabs)
            if kind in ("url", "keep"):
                out.append(HREF.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1))
                out[-1] = re.sub(r"(?i)\s+target\s*=\s*(?:\"_top\"|_top)", "", out[-1])
                unwrap.append(False)
            else:
                out.append("")
                unwrap.append(True)
        out.append(text[pos:])
        text = "".join(out)

        # <img>, <frame>, background=
        def media(m):
            tag, tppabs = anchor_attrs(m.group(0))
            tag = re.sub(r"(?i)\s+ismap\b", "", tag)
            for rx in (SRC, BACKGROUND):
                h = rx.search(tag)
                if not h:
                    continue
                kind, val = self.resolve(rel, attr_value(h), tppabs)
                if kind == "url":
                    tag = rx.sub(lambda mm: '%s"%s"' % (mm.group(1), val), tag, count=1)
                else:
                    if rx is SRC and tag.lower().startswith("<img"):
                        return ""  # counter, dead third party
                    tag = rx.sub("", tag, count=1)
            return tag

        text = TAG_IMG.sub(media, text)
        text = TAG_FRAME.sub(media, text)

        def body_bg(m):
            tag, tppabs = anchor_attrs(m.group(0))
            h = BACKGROUND.search(tag)
            if h:
                kind, val = self.resolve(rel, attr_value(h), tppabs)
                tag = BACKGROUND.sub(lambda mm: '%s"%s"' % (mm.group(1), val) if kind == "url" else "", tag, count=1)
            return tag

        text = re.sub(r"(?is)<body\b[^>]*>", body_bg, text)
        text = TPPABS.sub("", text)
        # leftover <a ...> of unwrapped anchors can leave empty font wrappers: harmless
        return text

    def sanitize(self, rel, text):
        # meta refresh to a dead host (AUTOMAG) and its link
        if rel.startswith("automag/") and re.search(r"(?i)http-equiv\s*=\s*\"?refresh", text):
            text = re.sub(r"(?is)<meta[^>]+refresh[^>]*>", "", text)
            text = re.sub(r"(?is)<body[^>]*>.*</body>", (
                '<body bgcolor="#FFFFFF"><p><font face="Verdana" size="2">AUTOMAG was a member site of '
                "CITEWEB. This page used to redirect to a site on mygale.org that no longer exists."
                '</font></p><p><font face="Verdana" size="2"><a href="/">&lt; back to CITEWEB</a></font></p></body>'),
                text, count=1)
        # applets (live chat): note
        text = re.sub(r"(?is)<applet\b.*?</applet\s*>",
                      '<p><font face="Verdana" size="2"><em>(The live chat applet is not part of this archive.)</em></font></p>', text)
        # scripts loading remote code: none expected; keep inline scripts as they are
        # member data: age and town, passwords never present
        text = AGE_TOWN.sub("", text)
        text = AGE_TOWN_B.sub("", text)
        # forms frozen
        had_form = bool(re.search(r"(?i)<form\b", text))
        if had_form:
            text = re.sub(r"(?is)<form\b[^>]*>", '<div class="frozen-form">', text)
            text = re.sub(r"(?is)</form\s*>", "</div>", text)
            text = re.sub(r"(?is)<input\b[^>]*type\s*=\s*\"?hidden\"?[^>]*>", "", text)
            text = re.sub(r"(?is)<(input|select|textarea)\b", r"<\1 disabled", text)
            text = re.sub(r"(?i)(<input\b[^>]*?)\s+value\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", r"\1", text)
            text = re.sub(r"(?is)(<body\b[^>]*>)", lambda m: m.group(1) + FORM_BANNER, text, count=1)
        # e-mails: mailto links removed by the link pass (kept as text), addresses masked
        text = re.sub(r"(?is)<a\b[^>]*href\s*=\s*\"?mailto:[^>]*>(.*?)</a\s*>", r"\1", text)
        if rel.startswith("automag/"):  # private classified ads: the whole address goes
            text = EMAIL.sub("????&#65312;????", text)
        text = EMAIL.sub(lambda m: m.group(1) + "&#65312;????", text)
        # phone numbers (private ads, the old publicity contact): masked
        text = PHONE.sub(lambda m: m.group(1) + ".??.??.??.??", text)
        # visitor host names of the WebTrends reports
        if rel.startswith("stats/"):
            text = STATS_HOST.sub(r"\1(host hidden) </TD>", text)
            text = text.replace("204.245.240.194", "xxx.xxx.xxx.xxx")  # example IP of the WebTrends glossary
        # charset
        if not re.search(r"(?i)charset\s*=", text):
            if re.search(r"(?i)<head[^>]*>", text):
                text = re.sub(r"(?i)(<head[^>]*>)", r'\1<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">', text, count=1)
            else:
                text = '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">\n' + text
        # footers
        add_removal = bool(rel in POSTAL_PAGES or EMAIL_CLEAR.search(text) or FAMILY_NAMES.search(text)
                           or MEMBER_ENTRY.search(text))
        if add_removal:
            text = self._append(text, REMOVAL_NOTE)
        if rel == "citeweb/index.htm":
            text = self._append(text, HOME_NOTE)
        return text

    @staticmethod
    def _append(text, note):
        m = re.search(r"(?is)</body\s*>(?!.*</body\s*>)", text)
        if m:
            return text[: m.start()] + note + "\n" + text[m.start():]
        return text + "\n" + note + "\n"

    def run(self, out):
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for rel in sorted(self.files):
            p = self.files[rel]
            d = out / self.dest[rel]
            if rel.endswith((".htm", ".html")):
                text = rd(p)
                text = self.rewrite(rel, text)
                text = self.sanitize(rel, text)
                wr(d, text)
            else:
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, d)
        wr(out / "ojuice/index.html", OJUICE_PAGE % {"oj": OJ})
        wr(out / "404.html", NOT_FOUND)
        return len(self.files) + 2


def path_is_oj(u):
    return "ojuice" in (u.path or "").lower() and (u.hostname or "").lower().endswith("citeweb.net")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raw", default=os.environ.get("CITEWEB_RAW", "~/Code/Citeweb/raw"))
    ap.add_argument("--out", default=str(REPO / "site"))
    a = ap.parse_args(argv)
    s = Site(a.raw)
    n = s.run(Path(a.out))
    print("build: %d files in %s" % (n, a.out))
    un = {k: sorted(v)[:2] for k, v in sorted(s.unresolved.items())}
    print("unresolved link targets (made plain text): %d" % len(un))
    for k, v in list(un.items())[:80]:
        print("   ", k, "<-", v)


if __name__ == "__main__":
    sys.exit(main())
