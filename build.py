#!/usr/bin/env python3
"""
build.py — compile checklists/*.yaml into the FLEET data block inside index.html.

The site stays a single self-contained file, so it still works from file:// and on
any static host. The YAML files are the source of truth; index.html's data block is
generated and should not be hand-edited.

    python3 build.py            regenerate index.html
    python3 build.py --check    exit 1 if index.html is out of date (for CI / hooks)

Uses PyYAML when it is installed, and falls back to a bundled parser for the small
YAML subset these files use, so the repo builds with a bare Python install.
"""

import json, os, re, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "checklists")
APP = os.path.join(ROOT, "app.html")     # the checklist tool
HOME = os.path.join(ROOT, "index.html")  # the homepage
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
                '    <li><b>%s</b><span>%s</span></li>'
                % (_esc(a["code"]), _esc(" · ".join(detail)))
            )
        out.append("  </ul>")
        out.append("</div>")
    return "\n".join(out)


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


def sitemap_xml():
    # No lastmod on purpose: it would change on every build and make --check fail
    # a day after the last edit.
    urls = "".join(
        "  <url><loc>%s%s</loc><priority>%s</priority></url>\n"
        % (SITE.rstrip("/"), path, "1.0" if path == "/" else "0.8")
        for _, path in PAGES
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
    out[os.path.join(ROOT, "robots.txt")] = robots_txt()
    if SITE:
        out[os.path.join(ROOT, "sitemap.xml")] = sitemap_xml()
    return out


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
    if check:
        if stale:
            print("out of date, run: python3 build.py — %s"
                  % ", ".join(os.path.basename(p) for p in stale), file=sys.stderr)
            return 1
        print("up to date (%s)" % summary)
        return 0
    if not stale:
        print("no change (%s)" % summary)
        return 0
    for a in fleet:
        print("  %-9s %2d phases %4d items" % (a["code"], len(a["phases"]),
              sum(1 for p in a["phases"] for it in p["items"] if "div" not in it)))
    for p in stale:
        open(p, "w", encoding="utf-8").write(new[p])
    print("wrote %s — %s" % (", ".join(os.path.basename(p) for p in stale), summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
