"""Self-contained HTML dashboard for a MergeWeather report.

The output is a single file: compiled Tailwind CSS (assets/report.css, built by
`make css`) and the interaction script (assets/report.js) are inlined, and the
report itself is embedded as JSON for the interactive graph. All content is
also rendered server-side, so the report remains readable without JavaScript.
No network requests are made when the file is opened.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, Iterable, List

ASSETS = Path(__file__).with_name("assets")

# status -> (icon, weather name, badge classes)
WEATHER = {
    "pass": ("☀", "Sunny", "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-300 dark:ring-emerald-400/20"),
    "interaction": ("⛈", "Thunderstorm", "bg-rose-500/10 text-rose-700 ring-rose-600/20 dark:text-rose-300 dark:ring-rose-400/30"),
    "fail": ("🌧", "Rain", "bg-red-500/10 text-red-700 ring-red-600/20 dark:text-red-300 dark:ring-red-400/30"),
    "flaky": ("🌦", "Showers", "bg-fuchsia-500/10 text-fuchsia-700 ring-fuchsia-600/20 dark:text-fuchsia-300 dark:ring-fuchsia-400/30"),
    "conflict": ("🌫", "Fog", "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-300 dark:ring-amber-400/30"),
    "error": ("🌪", "Tornado", "bg-purple-500/10 text-purple-700 ring-purple-600/20 dark:text-purple-300 dark:ring-purple-400/30"),
    "not_run": ("❔", "Uncharted", "bg-zinc-500/10 text-zinc-600 ring-zinc-500/20 dark:text-zinc-400 dark:ring-zinc-400/20"),
    "pending": ("…", "Forming", "bg-sky-500/10 text-sky-700 ring-sky-600/20 dark:text-sky-300 dark:ring-sky-400/20"),
}

VERDICT = {
    "interactions-found": ("⛈", "Storm warning", "Behavioral interactions found between branches.",
                           "from-rose-500/20 via-rose-500/5 to-transparent", "text-rose-600 dark:text-rose-400"),
    "no-failures-found": ("☀", "Clear skies", "No failing combinations in the explored space.",
                          "from-emerald-500/20 via-emerald-500/5 to-transparent", "text-emerald-600 dark:text-emerald-400"),
    "inconclusive-budget": ("🌥", "Partly cloudy", "Budget ran out before the space was fully explored.",
                            "from-amber-500/20 via-amber-500/5 to-transparent", "text-amber-600 dark:text-amber-400"),
    "base-failing": ("🌪", "Base is broken", "The base fails on its own; branch failures were not attributed.",
                     "from-purple-500/20 via-purple-500/5 to-transparent", "text-purple-600 dark:text-purple-400"),
}

CARD = "rounded-xl border border-zinc-200 bg-white/80 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/50"
MUTED = "text-zinc-500 dark:text-zinc-400"
CODE = ("rounded-lg border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-relaxed text-zinc-800 "
        "overflow-x-auto whitespace-pre dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300")
TH = "px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400"
TD = "px-3 py-2 align-top"
CHIP = ("inline-flex items-center rounded-md border border-zinc-200 bg-zinc-100 px-2 py-0.5 font-mono text-xs "
        "text-zinc-700 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200")

e = html.escape


def weather_key(status: str, size: int) -> str:
    if status == "fail":
        return "fail" if size <= 1 else "interaction"
    return status if status in WEATHER else "pending"


def badge(status: str, size: int = 2, label: str = None) -> str:
    icon, name, cls = WEATHER[weather_key(status, size)]
    return (f'<span class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs '
            f'font-medium ring-1 ring-inset {cls}">{icon} {e(label or name)}</span>')


def pill(text: str, tone: str = "zinc") -> str:
    tones = {
        "zinc": "bg-zinc-500/10 text-zinc-700 ring-zinc-500/20 dark:text-zinc-300",
        "green": "bg-emerald-500/10 text-emerald-700 ring-emerald-600/20 dark:text-emerald-300",
        "amber": "bg-amber-500/10 text-amber-700 ring-amber-600/20 dark:text-amber-300",
        "rose": "bg-rose-500/10 text-rose-700 ring-rose-600/20 dark:text-rose-300",
        "sky": "bg-sky-500/10 text-sky-700 ring-sky-600/20 dark:text-sky-300",
    }
    return (f'<span class="inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs '
            f'font-medium ring-1 ring-inset {tones[tone]}">{e(text)}</span>')


def copy_block(text: str, ident: str, label: str = "Copy reproduction command") -> str:
    return f"""
