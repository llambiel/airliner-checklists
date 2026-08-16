#!/usr/bin/env python3
"""
build.py — compile checklists/*.yaml into the site.

Writes the FLEET data block inside app.html, the fleet list on index.html, one plain
HTML page per aircraft under types/, and robots.txt + sitemap.xml. Every page stays
self-contained, so the site still works from file:// and on any static host. The YAML
files are the source of truth; generated blocks and types/ should not be hand-edited.

    python3 build.py            regenerate every generated file
    python3 build.py --check    exit 1 if anything is out of date (for CI / hooks)

Uses PyYAML when it is installed, and falls back to a bundled parser for the small
YAML subset these files use, so the repo builds with a bare Python install.
"""

import json, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "checklists")
APP = os.path.join(ROOT, "app.html")     # the checklist tool
HOME = os.path.join(ROOT, "index.html")  # the homepage
TYPES = os.path.join(ROOT, "types")      # one plain page per aircraft, for search engines
BEGIN = "/* == GENERATED FROM checklists/*.yaml BY build.py — DO NOT EDIT BY HAND == */"
END = "/* == END GENERATED == */"
HOME_BEGIN = "<!-- == GENERATED FLEET LIST FROM checklists/*.yaml — DO NOT EDIT BY HAND == -->"
HOME_END = "<!-- == END GENERATED == -->"
LINKS_BEGIN = "<!-- == GENERATED SITE LINKS — DO NOT EDIT BY HAND == -->"
LINKS_END = "<!-- == END SITE LINKS == -->"

# The public address of the site. Search engines need one absolute, agreed URL
# per page, so this is the single place it is written down. Set it to "" and
# the canonical tags, robots.txt and sitemap.xml are simply left out.
SITE = "https://airlinerchecklists.com"

PAGES = [("index.html", "/"), ("app.html", "/app.html")]
TYPE_PATH = "/types/%s.html"   # one indexable URL per aircraft
RESERVED = ("note", "sub", "divider", "only")


# ---------------------------------------------------------------- YAML input
def _strip_comment(s):
    out, quote = [], None
    for i, ch in enumerate(s):
        if quote:
            out.append(ch)
            if ch == quote and s[i - 1 : i] != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(s):
    """Every plain scalar stays a string.

    A checklist response is always text, and YAML 1.1 would otherwise turn
    'APU: OFF' into the boolean False and print it as 'False' on the page.
    """
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        body = s[1:-1]
        return body.replace('\\"', '"').replace("\\\\", "\\") if s[0] == '"' else body
    return None if s in ("~", "") else s


def _split_key(s):
    """Split 'key: value' at the first colon outside quotes."""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote and s[i - 1 : i] != "\\":
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            return s[:i], s[i + 1 :]
    return None, None


def _parse(lines, i, indent):
    """Parse one block of (indent, text) lines. Returns (value, next_index)."""
    if lines[i][1].startswith("- "):
        seq = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            inner = [(indent + 2, lines[i][1][2:])]
            i += 1
            while i < len(lines) and lines[i][0] >= indent + 2:
                inner.append(lines[i])
                i += 1
            if len(inner) == 1 and _split_key(inner[0][1])[0] is None:
                seq.append(_scalar(inner[0][1]))  # plain scalar entry, e.g. a filename
            else:
                val, _ = _parse(inner, 0, indent + 2)
                seq.append(val)
        return seq, i
    mapping = {}
    while i < len(lines) and lines[i][0] == indent:
        key, rest = _split_key(lines[i][1])
        if key is None:
            raise ValueError("cannot parse line: " + lines[i][1])
        key = _scalar(key)
        i += 1
        if rest.strip():
            mapping[key] = _scalar(rest)
        elif i < len(lines) and lines[i][0] > indent:
            mapping[key], i = _parse(lines, i, lines[i][0])
        else:
            mapping[key] = None
    return mapping, i


