#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause
"""Generate the theme-aware README architecture SVGs.

The SVGs are static, self-contained, and use embedded local brand icons. Do not
hand-edit the generated files; edit this script and regenerate them.
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from html import escape
from pathlib import Path

ASSETS = Path(__file__).resolve().parent
LOGOS = ASSETS / "logos"

THEMES = {
    "light": {
        "bg": "#f8fafc",
        "dot": "#cbd5e1",
        "card": "#ffffff",
        "card_border": "#e2e8f0",
        "group": "#f1f5f9",
        "group_border": "#e2e8f0",
        "text": "#0f172a",
        "muted": "#64748b",
        "faint": "#94a3b8",
        "arrow": "#94a3b8",
        "badge_bg": "#f8fafc",
        "badge_border": "#e2e8f0",
        "icon_tile": "#ffffff",
        "icon_border": "#e2e8f0",
    },
    "dark": {
        "bg": "#0d1117",
        "dot": "#30363d",
        "card": "#161b22",
        "card_border": "#30363d",
        "group": "#111827",
        "group_border": "#30363d",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "faint": "#6e7681",
        "arrow": "#6e7681",
        "badge_bg": "#0d1117",
        "badge_border": "#30363d",
        "icon_tile": "#f8fafc",
        "icon_border": "#30363d",
    },
}

ACCENTS = {
    "sky": "#38bdf8",
    "teal": "#2dd4bf",
    "emerald": "#34d399",
    "violet": "#a78bfa",
    "orange": "#fb923c",
    "red": "#f87171",
    "amber": "#fbbf24",
    "blue": "#60a5fa",
    "indigo": "#818cf8",
}

FONT = "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
MONO = "ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace"

# Simple Icons are monochrome; give each tile its identifiable brand color.
ICON_COLORS = {
    "googlechrome.svg": "#4285F4",
    "traefik.svg": "#24A1C1",
    "react.svg": "#149ECA",
    "fastapi.svg": "#009688",
    "eclipse-theia.svg": "#7C3AED",
    "postgresql.svg": "#336791",
    "redis.svg": "#DC382D",
    "celery.svg": "#37814A",
    "docker.svg": "#2496ED",
    "prometheus.svg": "#E6522C",
    "grafana.svg": "#F46800",
    "sentry.svg": "#362D59",
    "opentelemetry.svg": "#425CC7",
}

# (name, x, y, width, height, accent, icon, title, description lines, badge)
CARDS = [
    (
        "browser",
        55,
        110,
        195,
        132,
        ACCENTS["sky"],
        "googlechrome.svg",
        "Browser",
        ["Dashboard · IDE", "API client"],
        "HTTPS / WS",
    ),
    (
        "traefik",
        330,
        110,
        210,
        132,
        ACCENTS["sky"],
        "traefik.svg",
        "Traefik v3",
        ["Reverse proxy", "TLS · routing"],
        "edge",
    ),
    (
        "spa",
        40,
        285,
        215,
        155,
        ACCENTS["teal"],
        "react.svg",
        "React 19 SPA",
        ["Management dashboard", "and user portal", "Vite · TanStack"],
        "/*",
    ),
    (
        "api",
        285,
        285,
        230,
        155,
        ACCENTS["emerald"],
        "fastapi.svg",
        "FastAPI backend",
        ["Auth · RBAC · orchestration", "billing · metrics", "WebSocket API"],
        "/api/*",
    ),
    (
        "ide",
        548,
        285,
        207,
        155,
        ACCENTS["violet"],
        "eclipse-theia.svg",
        "NukeIDE container",
        ["Per-user environment", "nginx · Theia IDE", "Go auth sidecar"],
        "/user/{name}/*",
    ),
    (
        "postgres",
        58,
        505,
        142,
        140,
        ACCENTS["orange"],
        "postgresql.svg",
        "PostgreSQL 17",
        ["Users · roles · servers", "audit · metrics"],
        "state",
    ),
    (
        "redis",
        208,
        505,
        142,
        140,
        ACCENTS["red"],
        "redis.svg",
        "Redis",
        ["Sessions · pub/sub", "broker · cache"],
        "state",
    ),
    (
        "celery",
        358,
        505,
        165,
        140,
        ACCENTS["amber"],
        "celery.svg",
        "Celery + Beat",
        ["Billing · cleanup", "queue · lifecycle"],
        "jobs",
    ),
    (
        "docker",
        565,
        475,
        190,
        150,
        ACCENTS["blue"],
        "docker.svg",
        "Docker / Podman",
        ["Container engine for", "user environments", "and platform services"],
        "runtime",
    ),
]

OBS_CARDS = [
    ("prometheus", 155, ACCENTS["indigo"], "prometheus.svg", "Prometheus", "Metrics scraping & storage"),
    ("grafana", 270, ACCENTS["indigo"], "grafana.svg", "Grafana", "Dashboards, alerts, Jaeger UI"),
    ("sentry", 385, ACCENTS["indigo"], "sentry.svg", "Sentry / GlitchTip", "Error tracking & PII scrubbing"),
    ("otel", 500, ACCENTS["indigo"], "opentelemetry.svg", "OTel + Jaeger", "Distributed tracing"),
]


def logo_uri(name: str) -> str:
    path = LOGOS / name
    if not path.is_file():
        raise FileNotFoundError(f"missing logo asset: {path}")
    raw = path.read_text(encoding="utf-8")
    color = ICON_COLORS.get(name)
    if color:
        raw = raw.replace("<svg ", f'<svg fill="{color}" ', 1)
    if name == "nukelab.svg":
        # Drop the logo's own theme-dependent background so the mark sits on
        # the generated page background in both variants.
        raw = re.sub(r"<style>.*?</style>", "", raw, flags=re.S)
        raw = re.sub(r'<rect class="bg"[^>]*/>', "", raw)
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def text(x: float, y: float, value: str, size: float, fill: str, **attrs: object) -> str:
    font_family = str(attrs.pop("font_family", FONT))
    extra = " ".join(f'{key.replace("_", "-")}="{escape(str(val), quote=True)}"' for key, val in attrs.items())
    return (
        f'<text x="{x}" y="{y}" font-family="{font_family}" font-size="{size}" fill="{fill}"'
        f'{f" {extra}" if extra else ""}>{escape(value)}</text>'
    )


def card(
    theme: dict[str, str],
    *,
    x: int,
    y: int,
    width: int,
    height: int,
    accent: str,
    icon: str,
    title: str,
    lines: list[str],
    badge: str,
) -> str:
    cx = x + width / 2
    parts = [
        "<g>",
        (
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" '
            f'fill="{theme["card"]}" stroke="{theme["card_border"]}"/>'
        ),
        (
            f'<rect x="{x + 20}" y="{y + 0.5}" width="{width - 40}" height="3" '
            f'rx="1.5" fill="{accent}"/>'
        ),
        (
            f'<rect x="{cx - 20}" y="{y + 14}" width="40" height="40" rx="10" '
            f'fill="{theme["icon_tile"]}" stroke="{theme["icon_border"]}"/>'
        ),
        (
            f'<image href="{logo_uri(icon)}" x="{cx - 12}" y="{y + 26}" width="24" height="24" '
            'preserveAspectRatio="xMidYMid meet"/>'
        ),
        text(cx, y + 72, title, 13, theme["text"], text_anchor="middle", font_weight="700"),
    ]
    for index, line in enumerate(lines):
        parts.append(text(cx, y + 90 + index * 13, line, 10.5, theme["muted"], text_anchor="middle"))
    badge_width = max(46, len(badge) * 5.6 + 14)
    badge_y = y + height - 24
    parts.extend(
        [
            (
                f'<rect x="{cx - badge_width / 2}" y="{badge_y}" width="{badge_width}" height="18" '
                f'rx="5" fill="{theme["badge_bg"]}" stroke="{theme["badge_border"]}"/>'
            ),
            text(
                cx,
                badge_y + 12,
                badge,
                9,
                theme["faint"],
                text_anchor="middle",
                font_family=MONO,
            ),
            "</g>",
        ]
    )
    return "".join(parts)


def obs_card(
    theme: dict[str, str],
    *,
    x: int,
    y: int,
    accent: str,
    icon: str,
    title: str,
    description: str,
) -> str:
    width = 155
    height = 105
    cx = x + width / 2
    return "".join(
        [
            "<g>",
            (
                f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" '
                f'fill="{theme["card"]}" stroke="{theme["card_border"]}"/>'
            ),
            (
                f'<rect x="{x + 16}" y="{y + 0.5}" width="{width - 32}" height="3" '
                f'rx="1.5" fill="{accent}"/>'
            ),
            (
                f'<rect x="{cx - 16}" y="{y + 12}" width="32" height="32" rx="8" '
                f'fill="{theme["icon_tile"]}" stroke="{theme["icon_border"]}"/>'
            ),
            (
                f'<image href="{logo_uri(icon)}" x="{cx - 10}" y="{y + 18}" width="20" height="20" '
                'preserveAspectRatio="xMidYMid meet"/>'
            ),
            text(cx, y + 57, title, 11, theme["text"], text_anchor="middle", font_weight="700"),
            text(cx, y + 73, description, 9, theme["muted"], text_anchor="middle"),
            "</g>",
        ]
    )


def label(theme: dict[str, str], x: float, y: float, value: str, *, size: float = 9, **attrs: object) -> str:
    fill = str(attrs.pop("fill", theme["muted"]))
    attrs.setdefault("text_anchor", "middle")
    return text(x, y, value, size, fill, letter_spacing="0.5", **attrs)


def build(theme_name: str) -> str:
    theme = THEMES[theme_name]
    cards = {name: card(theme, x=x, y=y, width=w, height=h, accent=accent, icon=icon, title=title, lines=lines, badge=badge) for name, x, y, w, h, accent, icon, title, lines, badge in CARDS}
    obs = "".join(
        obs_card(theme, x=800, y=y, accent=accent, icon=icon, title=title, description=description)
        for _, y, accent, icon, title, description in OBS_CARDS
    )
    route_bus = (
        f'<path d="M435 242 V265 M148 265 H652 M148 265 V283 M400 265 V283 M652 265 V283" '
        f'fill="none" stroke="{theme["arrow"]}" stroke-width="1.4" stroke-linecap="round"/>'
        f'<path d="M148 283 V285 M400 283 V285 M652 283 V285" fill="none" '
        f'stroke="{theme["arrow"]}" stroke-width="1.4" marker-end="url(#arrowhead)"/>'
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 700" width="1000" height="700" role="img" aria-labelledby="title desc">
  <title id="title">NukeLab architecture at a glance</title>
  <desc id="desc">Browser traffic reaches Traefik, which routes to the React SPA, FastAPI backend, and NukeIDE containers. The backend and Celery workers use PostgreSQL, Redis, and the container driver for user environments, while the optional observability stack covers the platform.</desc>
  <defs>
    <pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">
      <circle cx="1" cy="1" r="1" fill="{theme["dot"]}" opacity="0.55"/>
    </pattern>
    <marker id="arrowhead" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M0 0 L10 5 L0 10 Z" fill="{theme["arrow"]}"/>
    </marker>
  </defs>
  <rect width="1000" height="700" fill="{theme["bg"]}"/>
  <rect width="1000" height="700" fill="url(#dots)"/>

  <image href="{logo_uri("nukelab.svg")}" x="332" y="15" width="48" height="48" preserveAspectRatio="xMidYMid meet"/>
  {text(395, 42, "NukeLab Architecture", 26, theme["text"], text_anchor="start", font_weight="800", letter_spacing="-0.2")}
  {text(395, 60, "MULTI-USER SCIENTIFIC COMPUTING PLATFORM", 9.5, theme["muted"], text_anchor="start", letter_spacing="1.2")}

  <path d="M250 176 H328" fill="none" stroke="{theme["arrow"]}" stroke-width="1.4" marker-end="url(#arrowhead)"/>
  {label(theme, 289, 168, "HTTPS / WS")}
  {label(theme, 447, 258, "ROUTES", text_anchor="start")}

  {route_bus}
  {label(theme, 154, 279, "/*", text_anchor="start")}
  {label(theme, 406, 279, "/api/*", text_anchor="start")}
  {label(theme, 658, 279, "/user/{name}/*", text_anchor="start")}

  {cards["browser"]}
  {cards["traefik"]}
  {cards["spa"]}
  {cards["api"]}
  {cards["ide"]}

  <path d="M400 440 V468" fill="none" stroke="{theme["arrow"]}" stroke-width="1.4" marker-end="url(#arrowhead)"/>
  {label(theme, 408, 458, "launch · lifecycle", text_anchor="start")}
  <path d="M660 475 V442" fill="none" stroke="{theme["arrow"]}" stroke-width="1.4" marker-end="url(#arrowhead)"/>
  {label(theme, 670, 460, "spawns", text_anchor="start")}
  <path d="M523 575 H563" fill="none" stroke="{theme["arrow"]}" stroke-width="1.4" marker-end="url(#arrowhead)"/>

  <rect x="40" y="470" width="505" height="185" rx="18" fill="{theme["group"]}" stroke="{theme["group_border"]}"/>
  {label(theme, 60, 494, "DATA, STATE & BACKGROUND WORK", text_anchor="start")}
  {cards["postgres"]}
  {cards["redis"]}
  {cards["celery"]}

  {cards["docker"]}

  <rect x="785" y="110" width="185" height="560" rx="18" fill="{theme["group"]}" stroke="{theme["group_border"]}" stroke-dasharray="5 5"/>
  {label(theme, 800, 136, "OBSERVABILITY", text_anchor="start")}
  {label(theme, 800, 150, "OPTIONAL", text_anchor="start", size=8, fill=theme["faint"])}
  {obs}
  {label(theme, 877, 646, "metrics · traces · logs")}
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify checked-in SVGs match this source")
    args = parser.parse_args()

    outputs = {
        "architecture-light.svg": build("light"),
        "architecture-dark.svg": build("dark"),
    }
    failed = False
    for name, content in outputs.items():
        path = ASSETS / name
        if args.check:
            if not path.is_file() or path.read_text() != content:
                print(f"{path} is out of date; run {Path(__file__).name}", file=sys.stderr)
                failed = True
        else:
            path.write_text(content)
            print(f"wrote {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
