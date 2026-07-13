"""
Static HTML dashboard generator.

Turns the list of stored :class:`Listing` objects into a single, self-contained
``index.html`` styled with Tailwind CSS (via CDN). The page is fully responsive
(1/2/3 column grid), supports light & dark mode automatically, and includes a
little vanilla-JS toolbar for client-side filtering/search — no build step, no
framework, perfect for GitHub Pages.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from pathlib import Path

try:  # zoneinfo ships with Python 3.9+; tzdata provides the DB on slim images.
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import config
from .models import Listing

log = logging.getLogger("dashboard")

# Badge colour classes per classification category.
_CATEGORY_STYLE = {
    "confirmed": ("Bestätigt V7 II", "bg-emerald-100 text-emerald-800 "
                                     "dark:bg-emerald-900/50 dark:text-emerald-300"),
    "likely": ("Wahrscheinlich V7 II", "bg-amber-100 text-amber-800 "
                                       "dark:bg-amber-900/50 dark:text-amber-300"),
    "uncertain": ("Unsicher", "bg-orange-100 text-orange-800 "
                              "dark:bg-orange-900/40 dark:text-orange-300"),
    "rejected": ("Kein V7 II", "bg-rose-100 text-rose-700 "
                              "dark:bg-rose-900/40 dark:text-rose-300"),
    "unknown": ("Ungeprüft", "bg-slate-100 text-slate-700 "
                            "dark:bg-slate-700 dark:text-slate-200"),
}

_SOURCE_STYLE = {
    "kleinanzeigen": "bg-sky-600",
    "mobile.de": "bg-indigo-600",
}

_SOURCE_LABEL = {
    "kleinanzeigen": "Kleinanzeigen",
    "mobile.de": "mobile.de",
}


# --------------------------------------------------------------------------- #
# Small formatting helpers
# --------------------------------------------------------------------------- #
def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_new(listing: Listing, now: datetime) -> bool:
    found = _parse_iso(listing.date_found)
    if not found:
        return False
    return (now - found).total_seconds() <= config.NEW_LISTING_HOURS * 3600


def _time_ago(value: str, now: datetime) -> str:
    dt = _parse_iso(value)
    if not dt:
        return ""
    seconds = max(0, int((now - dt).total_seconds()))
    if seconds < 3600:
        return f"vor {seconds // 60} Min."
    if seconds < 86400:
        return f"vor {seconds // 3600} Std."
    days = seconds // 86400
    return "vor 1 Tag" if days == 1 else f"vor {days} Tagen"


def _fmt_price(listing: Listing) -> str:
    if listing.price_eur is not None:
        return f"{listing.price_eur:,.0f} €".replace(",", ".")
    return html.escape(listing.price_raw) if listing.price_raw else "Preis auf Anfrage"


def _fmt_km(listing: Listing) -> str | None:
    if listing.mileage_km is None:
        return None
    return f"{listing.mileage_km:,.0f} km".replace(",", ".")


def _local_timestamp(now: datetime) -> str:
    if ZoneInfo is not None:
        try:
            local = now.astimezone(ZoneInfo(config.DISPLAY_TIMEZONE))
            return local.strftime("%d.%m.%Y, %H:%M Uhr")
        except Exception:  # noqa: BLE001 — missing tzdata, fall through to UTC
            pass
    return now.strftime("%d.%m.%Y, %H:%M UTC")


# --------------------------------------------------------------------------- #
# Card + page rendering
# --------------------------------------------------------------------------- #
def _spec_chip(label: str, value: str) -> str:
    return (
        '<span class="inline-flex items-center gap-1 rounded-md bg-slate-100 '
        'px-2 py-1 text-xs font-medium text-slate-700 dark:bg-slate-700/60 '
        f'dark:text-slate-200">{html.escape(label)}: '
        f'<strong class="font-semibold">{html.escape(value)}</strong></span>'
    )


def _render_card(listing: Listing, now: datetime) -> str:
    is_new = _is_new(listing, now)
    category = listing.classification.category or "unknown"
    cat_label, cat_classes = _CATEGORY_STYLE.get(category, _CATEGORY_STYLE["unknown"])
    confidence_pct = int(round(listing.classification.confidence * 100))
    source_color = _SOURCE_STYLE.get(listing.source, "bg-slate-600")

    # Spec chips (only render the ones we actually have).
    chips = []
    km = _fmt_km(listing)
    if km:
        chips.append(_spec_chip("Laufleistung", km))
    if listing.first_registration:
        chips.append(_spec_chip("EZ", listing.first_registration))
    if listing.power_ps:
        chips.append(_spec_chip("Leistung", f"{listing.power_ps} PS"))
    chips_html = "".join(chips)

    # Image layered ABOVE an always-present placeholder icon. If the image is
    # missing, slow or broken, the icon underneath simply shows through — the
    # box is never left blank. A broken image removes itself via onerror.
    if listing.image_url:
        image_html = (
            f'<img src="{html.escape(listing.image_url)}" alt="" loading="lazy" '
            'class="absolute inset-0 z-10 h-full w-full object-cover" '
            'onerror="this.remove()">'
        )
    else:
        image_html = ""

    # NEW badge.
    new_badge = (
        '<span class="absolute left-3 top-3 z-20 inline-flex items-center gap-1 '
        'rounded-full bg-rose-600 px-2.5 py-1 text-xs font-bold text-white '
        'shadow-lg ring-2 ring-white/70 dark:ring-slate-900/70">'
        '<span class="relative flex h-2 w-2"><span class="absolute inline-flex '
        'h-full w-full animate-ping rounded-full bg-white opacity-75"></span>'
        '<span class="relative inline-flex h-2 w-2 rounded-full bg-white">'
        "</span></span>NEU</span>"
    ) if is_new else ""

    # Classification reasons (expandable).
    reasons = "".join(
        f'<li class="flex gap-1.5"><span class="text-slate-400">•</span>'
        f"<span>{html.escape(r)}</span></li>"
        for r in listing.classification.reasons
    )
    reasons_block = (
        '<details class="mt-3 text-xs text-slate-500 dark:text-slate-400">'
        '<summary class="cursor-pointer select-none font-medium '
        'hover:text-slate-700 dark:hover:text-slate-200">'
        f"Warum {html.escape(cat_label)}? ({confidence_pct}% Konfidenz)</summary>"
        f'<ul class="mt-2 space-y-1">{reasons}</ul></details>'
    ) if reasons else ""

    # Data attributes powering the JS filter/search bar.
    search_index = html.escape(
        f"{listing.title} {listing.location}".lower(), quote=True)

    return f"""
    <article class="listing-card group flex flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-xl dark:border-slate-700 dark:bg-slate-800"
             data-category="{html.escape(category)}"
             data-source="{html.escape(listing.source)}"
             data-new="{'1' if is_new else '0'}"
             data-search="{search_index}">
      <div class="relative aspect-[4/3] w-full overflow-hidden bg-slate-100 dark:bg-slate-700">
        <div class="absolute inset-0 z-0 flex items-center justify-center text-slate-300 dark:text-slate-500">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.2" stroke="currentColor" class="h-12 w-12"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M4.5 19.5h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z"/></svg>
        </div>
        {image_html}
        {new_badge}
        <span class="absolute right-3 top-3 z-20 rounded-full {source_color} px-2.5 py-1 text-xs font-semibold text-white shadow">{html.escape(_SOURCE_LABEL.get(listing.source, listing.source))}</span>
      </div>

      <div class="flex flex-1 flex-col p-4">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold {cat_classes}">{html.escape(cat_label)}</span>
        </div>

        <h2 class="line-clamp-2 text-base font-semibold leading-snug text-slate-900 dark:text-white">
          <a href="{html.escape(listing.url)}" target="_blank" rel="noopener noreferrer" class="hover:underline">{html.escape(listing.title) or 'Ohne Titel'}</a>
        </h2>

        <p class="mt-2 text-xl font-bold text-slate-900 dark:text-white">{_fmt_price(listing)}</p>

        <div class="mt-3 flex flex-wrap gap-1.5">{chips_html}</div>

        {reasons_block}

        <div class="mt-auto pt-4">
          <div class="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span class="inline-flex items-center gap-1 truncate">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4 shrink-0"><path fill-rule="evenodd" d="M9.69 18.933l.003.001C9.89 19.02 10 19 10 19s.11.02.308-.066l.002-.001.006-.003.018-.008a5.741 5.741 0 00.281-.14c.186-.096.446-.24.757-.433.62-.386 1.445-.966 2.274-1.765C15.302 14.988 17 12.493 17 9A7 7 0 103 9c0 3.492 1.698 5.988 3.355 7.584a13.731 13.731 0 002.273 1.765 11.842 11.842 0 00.976.544l.062.029.018.008.006.003zM10 11.25a2.25 2.25 0 100-4.5 2.25 2.25 0 000 4.5z" clip-rule="evenodd"/></svg>
              <span class="truncate">{html.escape(listing.location) or '—'}</span>
            </span>
            <span class="shrink-0 whitespace-nowrap">{html.escape(_time_ago(listing.date_found, now))}</span>
          </div>
          <a href="{html.escape(listing.url)}" target="_blank" rel="noopener noreferrer"
             class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 dark:bg-white dark:text-slate-900 dark:hover:bg-slate-200">
            Zum Inserat
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4"><path fill-rule="evenodd" d="M5.22 14.78a.75.75 0 001.06 0l7.22-7.22v5.69a.75.75 0 001.5 0v-7.5a.75.75 0 00-.75-.75h-7.5a.75.75 0 000 1.5h5.69l-7.22 7.22a.75.75 0 000 1.06z" clip-rule="evenodd"/></svg>
          </a>
        </div>
      </div>
    </article>"""


def _stat(value: int | str, label: str, accent: str) -> str:
    return f"""
      <div class="rounded-2xl border border-slate-200 bg-white px-5 py-4 dark:border-slate-700 dark:bg-slate-800">
        <div class="text-2xl font-bold {accent}">{value}</div>
        <div class="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{html.escape(label)}</div>
      </div>"""


def generate_html(listings: list[Listing], output_path: Path | None = None) -> str:
    """Render the dashboard and (optionally) write it to ``output_path``."""
    now = datetime.now(timezone.utc)
    output_path = output_path or config.OUTPUT_HTML

    total = len(listings)
    new_count = sum(1 for l in listings if _is_new(l, now))
    confirmed_count = sum(1 for l in listings
                          if l.classification.category == "confirmed")
    updated = _local_timestamp(now)

    cards = "\n".join(_render_card(l, now) for l in listings)

    empty_state = "" if listings else """
      <div class="col-span-full flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-300 py-20 text-center dark:border-slate-600">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="mb-4 h-14 w-14 text-slate-400"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"/></svg>
        <h3 class="text-lg font-semibold text-slate-700 dark:text-slate-200">Noch keine Inserate</h3>
        <p class="mt-1 max-w-md text-sm text-slate-500 dark:text-slate-400">Der Monitor hat bislang keine passenden V7&nbsp;II-Angebote gefunden. Der nächste automatische Lauf aktualisiert diese Seite.</p>
      </div>"""

    title = html.escape(config.TARGET_LABEL)

    return _write(_PAGE_TEMPLATE.format(
        title=title,
        updated=html.escape(updated),
        stat_total=_stat(total, "Inserate gesamt", "text-slate-900 dark:text-white"),
        stat_new=_stat(new_count, "Neu (48 Std.)", "text-rose-600 dark:text-rose-400"),
        stat_confirmed=_stat(confirmed_count, "Bestätigt V7 II",
                             "text-emerald-600 dark:text-emerald-400"),
        cards=cards,
        empty_state=empty_state,
    ), output_path)


def _write(page: str, output_path: Path) -> str:
    output_path.write_text(page, encoding="utf-8")
    log.info("Wrote dashboard to %s (%d bytes).", output_path.name, len(page))
    return page


# --------------------------------------------------------------------------- #
# Page template (Tailwind via CDN + tiny filter/search script)
# --------------------------------------------------------------------------- #
_PAGE_TEMPLATE = """<!doctype html>
<html lang="de" class="scroll-smooth">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex">
  <title>{title} · Marktplatz Monitor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{ theme: {{ extend: {{ fontFamily: {{
      sans: ['-apple-system','BlinkMacSystemFont','SF Pro Text','Segoe UI','Roboto','Helvetica','Arial','sans-serif']
    }} }} }} }};
  </script>
  <style>
    .line-clamp-2 {{ display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }}
  </style>