def load_yaml(path):
    text = open(path, encoding="utf-8").read()
    try:
        import yaml  # PyYAML when available
    except ImportError:
        yaml = None
    if yaml is not None:
        class StrLoader(yaml.SafeLoader):
            pass
        StrLoader.yaml_implicit_resolvers = {}  # plain scalars stay strings, see _scalar
        try:
            return yaml.load(text, StrLoader)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            where = " line %d" % (mark.line + 1) if mark else ""
            raise Bad(
                "%s%s: %s\n  (a value containing ': ' must be quoted — \"Watch this: rotate slowly\")"
                % (os.path.basename(path), where, getattr(e, "problem", e))
            )
    lines = []
    for raw in text.splitlines():
        body = _strip_comment(raw)
        if body.strip():
            lines.append((len(body) - len(body.lstrip(" ")), body.strip()))
    if not lines:
        return None
    value, _ = _parse(lines, 0, lines[0][0])
    return value


# ---------------------------------------------------------------- validation
class Bad(Exception):
    pass


def item_of(raw, where, variants=None):
    if not isinstance(raw, dict):
        raise Bad("%s: item must be 'CHALLENGE: RESPONSE', got %r" % (where, raw))
    if "divider" in raw:
        return {"div": str(raw["divider"])}
    keys = [k for k in raw if k not in RESERVED]
    if len(keys) != 1:
        raise Bad(
            "%s: expected exactly one 'CHALLENGE: RESPONSE' pair (plus optional %s), got %s"
            % (where, "/".join(RESERVED), keys or "none")
        )
    c = keys[0]
    if raw[c] is None:
        raise Bad("%s: '%s' has no response" % (where, c))
    out = {"c": str(c), "r": str(raw[c])}
    if str(raw.get("sub") or "").lower() not in ("", "false", "no", "off", "0", "none"):
        out["sub"] = True
    if raw.get("note"):
        out["note"] = str(raw["note"])
    only = raw.get("only")
    if only:
        only = [str(v).strip() for v in (only if isinstance(only, list) else [only])]
        if variants is not None:
            unknown = [v for v in only if v not in variants]
            if unknown:
                raise Bad("%s: '%s' is limited to a variant that does not exist: %s (declared: %s)"
                          % (where, out["c"], ", ".join(unknown), ", ".join(variants) or "none"))
        out["only"] = only
    return out


def variants_of(doc, fn):
    """variants: a list of names, or of {name, note} mappings."""
    out = []
    for v in doc.get("variants") or []:
        if isinstance(v, dict):
            name = v.get("name")
            if not name:
                raise Bad("%s: a variant is missing its 'name'" % fn)
            entry = {"n": str(name)}
            if v.get("note"):
                entry["note"] = str(v["note"])
        else:
            entry = {"n": str(v)}
        out.append(entry)
    names = [v["n"] for v in out]
    if len(names) != len(set(names)):
        raise Bad("%s: duplicate variant name" % fn)
    return out


def aircraft_of(doc, fn):
    for k in ("id", "code", "name", "phases"):
        if not doc.get(k):
            raise Bad("%s: missing top-level '%s'" % (fn, k))
    variants = variants_of(doc, fn)
    variant_names = [v["n"] for v in variants]
    phases, seen = [], set()
    for p in doc["phases"]:
        for k in ("id", "name", "items"):
            if not p.get(k):
                raise Bad("%s: phase missing '%s'" % (fn, k))
        if p["id"] in seen:
            raise Bad("%s: duplicate phase id '%s'" % (fn, p["id"]))
        seen.add(p["id"])
        kind = p.get("kind", "checklist")
        if kind not in ("flow", "checklist"):
            raise Bad("%s/%s: kind must be 'flow' or 'checklist'" % (fn, p["id"]))
        items = [item_of(it, "%s/%s" % (fn, p["id"]), variant_names) for it in p["items"]]
        phases.append({"id": str(p["id"]), "name": str(p["name"]), "kind": kind, "items": items})
    out = {
        "id": str(doc["id"]),
        "code": str(doc["code"]),
        "name": str(doc["name"]),
        "sub": str(doc.get("sub") or ""),
        "mfr": str(doc.get("manufacturer") or "Other"),
    }
    if variants:
        out["vars"] = variants
    out["phases"] = phases
    return out


