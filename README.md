# Flight Deck Checklists

Hosted at **airlinerchecklists.com** · source at
[github.com/llambiel/airliner-checklists](https://github.com/llambiel/airliner-checklists)

Interactive checklists for flight simulation — airliners first, plus regional turboprops, business jets
and transports.
Two static HTML files — a homepage and the checklist tool: no server needed to use them, no
dependencies, no tracking. Progress lives in `localStorage`.

Checklist content is written in YAML (`checklists/*.yaml`) and compiled into both pages by `build.py`.

> **Disclaimer — this project is vibe coded.** It was written in a conversational back-and-forth with
> an LLM rather than by a type-rated pilot with the FCOMs open. It is a study aid for a flight simulator.
> Do not use it for real-world flight, real-world training, or anything where being wrong matters.
> See [Accuracy](#accuracy).

## Fleet

**Airbus** — A220 · A300-600 · A310 · A318 · A319 · A320 · A321 · A320neo · A330ceo · A330neo ·
A340 · A350 · A380 · A400M Atlas

**Boeing** — 707 · 727 · 737 NG · 737 MAX · 757 · 767 · 777 · 747-400 · 747-8 · 787

**McDonnell Douglas** — MD-80 · MD-10 · MD-11

**Lockheed** — L-1011 TriStar

**Embraer** — E-Jets (E170 / E175 / E190 / E195)

**Fokker** — 70 / 100

**Bombardier** — CRJ700 / 900 / 1000 · Challenger 604 / 605 / 650

**De Havilland Canada** — Dash 8 Q400

**ATR** — 42 / 72

**Gulfstream** — G650 / G650ER

**Dassault** — Falcon 50 / 50EX

**Pilatus** — PC-12 · PC-24

**Daher** — TBM 900 / 930 / 940 / 960

Variants that share a cockpit share a checklist — they appear as selectable chips that carry the
differences worth knowing. Where the flight deck genuinely differs (737 NG vs MAX, 747-400 vs -8,
A330 ceo vs neo) they are separate types with their own files. The A320 family is split by fuselage
even though it shares a type rating, because that is how people pick an aeroplane in a simulator.

## Run it

Open `index.html` for the homepage, or `app.html` to go straight to the checklists. Both work
from `file://`.

Served over HTTP each aeroplane has its own address — `/checklist/a320ceo`, or
`/checklist/a320ceo/taxi` for a phase — which the app writes as you switch types and reads back on
load, so the URL survives a reload and is worth sending to someone. That needs the one rule in
`nginx.conf` (`location /checklist { try_files $uri /app.html; }`); opened as a local file, where
there is no server to route paths, the same thing rides in the URL hash instead.

For a second monitor or a tablet next to the sim, serve the folder:

```sh
python3 -m http.server 8080
# then http://<your-ip>:8080 on the tablet
```

Or with Docker — the image compiles the YAML and serves the result with nginx on Alpine:

```sh
docker build -t flightdeck .
docker run --rm -p 8080:8080 flightdeck
```

## Using it

| Key | Action |
| --- | --- |
| `Space` | Check the highlighted line and advance |
| `↑` / `↓` | Move the highlight |
| `Backspace` | Uncheck the last checked line |
| `N` / `P` | Next / previous phase |
| `R` | Reset the current phase |
| `T` | Open the type menu — then type to filter it, `↑`/`↓` and `Enter` to pick |

Lines are also clickable/tappable. The amber line is what you're on; green means done.

**The blanks are fields.** Any `____` in a response — V-speeds, fuel, QNH, minima, trim — is a box you
type into, saved per aircraft with everything else. Click it (or tab to it) and type; `Enter` commits.
They are the numbers for *this* flight, so **Reset flight** clears them along with the ticks.

**Print** puts the whole selected type on paper — every phase, notes included, two columns to a page,
boxes left empty to tick by hand. It prints black on white whichever theme is on screen, keeps any
numbers you have filled in, and follows the variant you picked (lines belonging to other variants are
left out, and lines shown with no variant chosen carry their variant tag). `Ctrl`/`⌘`+`P` works too.

Phases are tagged either **Flow** (a panel scan done from memory) or **Checklist** (read and respond) —
the same distinction real crews make. Airbus cards keep their printed *below the line* break.

**Theme** cycles Auto → Day → Night. Day is a laminated checklist card, Night is a backlit EFB —
use Night when you fly at night so the second screen doesn't blind you.

**Reset flight** clears every phase for the selected type, and the numbers with it. Everything else is
remembered between sessions, per aircraft: checked lines, the phase you left off on, the variant you
picked, and whatever you typed into the blanks.

## Editing the checklists

```
checklists/
  fleet.yaml      menu order — comment a line out to drop that type
  a320ceo.yaml    one file per type
  b787.yaml
  ...
build.py          compiles the YAML into every page below
index.html        homepage (its fleet list is generated)
app.html          the checklist tool (its FLEET data block is generated)
types/            one plain HTML page per aircraft — fully generated, don't edit
robots.txt        generated
sitemap.xml       generated
Dockerfile        multi-stage build → nginx:alpine
nginx.conf        server block, port 8080
```

The public address lives in one place — the `SITE` constant at the top of `build.py`. It produces the
canonical link and `og:url` on each page, the structured data, `robots.txt` and `sitemap.xml`. Set it
to `""` and all of that is simply left out.

**One page per aircraft.** The tool keeps all types on a single URL behind JavaScript, which gives a
search engine one page to weigh for forty aeroplanes. `types/<id>.html` is the plain counterpart: the
whole checklist in the markup, its own title, description and canonical, links back into the
interactive version, and cross-links to every other type. The homepage fleet list links to them and
the sitemap lists them all. Add an aircraft and its page appears; drop one and `build.py` deletes the
page it left behind (`--check` fails while a stray page is still there).

Edit a YAML file, then:

```sh
python3 build.py           # regenerate index.html and app.html
python3 build.py --check   # exit 1 if either page is stale (CI / pre-commit)
```

`build.py` uses PyYAML when it's installed and otherwise falls back to a bundled parser for the
small YAML subset these files use, so it runs on a bare Python 3 install. Both parsers are held to
the same rule: **every plain value is read as text**, so `APU: OFF` stays `OFF` instead of turning
into a boolean and printing as `False`.

An item is simply `CHALLENGE: RESPONSE`, with `note`, `sub`, `divider` and `only` as the only
reserved keys:

```yaml
id:   b738                 # save-slot key in localStorage — don't change it casually
code: "737"                # menu label
name: Boeing 737-800
sub:  2 × CFM56-7B · two-crew
manufacturer: Boeing       # groups the type menu
variants:                  # optional chips; note is shown when the chip is picked
  - name: "-800"
    note: Typical takeoff flaps 5.

phases:
  - id:   preflight
    name: Preflight
    kind: flow             # flow = from memory | checklist = read & respond
    items:
      - BATTERY: "ON"
      - BARO REF: ____ SET       # two or more underscores become a fillable field
      - IRS: NAV
        note: Align needs the aircraft stationary.
      - divider: Below the line              # printed rule, not a checkable item
      - AUTOBRAKE: RTO
        sub: true                            # indented sub-item
      - MAIN DECK CARGO DOOR: CLOSED AND LOCKED
        only:                                # this line belongs to particular variants
          - "-800F"
```

`only` is how the freighters are handled. Flying a 767-300F is the same job as flying a -300ER; the
difference is a handful of lines — main deck cargo door, load and restraint against a wider CG range,
main deck fire suppression, supernumeraries briefed instead of cabin crew. Rather than duplicate a
whole checklist to change four lines, those lines are tagged with the variants they belong to.

With no variant picked they all show, flagged with the variant name — hiding lines by default is the
wrong failure mode for a checklist. Pick a variant and the ones that do not apply disappear, and stop
counting toward the phase total. `build.py` rejects an `only` that names a variant the file does not
declare, so a typo fails the build instead of silently hiding a line.

A run of two or more underscores in a response is a blank the crew fills in — it renders as a typed
field on screen and as a rule to write on when printed. Several per line is fine (`V1 ____ · VR ____ ·
V2 ____`); each keeps its own value.

One YAML gotcha survives: a value containing `": "` must be quoted, or the parser sees a nested
mapping. `build.py` says so by name and line when it happens.

Add the file to `checklists/fleet.yaml` and rebuild. Nothing else needs touching — the type menu,
phase ladder, progress counters and keyboard shortcuts all come from the data. `build.py` fails with
a pointed message on a missing response, a stray second pair on one item, a bad `kind`, or a
duplicate id.

**Why compiled and not loaded at runtime:** browsers refuse `fetch()` from `file://`, so reading the
YAML in the browser would mean you could no longer just double-click `app.html` — you'd need a web
server every time you fly. Compiling keeps the open-it-anywhere convenience and the YAML source both.

## Accuracy

These are condensed for simulator use and are **not for real-world flight**. They were assembled
from general type knowledge, not transcribed from any operator's manual, and they are deliberately
simplified — the abnormal and emergency checklists that make up most of a real QRH are not here at
all.

Sequences and values vary by operator, engine option and add-on model. Engine start order is the
clearest example: the A340, A380, 747, MD-80 and MD-11 items say so inline rather than pretending
there is one right answer. Cross-check against the aircraft's FCOM or your add-on developer's
documentation, and edit the YAML to match what you actually fly.