</head>
<body class="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-900 dark:text-slate-100">

  <header class="sticky top-0 z-30 border-b border-slate-200 bg-white/80 backdrop-blur dark:border-slate-800 dark:bg-slate-900/80">
    <div class="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-4 sm:px-6">
      <div class="flex items-center gap-2">
        <span class="text-2xl">🏍️</span>
        <h1 class="text-lg font-bold tracking-tight sm:text-xl">{title} <span class="text-slate-400">· Marktplatz Monitor</span></h1>
      </div>
      <p class="text-xs text-slate-500 dark:text-slate-400">Automatisch aktualisiert · Letzter Lauf: <time>{updated}</time></p>
    </div>
  </header>

  <main class="mx-auto max-w-6xl px-4 py-6 sm:px-6">

    <section class="mb-6 grid grid-cols-3 gap-3">
      {stat_total}
      {stat_new}
      {stat_confirmed}
    </section>

    <section class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex flex-wrap gap-2" id="filters">
        <button data-filter="all"       class="filter-btn is-active rounded-full px-3.5 py-1.5 text-sm font-medium">Alle</button>
        <button data-filter="new"       class="filter-btn rounded-full px-3.5 py-1.5 text-sm font-medium">🔴 Neu</button>
        <button data-filter="confirmed" class="filter-btn rounded-full px-3.5 py-1.5 text-sm font-medium">✓ Bestätigt</button>
        <button data-filter="likely"    class="filter-btn rounded-full px-3.5 py-1.5 text-sm font-medium">Wahrscheinlich</button>
      </div>
      <input id="search" type="search" placeholder="Suchen (Titel, Ort) …"
             class="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-sm outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-900/10 dark:border-slate-600 dark:bg-slate-800 dark:focus:border-white sm:w-64">
    </section>

    <section id="grid" class="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {cards}
      {empty_state}
    </section>

    <p id="no-results" class="hidden py-16 text-center text-sm text-slate-500 dark:text-slate-400">Keine Inserate entsprechen dem Filter.</p>

  </main>

  <footer class="mx-auto max-w-6xl px-4 py-10 text-center text-xs text-slate-400 sm:px-6">
    <p>Erstellt mit einem selbst gehosteten Python-Scraper · Deploy via GitHub Pages.</p>
    <p class="mt-1">Alle Angaben ohne Gewähr. Preise, Verfügbarkeit und Fahrzeugdaten bitte direkt beim Anbieter prüfen.</p>
  </footer>

  <style>
    .filter-btn {{ background:#fff; color:#475569; border:1px solid #e2e8f0; }}
    .filter-btn.is-active {{ background:#0f172a; color:#fff; border-color:#0f172a; }}
    @media (prefers-color-scheme: dark) {{
      .filter-btn {{ background:#1e293b; color:#cbd5e1; border-color:#334155; }}
      .filter-btn.is-active {{ background:#fff; color:#0f172a; border-color:#fff; }}
    }}
  </style>

  <script>
    (function () {{
      var grid = document.getElementById('grid');
      var cards = Array.prototype.slice.call(document.querySelectorAll('.listing-card'));
      var buttons = Array.prototype.slice.call(document.querySelectorAll('.filter-btn'));
      var search = document.getElementById('search');
      var noResults = document.getElementById('no-results');
      var activeFilter = 'all';

      function apply() {{
        var q = (search.value || '').trim().toLowerCase();
        var visible = 0;
        cards.forEach(function (card) {{
          var cat = card.getAttribute('data-category');
          var isNew = card.getAttribute('data-new') === '1';
          var matchesFilter =
            activeFilter === 'all' ? true :
            activeFilter === 'new' ? isNew :
            cat === activeFilter;
          var matchesSearch = !q || (card.getAttribute('data-search') || '').indexOf(q) !== -1;
          var show = matchesFilter && matchesSearch;
          card.classList.toggle('hidden', !show);
          if (show) visible++;
        }});
        if (noResults) noResults.classList.toggle('hidden', visible !== 0 || cards.length === 0);
      }}

      buttons.forEach(function (btn) {{
        btn.addEventListener('click', function () {{
          buttons.forEach(function (b) {{ b.classList.remove('is-active'); }});
          btn.classList.add('is-active');
          activeFilter = btn.getAttribute('data-filter');
          apply();
        }});
      }});
      if (search) search.addEventListener('input', apply);
    }})();
  </script>
</body>
</html>"""