def read_fleet():
    manifest = os.path.join(SRC, "fleet.yaml")
    if os.path.exists(manifest):
        files = load_yaml(manifest) or []
    else:
        files = sorted(f for f in os.listdir(SRC) if f.endswith((".yaml", ".yml")))
    fleet, ids = [], set()
    for fn in files:
        path = os.path.join(SRC, fn)
        if not os.path.exists(path):
            raise Bad("fleet.yaml lists '%s', which does not exist" % fn)
        a = aircraft_of(load_yaml(path), fn)
        if a["id"] in ids:
            raise Bad("duplicate aircraft id '%s' (ids are the save-slot keys)" % a["id"])
        ids.add(a["id"])
        fleet.append(a)
    if not fleet:
        raise Bad("no checklists found in %s" % SRC)
    return fleet


# ---------------------------------------------------------------- JS output
def to_js(fleet):
    d = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    out = ["const FLEET = ["]
    for a in fleet:
        head = {k: a[k] for k in ("id", "code", "name", "sub", "mfr") if k in a}
        if "vars" in a:
            head["vars"] = a["vars"]
        out.append(d(head)[:-1] + ',"phases":[')
        for p in a["phases"]:
            out.append('{"id":%s,"name":%s,"kind":%s,"items":[' % (d(p["id"]), d(p["name"]), d(p["kind"])))
            out += ["  " + d(it) + "," for it in p["items"]]
            out.append("]},")
        out.append("]},")
    out.append("];")
    return "\n".join(out)


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_home_html(fleet):
    """The homepage fleet list, grouped by manufacturer in menu order."""
    groups = []
    for a in fleet:
        g = next((g for g in groups if g["mfr"] == a["mfr"]), None)
        if g is None:
            g = {"mfr": a["mfr"], "list": []}
            groups.append(g)
        g["list"].append(a)
    out = []
    for g in groups:
        out.append('<div class="mfr">')
        out.append("  <h3>%s</h3>" % _esc(g["mfr"]))
        out.append("  <ul>")
        for a in g["list"]:
            # The full name earns its place: it is what someone types into a search box.
            detail = [a["name"]] + [v["n"] for v in a.get("vars", [])]
            out.append(
                '    <li><a href="types/%s.html"><b>%s</b><span>%s</span></a></li>'
                % (a["id"], _esc(a["code"]), _esc(" · ".join(detail)))
            )
        out.append("  </ul>")
        out.append("</div>")
    return "\n".join(out)