<div class="relative">
  <div class="mb-2 flex items-center justify-between gap-2">
    <span class="text-xs font-medium {MUTED}">Reproduce</span>
    <button type="button" data-copy="{e(ident)}" aria-label="{e(label)}"
      class="mw-copy inline-flex items-center gap-1.5 rounded-md border border-zinc-200 bg-white px-2.5 py-1 text-xs font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700">
      <svg aria-hidden="true" viewBox="0 0 16 16" class="h-3.5 w-3.5 fill-current"><path d="M4 2a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V2zm2-1a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V2a1 1 0 0 0-1-1H6zM2 5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1v-1h1v1a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h1v1H2z"/></svg>
      <span class="mw-copy-label">{e(label)}</span>
    </button>
  </div>
  <pre id="{e(ident)}" class="{CODE}">{e(text)}</pre>
</div>"""


def kpi(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="{CARD} p-4"><div class="text-xs font-medium uppercase tracking-wide {MUTED}">{e(label)}</div>'
            f'<div class="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{e(value)}</div>'
            + (f'<div class="mt-0.5 text-xs {MUTED}">{e(sub)}</div>' if sub else "") + "</div>")


def section(title: str, body: str, ident: str = "", aside: str = "") -> str:
    return (f'<section {"id=" + chr(34) + ident + chr(34) if ident else ""} class="scroll-mt-20">'
            f'<div class="mb-3 flex flex-wrap items-end justify-between gap-2"><h2 class="text-base font-semibold '
            f'tracking-tight">{e(title)}</h2>{aside}</div>{body}</section>')


def anchor(cid: str) -> str:
    return "combo-" + "".join(ch if ch.isalnum() else "-" for ch in cid)


def related_claims(exp: Dict, finding: Dict) -> List[Dict]:
    ids = {f"finding:{finding['id']}", f"combo:{finding['combination']}", f"combo:{finding['reduced_from']}"}
    ids |= {f"combo:{c['combination']}" for c in finding["removal_checks"]}
    ids |= {f"diff:{b}" for b in finding["branches"]}
    return [c for c in exp.get("claims", []) if set(c["evidence"]) & ids or not c["evidence"]]


def finding_card(f: Dict, report: Dict, combos: Dict[str, Dict]) -> str:
    icon, name, _ = WEATHER[weather_key("fail", len(f["branches"]))]
    proven = f["minimality"] == "proven_1_minimal"
    chips = " ".join(f'<span class="{CHIP}">{e(b)}</span>' for b in f["branches"])
    final = combos.get(f["combination"], {})

    checks = "".join(
        f'<tr class="border-t border-zinc-100 dark:border-zinc-800"><td class="{TD} font-mono text-xs">− {e(c["removed"])}</td>'
        f'<td class="{TD}"><a href="#{anchor(c["combination"])}" class="font-mono text-xs text-sky-600 hover:underline dark:text-sky-400">{e(c["combination"])}</a></td>'
        f'<td class="{TD}">{badge(c["status"], len(c["combination"].split("+")))}</td>'
        f'<td class="{TD}">{pill(c["verdict"], "green" if c["verdict"] == "definitive" else "amber")}</td></tr>'
        for c in f["removal_checks"])
    steps = "".join(
        f'<li class="flex items-center gap-2"><span class="h-1.5 w-1.5 rounded-full bg-zinc-400"></span>'
        f'<span class="font-mono text-xs">remove {e(s["removed"])} → {e(s["tested"])}</span>{badge(s["status"], 2)}</li>'
        for s in f["reduction_steps"]) or f'<li class="text-xs {MUTED}">No reduction needed: the failing set was already minimal when found.</li>'
    sig = (f'<pre class="{CODE}">{e(chr(10).join(f["signature"]))}</pre>' if f["signature"]
           else f'<p class="text-xs {MUTED}">No signature lines matched.</p>')
    runs = "".join(
        f'<details class="group rounded-lg border border-zinc-200 dark:border-zinc-800"><summary class="flex cursor-pointer items-center gap-2 px-3 py-2 text-xs">'
        f'<span class="mw-chevron transition">›</span><span class="font-mono">{e(r["id"])}</span>{badge(r["outcome"] if r["outcome"] != "timeout" else "fail", len(f["branches"]), r["outcome"])}'
        f'<span class="{MUTED}">exit {e(str(r["exit_code"]))} · {e(str(r["duration"]))}s</span></summary>'
        f'<div class="space-y-2 px-3 pb-3"><pre class="{CODE} max-h-64">{e(r["stdout_tail"])}</pre>'
        + (f'<pre class="{CODE} max-h-64">{e(r["stderr_tail"])}</pre>' if r["stderr_tail"].strip() else "")
        + "</div></details>" for r in final.get("runs", [])[:3])

    exp = report.get("explanation")
    if exp and exp.get("claims"):
        claims = related_claims(exp, f)
        items = "".join(
            f'<li class="flex gap-3 py-2">{pill("OBSERVATION", "green") if c["label"] == "observation" else pill("HYPOTHESIS", "amber")}'
            f'<div><p class="text-sm">{e(c["text"])}</p><p class="mt-1 flex flex-wrap gap-1">'
            + ("".join(f'<span class="{CHIP}">{e(x)}</span>' for x in c["evidence"]) or f'<span class="text-xs {MUTED}">no valid citation</span>')
            + "</p></div></li>" for c in claims)
        explanation = (f'<p class="text-sm">{e(exp.get("summary", ""))}</p>'
                       f'<ul class="mt-2 divide-y divide-zinc-100 dark:divide-zinc-800">{items}</ul>'
                       f'<p class="mt-2 text-xs {MUTED}">Generated by {e(str(exp.get("model")))}. Claims labeled '
                       f'HYPOTHESIS are not established by recorded evidence. Findings are never changed by this step.</p>')
    else:
        explanation = (f'<p class="text-sm {MUTED}">No explanation attached. Run '
                       f'<code class="{CHIP}">mergeweather explain report.json</code> to add an evidence-cited one.</p>')

    caveats = ("".join(f'<li>{e(c)}</li>' for c in f["minimality_caveats"]))
    return f"""
<article id="finding-{e(f['id'])}" class="{CARD} overflow-hidden scroll-mt-20">
  <div class="border-b border-zinc-200 bg-gradient-to-r from-rose-500/10 to-transparent p-5 dark:border-zinc-800">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <div class="flex items-center gap-2 text-sm font-medium text-rose-600 dark:text-rose-400">{icon} {e(f['id'])} · {name}</div>
        <h3 class="mt-1 text-lg font-semibold tracking-tight">{e(f['kind'].capitalize())}</h3>
        <div class="mt-2 flex flex-wrap gap-1.5">{chips}</div>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        {pill('proven 1-minimal' if proven else 'smallest found', 'green' if proven else 'amber')}
        {pill(f['stability'], 'green' if f['stability'] == 'stable' else 'amber')}
        <span class="{CHIP}">{e(f['fingerprint'] or '')}</span>
        <button type="button" data-focus="{e(f['id'])}" class="mw-focus rounded-md border border-zinc-200 px-2 py-0.5 text-xs font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800">Show in graph</button>
      </div>
    </div>
    {f'<ul class="mt-3 list-disc pl-5 text-xs text-amber-700 dark:text-amber-300">{caveats}</ul>' if caveats else ''}
  </div>
  <div class="p-5">
    {copy_block(f['reproduction'], 'repro-' + f['id'])}
  </div>
  <details class="group border-t border-zinc-200 dark:border-zinc-800">
    <summary class="flex cursor-pointer items-center justify-between px-5 py-3 text-sm font-medium hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
      <span class="flex items-center gap-2"><span class="mw-chevron inline-block transition">›</span>Evidence &amp; LLM Explanation</span>
      <span class="text-xs {MUTED}">{len(f['evidence'])} evidence items · reduced from <span class="font-mono">{e(f['reduced_from'])}</span></span>
    </summary>
    <div class="grid gap-6 px-5 pb-5 lg:grid-cols-2">
      <div class="space-y-4">
        <div><h4 class="mb-2 text-xs font-semibold uppercase tracking-wide {MUTED}">Failure signature</h4>{sig}</div>
        <div><h4 class="mb-2 text-xs font-semibold uppercase tracking-wide {MUTED}">Removal checks (1-minimality proof)</h4>
          <div class="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800"><table class="w-full text-sm">
          <thead><tr><th class="{TH}">Removed</th><th class="{TH}">Combination</th><th class="{TH}">Result</th><th class="{TH}">Verdict</th></tr></thead>
          <tbody>{checks}</tbody></table></div></div>
        <div><h4 class="mb-2 text-xs font-semibold uppercase tracking-wide {MUTED}">Reduction path</h4><ul class="space-y-1.5">{steps}</ul></div>
      </div>
      <div class="space-y-4">
        <div><h4 class="mb-2 text-xs font-semibold uppercase tracking-wide {MUTED}">Test runs · {e(f['combination'])}</h4><div class="space-y-2">{runs}</div></div>
        <div class="rounded-lg border border-violet-500/30 bg-violet-500/5 p-4">
          <h4 class="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-violet-700 dark:text-violet-300">✦ LLM explanation</h4>
          {explanation}
        </div>
      </div>
    </div>
  </details>