# ------------------------------------------------------- one page per aircraft
# The tool keeps every type on one URL behind JavaScript, which gives a search
# engine a single page to weigh for forty aeroplanes. These are the plain HTML
# counterparts: one URL each, the whole checklist in the markup, linking into
# the interactive version.
TYPE_CSS = """
:root{
  --bg:#E8EAE7;--panel:#FBFCFA;--panel-2:#F1F3F0;--line:#CDD5D0;--ink:#16211C;
  --muted:#5E6B65;--green:#0E7A46;--cyan:#0F6076;
  --f-disp:"Roboto Condensed","Arial Narrow","Helvetica Neue",system-ui,sans-serif;
  --f-ui:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  --f-mono:ui-monospace,"SF Mono","Cascadia Mono","Roboto Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#080B0D;--panel:#10161A;--panel-2:#161E24;--line:#26333B;--ink:#DCE6EA;
  --muted:#7C8F99;--green:#3FD98A;--cyan:#5FC8E8;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-ui);font-size:16px;line-height:1.55}
a{color:inherit}
.wrap{max-width:920px;margin:0 auto;padding:0 22px}
.top{border-bottom:1px solid var(--line);background:var(--panel)}
.top .wrap{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding-top:13px;padding-bottom:13px}
.mark{font-family:var(--f-disp);font-weight:700;font-size:17px;letter-spacing:.14em;
  text-transform:uppercase;text-decoration:none}
.top .spacer{flex:1}
.cta{font-family:var(--f-disp);font-size:12px;letter-spacing:.14em;text-transform:uppercase;
  text-decoration:none;background:var(--green);color:var(--panel);padding:9px 15px;border-radius:3px}
h1{margin:34px 0 6px;font-family:var(--f-disp);font-weight:700;font-size:clamp(28px,4.6vw,42px);
  line-height:1.05;letter-spacing:.02em;text-transform:uppercase;text-wrap:balance}
.sub{margin:0 0 18px;color:var(--muted);font-size:15px}
.lede{margin:0 0 26px;max-width:64ch}
.vars{margin:0 0 30px;padding:0;list-style:none;display:grid;gap:8px}
.vars li{border-left:2px solid var(--cyan);padding:2px 0 2px 12px;font-size:14px;color:var(--muted)}
.vars b{font-family:var(--f-disp);letter-spacing:.08em;text-transform:uppercase;color:var(--ink)}
section.phase{background:var(--panel);border:1px solid var(--line);border-radius:4px;
  padding:16px 20px;margin:0 0 14px}
section.phase h2{margin:0 0 10px;font-family:var(--f-disp);font-size:16px;letter-spacing:.12em;
  text-transform:uppercase}
section.phase h2 em{font-style:normal;font-size:10px;letter-spacing:.16em;color:var(--muted);
  border:1px solid var(--line);border-radius:2px;padding:2px 7px;margin-left:9px;vertical-align:2px}
ol.items{list-style:none;margin:0;padding:0}
ol.items li{display:flex;align-items:baseline;gap:0;font-family:var(--f-mono);font-size:13.5px;
  padding:5px 0;border-bottom:1px solid var(--line)}
ol.items li:last-child{border-bottom:0}
ol.items li.sub{padding-left:22px}
ol.items li.divider{display:block;font-family:var(--f-disp);font-size:10px;letter-spacing:.2em;
  text-transform:uppercase;color:var(--muted);padding-top:12px}
.dots{flex:1 1 auto;min-width:14px;border-bottom:1px dotted var(--line);margin:0 8px;transform:translateY(-4px)}
.r{color:var(--cyan);text-align:right}
.tag{font-family:var(--f-disp);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--cyan);border:1px solid var(--cyan);border-radius:2px;padding:1px 5px;margin-left:8px}
p.note{margin:2px 0 8px;font-size:12.5px;color:var(--muted);max-width:64ch}
.also{margin:34px 0 0;padding-top:18px;border-top:1px solid var(--line)}
.also h2{font-family:var(--f-disp);font-size:12px;letter-spacing:.22em;text-transform:uppercase;
  color:var(--muted);margin:0 0 10px}
.also a{display:inline-block;font-family:var(--f-disp);font-size:12px;letter-spacing:.08em;
  text-transform:uppercase;text-decoration:none;border:1px solid var(--line);border-radius:2px;
  padding:5px 9px;margin:0 5px 6px 0;color:var(--muted)}
.also a:hover{color:var(--ink);border-color:var(--muted)}
footer{margin:30px 0 40px;padding-top:16px;border-top:1px solid var(--line);
  font-size:12.5px;color:var(--muted);max-width:72ch}
footer b{color:var(--green);font-family:var(--f-disp);letter-spacing:.1em;text-transform:uppercase}
"""


def type_meta(a):
    """Title and description — unique per page, and worded the way people search."""
    phases = len(a["phases"])
    items = sum(1 for p in a["phases"] for it in p["items"] if "div" not in it)
    title = "%s checklist · Flight Deck" % a["name"]
    desc = ("%s checklist for flight simulation — %s. %d phases and %d items, "
            "from cockpit preparation to securing the aircraft, split into flows "
            "flown from memory and read-and-respond checklists."
            % (a["name"], a["sub"], phases, items))
    return title, desc