</article>"""


def combo_rows(report: Dict) -> str:
    rows = []
    for c in report["combinations"]:
        size = len(c["branches"])
        detail = ""
        if c["status"] == "conflict":
            detail = (f'<p class="text-sm">Textual conflict while merging <span class="font-mono">{e(c["conflict_at"] or "")}</span> in '
                      + ", ".join(f'<span class="{CHIP}">{e(x)}</span>' for x in c["conflict_files"]) + "</p>")
        else:
            detail = copy_block(c.get("reproduction", ""), "repro-" + anchor(c["id"]))
            for r in c["runs"][:3]:
                detail += (f'<p class="mt-3 text-xs {MUTED}"><span class="font-mono">{e(r["id"])}</span> · {e(r["outcome"])} · '
                           f'exit {e(str(r["exit_code"]))} · {e(str(r["duration"]))}s · <span class="font-mono">{e(r["fingerprint"])}</span></p>'
                           f'<pre class="{CODE} mt-1 max-h-48">{e((r["stdout_tail"] + r["stderr_tail"])[-2000:])}</pre>')
        rows.append(f"""
<details id="{anchor(c['id'])}" data-status="{e(weather_key(c['status'], size))}" data-id="{e(c['id'])}" class="mw-row group scroll-mt-20 border-t border-zinc-100 dark:border-zinc-800">
  <summary class="grid cursor-pointer grid-cols-12 items-center gap-2 px-4 py-2.5 text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
    <span class="col-span-5 flex min-w-0 items-center gap-2 font-mono text-xs sm:col-span-4"><span class="mw-chevron inline-block transition">›</span><span class="truncate">{e(c['id'])}</span></span>
    <span class="col-span-4 sm:col-span-3">{badge(c['status'], size)}{' <span class="text-xs text-amber-600">incomplete</span>' if c['incomplete'] else ''}</span>
    <span class="col-span-3 text-right tabular-nums sm:col-span-1 {MUTED}">{len(c['runs'])}×</span>
    <span class="hidden truncate font-mono text-xs sm:col-span-2 sm:block {MUTED}">{e((c['tree'] or '—')[:12])}</span>
    <span class="hidden truncate font-mono text-xs sm:col-span-2 sm:block {MUTED}">{e(', '.join(x for x in c['fingerprints'] if x != 'pass') or '—')}</span>
  </summary>
  <div class="px-4 pb-4">{detail}</div>