def type_page(a, fleet):
    t, desc = type_meta(a)
    url = (SITE.rstrip("/") + TYPE_PATH % a["id"]) if SITE else ""
    o = ["<!doctype html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
         "<title>%s</title>" % _esc(t),
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<meta name="description" content="%s">' % _esc(desc),
         '<meta name="color-scheme" content="light dark">',
         '<meta property="og:type" content="article">',
         '<meta property="og:title" content="%s">' % _esc(t),
         '<meta property="og:description" content="%s">' % _esc(desc),
         '<meta name="twitter:card" content="summary">']
    if url:
        o += ['<link rel="canonical" href="%s">' % url,
              '<meta property="og:url" content="%s">' % url]
        ld = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": t,
            "url": url,
            "description": desc,
            "about": {"@type": "Product", "name": a["name"], "category": "Aircraft"},
            "isPartOf": {"@type": "WebSite", "name": "Flight Deck Checklists",
                         "url": SITE.rstrip("/") + "/"},
        }
        o.append('<script type="application/ld+json">%s</script>'
                 % json.dumps(ld, ensure_ascii=False, separators=(",", ":")))
    o += ["<style>%s</style>" % TYPE_CSS, "</head>", "<body>",
          '<div class="top"><div class="wrap">',
          '  <a class="mark" href="../index.html">Flight Deck</a>',
          '  <span class="spacer"></span>',
          '  <a class="cta" href="../app.html#%s">Open the interactive checklist →</a>' % a["id"],
          "</div></div>",
          '<div class="wrap">',
          "<h1>%s checklist</h1>" % _esc(a["name"]),
          '<p class="sub">%s</p>' % _esc(a["sub"]),
          '<p class="lede">Every phase for the %s, as flown in a flight simulator — panel scans '
          'marked as flows, read-and-respond cards marked as checklists. '
          '<a href="../app.html#%s">Open the interactive version</a> to tick lines off, fill in your '
          'speeds and keep your place between sessions.</p>' % (_esc(a["name"]), a["id"])]

    if a.get("vars"):
        o.append('<ul class="vars">')
        for v in a["vars"]:
            note = " — " + _esc(v["note"]) if v.get("note") else ""
            o.append("  <li><b>%s</b>%s</li>" % (_esc(v["n"]), note))
        o.append("</ul>")

    for p in a["phases"]:
        kind = "Flow · from memory" if p["kind"] == "flow" else "Checklist · read &amp; respond"
        o.append('<section class="phase"><h2>%s <em>%s</em></h2><ol class="items">'
                 % (_esc(p["name"]), kind))
        for it in p["items"]:
            if "div" in it:
                o.append('  <li class="divider">%s</li>' % _esc(it["div"]))
                continue
            tag = ('<span class="tag">%s</span>' % _esc(" / ".join(it["only"]))) if it.get("only") else ""
            o.append('  <li%s><span>%s%s</span><span class="dots"></span><span class="r">%s</span></li>'
                     % (' class="sub"' if it.get("sub") else "", _esc(it["c"]), tag, _esc(it["r"])))
            if it.get("note"):
                o.append('  <p class="note">%s</p>' % _esc(it["note"]))
        o.append("</ol></section>")

    others = [x for x in fleet if x["id"] != a["id"]]
    o.append('<div class="also"><h2>Other types</h2>')
    o += ['  <a href="%s.html">%s</a>' % (x["id"], _esc(x["code"])) for x in others]
    o.append("</div>")
    o += ["<footer><b>Simulation use only.</b> Condensed for flight simulation and "
          "<em>not</em> for real-world flight. Sequences and values vary by operator, engine option "
          "and add-on model — cross-check against the aircraft's own FCOM or the add-on developer's "
          "documentation.</footer>",
          "</div>", "</body>", "</html>", ""]
    return "\n".join(o)


def _splice_text(page, begin, end, body, what):
    if begin not in page or end not in page:
        raise Bad("%s is missing the generated-block markers (%s)" % (what, begin[:40]))
    head, rest = page.split(begin, 1)
    _, tail = rest.split(end, 1)
    joiner = "\n" + body + "\n" if body else "\n"
    return head + begin + joiner + end + tail


def _splice(path, begin, end, body, what):
    return _splice_text(open(path, encoding="utf-8").read(), begin, end, body, what)