</details>""")
    return "".join(rows)


def _asset(name: str) -> str:
    return (ASSETS / name).read_text()


def _json_for_script(data: Dict) -> str:
    return (json.dumps(data, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def render(report: Dict) -> str:
    inp, iso, bud = report["inputs"], report["isolation"], report["budget"]
    combos = {c["id"]: c for c in report["combinations"]}
    vicon, vtitle, vdesc, vgrad, vcolor = VERDICT.get(report["verdict"], ("?", report["verdict"], "", "", ""))
    tested = sum(1 for c in report["combinations"] if c["runs"])
    findings = report["findings"]

    status_counts: Dict[str, int] = {}
    for c in report["combinations"]:
        k = weather_key(c["status"], len(c["branches"]))
        status_counts[k] = status_counts.get(k, 0) + 1
    filters = ('<button type="button" data-filter="all" class="mw-filter rounded-full border border-zinc-200 px-2.5 py-0.5 text-xs font-medium dark:border-zinc-700" aria-pressed="true">All</button>'
               + "".join(f'<button type="button" data-filter="{k}" class="mw-filter rounded-full border border-zinc-200 px-2.5 py-0.5 text-xs font-medium dark:border-zinc-700" aria-pressed="false">{WEATHER[k][0]} {WEATHER[k][1]} · {n}</button>'
                         for k, n in status_counts.items()))

    branches = "".join(
        f'<tr class="border-t border-zinc-100 dark:border-zinc-800"><td class="{TD}"><span class="{CHIP}">{e(b["label"])}</span></td>'
        f'<td class="{TD} font-mono text-xs">{e(b["ref"])}</td><td class="{TD} font-mono text-xs {MUTED}">{e(b["commit"][:12])}</td>'
        f'<td class="{TD} text-xs">{e(", ".join(b["changed_files"]) or "—")}</td>'
        f'<td class="{TD}">{badge(combos[b["label"]]["status"], 1) if b["label"] in combos else badge("not_run", 1)}</td></tr>'
        for b in inp["branches"])

    conflicts = ("".join(
        f'<li class="flex flex-wrap items-center gap-2 py-2">{badge("conflict")}<a class="font-mono text-xs text-sky-600 hover:underline dark:text-sky-400" href="#{anchor(c["combination"])}">{e(c["combination"])}</a>'
        f'<span class="text-xs {MUTED}">while merging <span class="font-mono">{e(c["conflict_while_merging"] or "")}</span>:</span>'
        + "".join(f'<span class="{CHIP}">{e(x)}</span>' for x in c["files"]) + "</li>" for c in report["conflicts"])
        or f'<li class="py-2 text-sm {MUTED}">No textual merge conflicts.</li>')

    warn = ""
    if iso.get("warning"):
        warn = (f'<div class="mb-6 flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-800 dark:text-amber-200">'
                f'<span aria-hidden="true">⚠</span><div><b>No container isolation.</b> {e(iso["warning"])}</div></div>')

    finding_html = "".join(finding_card(f, report, combos) for f in findings) or (
        f'<div class="{CARD} p-8 text-center"><div class="text-3xl">☀</div><p class="mt-2 font-medium">No failing combinations</p>'
        f'<p class="text-sm {MUTED}">Everything that was explored passed.</p></div>')
    focus_chips = "".join(
        f'<button type="button" data-focus="{e(f["id"])}" class="mw-focus rounded-full border border-rose-500/40 bg-rose-500/10 px-2.5 py-0.5 text-xs font-medium text-rose-700 dark:text-rose-300">⛈ {e(f["id"])}: {e(" + ".join(f["branches"]))}</button>'
        for f in findings)

    legend = "".join(
        f'<span class="flex items-center gap-1.5"><span class="h-2.5 w-2.5 rounded-full" style="background:var(--g-{v})"></span>{n}</span>'
        for v, n in [("pass", "Sunny"), ("inter", "Thunderstorm"), ("fail", "Rain"), ("flaky", "Showers"),
                     ("conflict", "Fog"), ("notrun", "Uncharted"), ("pruned", "Pruned")])

    body = f"""