def site_links(path):
    """Canonical + og:url for one page, and the site's structured data on the homepage."""
    if not SITE:
        return ""
    url = SITE.rstrip("/") + path
    out = ['<link rel="canonical" href="%s">' % url,
           '<meta property="og:url" content="%s">' % url]
    if path == "/":
        ld = {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": "Flight Deck Checklists",
            "url": url,
            "applicationCategory": "GameApplication",
            "operatingSystem": "Any modern browser",
            "browserRequirements": "Requires JavaScript",
            "description": "Interactive challenge-and-response checklists for flight simulation, "
                           "covering airliners, regional turboprops and business jets.",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        }
        out.append('<script type="application/ld+json">%s</script>'
                   % json.dumps(ld, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(out)


def robots_txt():
    lines = ["User-agent: *", "Allow: /", ""]
    if SITE:
        lines += ["Sitemap: %s/sitemap.xml" % SITE.rstrip("/"), ""]
    return "\n".join(lines)


def sitemap_xml(fleet):
    # No lastmod on purpose: it would change on every build and make --check fail
    # a day after the last edit.
    paths = [p for _, p in PAGES] + [TYPE_PATH % a["id"] for a in fleet]
    prio = lambda p: "1.0" if p == "/" else ("0.8" if p == "/app.html" else "0.7")
    urls = "".join(
        "  <url><loc>%s%s</loc><priority>%s</priority></url>\n"
        % (SITE.rstrip("/"), path, prio(path))
        for path in paths
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            "%s</urlset>\n" % urls)


def render(fleet):
    """Every generated file, as {path: new contents}."""
    out = {}
    app = _splice(APP, BEGIN, END, to_js(fleet), "app.html")
    out[APP] = _splice_text(app, LINKS_BEGIN, LINKS_END, site_links("/app.html"), "app.html")
    if os.path.exists(HOME):
        home = _splice(HOME, HOME_BEGIN, HOME_END, to_home_html(fleet), "index.html")
        out[HOME] = _splice_text(home, LINKS_BEGIN, LINKS_END, site_links("/"), "index.html")
    for a in fleet:
        out[os.path.join(TYPES, a["id"] + ".html")] = type_page(a, fleet)
    out[os.path.join(ROOT, "robots.txt")] = robots_txt()
    if SITE:
        out[os.path.join(ROOT, "sitemap.xml")] = sitemap_xml(fleet)
    return out


def orphans(new):
    """Type pages left behind by an aircraft that has since been dropped."""
    if not os.path.isdir(TYPES):
        return []
    return sorted(os.path.join(TYPES, f) for f in os.listdir(TYPES)
                  if f.endswith(".html") and os.path.join(TYPES, f) not in new)


def main():
    check = "--check" in sys.argv
    try:
        fleet = read_fleet()
        new = render(fleet)
    except Bad as e:
        print("build error: %s" % e, file=sys.stderr)
        return 2
    phases = sum(len(a["phases"]) for a in fleet)
    items = sum(1 for a in fleet for p in a["phases"] for it in p["items"] if "div" not in it)
    summary = "%d aircraft · %d phases · %d items" % (len(fleet), phases, items)
    def current(p):
        return open(p, encoding="utf-8").read() if os.path.exists(p) else None

    stale = [p for p, body in sorted(new.items()) if current(p) != body]
    gone = orphans(new)
    if check:
        if stale or gone:
            print("out of date, run: python3 build.py — %s"
                  % ", ".join(os.path.basename(p) for p in stale + gone), file=sys.stderr)
            return 1
        print("up to date (%s)" % summary)
        return 0
    for p in gone:
        os.remove(p)
        print("  removed %s (no longer in the fleet)" % os.path.relpath(p, ROOT))
    if not stale:
        print("no change (%s)" % summary)
        return 0
    for a in fleet:
        print("  %-9s %2d phases %4d items" % (a["code"], len(a["phases"]),
              sum(1 for p in a["phases"] for it in p["items"] if "div" not in it)))
    for p in stale:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        open(p, "w", encoding="utf-8").write(new[p])
    named = [os.path.basename(p) for p in stale if os.path.dirname(p) == ROOT]
    npages = len(stale) - len(named)
    if npages:
        named.append("%d type page%s" % (npages, "" if npages == 1 else "s"))
    print("wrote %s — %s" % (", ".join(named), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