<header class="sticky top-0 z-30 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
  <div class="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
    <div class="flex min-w-0 items-center gap-3">
      <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-sky-400 to-violet-500 text-base shadow">🌤</div>
      <div class="min-w-0"><div class="text-sm font-semibold">MergeWeather</div>
        <div class="truncate font-mono text-xs {MUTED}">{e(Path(inp['repository']).name)} · base {e(inp['base']['commit'][:10])}</div></div>
    </div>
    <nav class="hidden items-center gap-5 text-sm md:flex {MUTED}">
      <a href="#graph" class="hover:text-zinc-900 dark:hover:text-white">Graph</a>
      <a href="#findings" class="hover:text-zinc-900 dark:hover:text-white">Findings</a>
      <a href="#combinations" class="hover:text-zinc-900 dark:hover:text-white">Combinations</a>
      <a href="#run" class="hover:text-zinc-900 dark:hover:text-white">Run details</a>
    </nav>
    <button type="button" id="mw-theme" aria-label="Toggle color theme" class="rounded-md border border-zinc-200 px-2 py-1 text-sm dark:border-zinc-700"><span class="dark:hidden">☾</span><span class="hidden dark:inline">☀</span></button>
  </div>
</header>

<main class="mx-auto max-w-7xl space-y-10 px-4 py-8 sm:px-6">
  {warn}
  <div class="relative overflow-hidden {CARD} p-6 sm:p-8">
    <div class="pointer-events-none absolute inset-0 bg-gradient-to-br {vgrad}"></div>
    <div class="relative flex flex-wrap items-center justify-between gap-6">
      <div>
        <div class="text-xs font-medium uppercase tracking-wider {MUTED}">Forecast</div>
        <h1 class="mt-1 flex items-center gap-3 text-3xl font-semibold tracking-tight sm:text-4xl"><span>{vicon}</span><span class="{vcolor}">{e(vtitle)}</span></h1>
        <p class="mt-2 max-w-xl text-sm {MUTED}">{e(vdesc)}</p>
      </div>
      <div class="w-full max-w-md text-sm sm:w-auto">
        <div class="font-mono text-xs {MUTED}">$ {e(inp['test_command'])}</div>
        <div class="mt-2 flex flex-wrap gap-1.5">{''.join(f'<span class="{CHIP}">{e(b["label"])}</span>' for b in inp['branches'])}</div>
      </div>
    </div>
  </div>

  <div class="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
    {kpi('Findings', str(len(findings)), 'minimal failing sets')}
    {kpi('Combinations', str(tested), f'{len(report["combinations"])} built')}
    {kpi('Test runs', f"{bud['used_runs']}/{bud['max_runs']}", 'budget exhausted' if bud['exhausted'] else 'within budget')}
    {kpi('Conflicts', str(len(report['conflicts'])), 'textual, reported separately')}
    {kpi('Flaky', str(len(report['flaky_combinations'])), 'mixed outcomes')}
    {kpi('Sandbox', str(iso['backend']), 'network isolated' if iso['network_isolated'] else 'network NOT isolated')}
  </div>

  {section('Interaction graph', f'''
  <div class="{CARD} overflow-hidden">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <div class="flex rounded-lg border border-zinc-200 p-0.5 text-xs font-medium dark:border-zinc-700" role="tablist">
        <button type="button" data-view="lattice" class="mw-view rounded-md px-3 py-1" aria-pressed="true">Combination lattice</button>
        <button type="button" data-view="network" class="mw-view rounded-md px-3 py-1" aria-pressed="false">Branch network</button>
      </div>
      <div class="flex flex-wrap gap-1.5">{focus_chips}<button type="button" data-focus="" class="mw-focus rounded-full border border-zinc-200 px-2.5 py-0.5 text-xs dark:border-zinc-700">Reset</button></div>
    </div>
    <div class="relative grid lg:grid-cols-[1fr_280px]">
      <div class="mw-bg-grid relative h-[440px]">
        <svg id="mw-graph" class="mw-graph h-full w-full" role="img" aria-label="Interactive graph of tested branch combinations"></svg>
        <noscript><p class="p-6 text-sm">Enable JavaScript for the interactive graph; all data is listed below.</p></noscript>
        <div id="mw-tip" class="pointer-events-none absolute z-10 hidden max-w-xs rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-zinc-700 dark:bg-zinc-900"></div>
        <div class="absolute bottom-3 right-3 flex gap-1">
          <button type="button" data-zoom="1.25" class="mw-zoom h-7 w-7 rounded-md border border-zinc-200 bg-white text-sm dark:border-zinc-700 dark:bg-zinc-900" aria-label="Zoom in">+</button>
          <button type="button" data-zoom="0.8" class="mw-zoom h-7 w-7 rounded-md border border-zinc-200 bg-white text-sm dark:border-zinc-700 dark:bg-zinc-900" aria-label="Zoom out">−</button>
          <button type="button" data-zoom="0" class="mw-zoom h-7 rounded-md border border-zinc-200 bg-white px-2 text-xs dark:border-zinc-700 dark:bg-zinc-900">Fit</button>
        </div>
      </div>
      <aside id="mw-inspector" class="border-t border-zinc-200 p-4 text-sm lg:border-l lg:border-t-0 dark:border-zinc-800">
        <p class="{MUTED}">Hover a node for details, click to inspect. Edges connect each combination to the sets one branch larger. Use a finding chip to trace its reduction.</p>
      </aside>
    </div>
    <div class="flex flex-wrap gap-x-4 gap-y-1 border-t border-zinc-200 px-4 py-2.5 text-xs dark:border-zinc-800 {MUTED}">{legend}</div>
  </div>''', 'graph')}

  {section('Findings', f'<div class="space-y-4">{finding_html}</div><p class="mt-3 text-xs {MUTED}">{e(report["minimality_note"])}</p>', 'findings')}

  {section('All combinations', f'''
  <div class="{CARD} overflow-hidden">
    <div class="flex flex-wrap items-center gap-2 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <input id="mw-search" type="search" placeholder="Filter by branch…" class="w-full rounded-md border border-zinc-200 bg-transparent px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-sky-500 sm:w-56 dark:border-zinc-700">
      <div class="flex flex-wrap gap-1.5">{filters}</div>
    </div>
    <div class="hidden grid-cols-12 gap-2 px-4 py-2 sm:grid {TH}"><span class="col-span-4">Combination</span><span class="col-span-3">Forecast</span><span class="col-span-1 text-right">Runs</span><span class="col-span-2">Tree</span><span class="col-span-2">Fingerprint</span></div>
    <div id="mw-rows">{combo_rows(report)}</div>
  </div>''', 'combinations')}

  <div id="run" class="grid scroll-mt-20 gap-6 lg:grid-cols-2">
    {section('Branches', f'<div class="{CARD} overflow-x-auto"><table class="w-full text-sm"><thead><tr><th class="{TH}">Label</th><th class="{TH}">Ref</th><th class="{TH}">Commit</th><th class="{TH}">Changed</th><th class="{TH}">Alone</th></tr></thead><tbody>{branches}</tbody></table></div>')}
    {section('Textual merge conflicts', f'<div class="{CARD} px-4"><ul class="divide-y divide-zinc-100 dark:divide-zinc-800">{conflicts}</ul></div>')}
    {section('Sandbox', f'''<div class="{CARD} p-4"><dl class="grid grid-cols-2 gap-y-2 text-sm">
      <dt class="{MUTED}">Backend</dt><dd class="font-mono text-xs">{e(str(iso['backend']))} {e(str(iso.get('image', '')))}</dd>
      <dt class="{MUTED}">Network isolated</dt><dd>{pill(str(iso['network_isolated']), 'green' if iso['network_isolated'] else 'rose')}</dd>
      <dt class="{MUTED}">Memory limit</dt><dd class="font-mono text-xs">{e(str(iso['memory_limit_mb']) + ' MB' if iso.get('memory_limit_mb') else 'not enforced')}</dd>
      <dt class="{MUTED}">Timeout</dt><dd class="font-mono text-xs">{e(str(iso['timeout_s']))} s</dd>
      <dt class="{MUTED}">Credentials scrubbed</dt><dd>{pill(str(iso['credentials_scrubbed']), 'green')}</dd></dl></div>''')}
    {section('Budget & order', f'''<div class="{CARD} space-y-2 p-4 text-sm">
      <p>Used <b>{bud['used_runs']}</b> of {bud['max_runs']} runs · max size {bud['max_size']}{' · <span class="text-amber-600 dark:text-amber-400">exhausted: ' + e(bud['reason']) + '</span>' if bud['exhausted'] else ''}.</p>
      <p class="{MUTED}">Unexplored: {len(bud['unexplored'])} · pruned: {len(report['pruned'])} (supersets of failing, flaky or conflicting sets).</p>
      <p class="text-xs {MUTED}">{e(report['canonical_order']['description'])}</p></div>''')}
  </div>
  <footer class="border-t border-zinc-200 pt-6 text-xs dark:border-zinc-800 {MUTED}">MergeWeather {e(report['tool']['version'])} · schema {e(report['schema'])} · self-contained report, no network requests.</footer>
</main>"""

    return f"""<!doctype html>
<html lang="en" class="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>MergeWeather Report</title>
<script>try{{var t=localStorage.getItem('mw-theme');if(t==='light')document.documentElement.classList.remove('dark');}}catch(_){{}}</script>
<style>{_asset('report.css')}</style>
</head>
<body class="min-h-screen bg-zinc-50 font-sans text-zinc-900 antialiased dark:bg-zinc-950 dark:text-zinc-100">
{body}
<script type="application/json" id="mw-data">{_json_for_script(graph_data(report))}</script>
<script>{_asset('report.js')}</script>
</body>
</html>"""


def graph_data(report: Dict) -> Dict:
    """Compact data for the graph: everything else is already in the DOM."""
    nodes = []
    for c in report["combinations"]:
        nodes.append({"id": c["id"], "b": c["branches"], "s": weather_key(c["status"], len(c["branches"])),
                      "runs": len(c["runs"]), "fp": [x for x in c["fingerprints"] if x != "pass"],
                      "tree": (c["tree"] or "")[:12], "conf": c["conflict_files"]})
    for p in report["pruned"]:
        nodes.append({"id": p["combination"], "b": p["combination"].split("+"), "s": "pruned", "why": p["reason"]})
    for u in report["budget"]["unexplored"]:
        nodes.append({"id": u, "b": u.split("+"), "s": "not_run"})
    return {
        "branches": [b["label"] for b in report["inputs"]["branches"]],
        "nodes": nodes,
        "findings": [{"id": f["id"], "b": f["branches"], "combo": f["combination"], "from": f["reduced_from"],
                      "checks": [c["combination"] for c in f["removal_checks"]],
                      "steps": [s["tested"] for s in f["reduction_steps"]], "kind": f["kind"],
                      "min": f["minimality"], "fp": f["fingerprint"]} for f in report["findings"]],
        "conflicts": [c["branches"] for c in report["conflicts"]],
    }
