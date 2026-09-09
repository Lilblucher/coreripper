"""Branded PDF documents (invoices, diagnostic reports).

One module so every PDF the site emits shares a page frame, palette and type
scale - a receipt emailed by `payments` and a client report downloaded from the
Workbench should look like they came from the same company.

Built on reportlab's platypus (already installed; no new dependency). Two
deliberate constraints:

- **No external assets.** The logo is drawn as vector geometry and the type is
  a built-in PDF base-14 font, so rendering never depends on a font file, a
  network fetch or MEDIA_ROOT being present. This runs inside a Celery worker
  and inside a request; neither can afford a missing-file crash.
- **Print palette, not screen palette.** The site is dark-themed (#0a0a0a);
  a PDF is usually printed or read in a white viewer, so these use the brand
  blue as an accent on white rather than inverting the site.

Callers get `bytes` and decide what to do with them (HTTP response, email
attachment), so nothing here touches the filesystem.
"""

from __future__ import annotations

import io
from datetime import datetime

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# --- Brand -----------------------------------------------------------------
# Mirrors the site's tokens (primary #2597e8 / secondary #15a6de), re-grounded
# for white paper: near-black body text instead of the site's #e5e7eb.
BRAND = colors.HexColor("#2597e8")
BRAND_DARK = colors.HexColor("#1a6fae")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
HAIRLINE = colors.HexColor("#e5e7eb")
WASH = colors.HexColor("#f6f9fc")
OK_GREEN = colors.HexColor("#15803d")
WARN_RED = colors.HexColor("#b91c1c")

PAGE_MARGIN = 18 * mm
HEADER_H = 26 * mm
FOOTER_H = 14 * mm

COMPANY_NAME = "CoreRipper"
COMPANY_SITE = "coreripper.site"


def _styles():
    """Type scale. Helvetica is a base-14 font, so it needs no embedding - the
    site's Space Grotesk would require shipping a TTF and would fail closed on
    a box where it's missing, which is not a trade worth making for a receipt."""
    base = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK
    )
    return {
        "body": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=MUTED, fontSize=8.5, leading=12),
        "h1": ParagraphStyle(
            "h1", parent=base, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=2
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName="Helvetica-Bold", fontSize=11, leading=15,
            textColor=BRAND_DARK, spaceBefore=10, spaceAfter=5,
        ),
        "label": ParagraphStyle(
            "label", parent=base, fontName="Helvetica-Bold", fontSize=7.5, leading=10,
            textColor=MUTED,
        ),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "rightbig": ParagraphStyle(
            "rightbig", parent=base, alignment=TA_RIGHT, fontName="Helvetica-Bold", fontSize=15,
            leading=19,
        ),
        "mono": ParagraphStyle(
            "mono", parent=base, fontName="Courier", fontSize=8, leading=10.5, textColor=INK
        ),
        "prose": ParagraphStyle("prose", parent=base, fontSize=10, leading=15.5, spaceAfter=7),
    }


# The site's logo mark, transcribed from the inline SVG in the page headers:
# an outlined pointy-top hexagon with a "pulse" trace running through it, on a
# 64x64 viewBox. Kept as raw viewBox coordinates so it stays comparable to the
# markup it came from; _logo_mark does the conversion. Note SVG's y axis points
# down and PDF's points up, hence the flip below.
_HEX_PATH = [(32, 6), (52, 18), (52, 46), (32, 58), (12, 46), (12, 18)]
_PULSE_PATH = [(4, 36), (24, 20), (34, 46), (60, 18)]


def _logo_mark(canvas, cx, cy, size):
    """Draw the CoreRipper hexagon+pulse mark centred on (cx, cy), `size` points
    across. Vector, so it stays sharp at any zoom and needs no image file or
    font - this has to render inside a Celery worker as reliably as in a
    request."""
    scale = size / 64.0

    def pt(x, y):
        return (cx + (x - 32) * scale, cy + (32 - y) * scale)

    canvas.setLineWidth(4 * scale)
    canvas.setLineCap(1)   # round - matches stroke-linecap in the SVG
    canvas.setLineJoin(1)  # round

    canvas.setStrokeColor(BRAND)
    hexagon = canvas.beginPath()
    hexagon.moveTo(*pt(*_HEX_PATH[0]))
    for p in _HEX_PATH[1:]:
        hexagon.lineTo(*pt(*p))
    hexagon.close()
    canvas.drawPath(hexagon, stroke=1, fill=0)

    canvas.setStrokeColor(colors.HexColor("#15a6de"))
    canvas.setLineWidth(6 * scale)
    pulse = canvas.beginPath()
    pulse.moveTo(*pt(*_PULSE_PATH[0]))
    for p in _PULSE_PATH[1:]:
        pulse.lineTo(*pt(*p))
    canvas.drawPath(pulse, stroke=1, fill=0)


def _page_furniture(doc_title):
    """The header/footer painted on every page. Returned as a closure because
    reportlab's onPage hook takes (canvas, doc) only - the title has to ride in
    from the caller somehow."""

    def draw(canvas, doc):
        canvas.saveState()
        w, h = A4

        # Header: mark + wordmark on the left, document title on the right,
        # over a thin brand rule.
        _logo_mark(canvas, PAGE_MARGIN + 4.5 * mm, h - PAGE_MARGIN - 5.5 * mm, 10 * mm)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.setFillColor(INK)
        canvas.drawString(PAGE_MARGIN + 12 * mm, h - PAGE_MARGIN - 7 * mm, COMPANY_NAME)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(PAGE_MARGIN + 12 * mm, h - PAGE_MARGIN - 10.5 * mm, COMPANY_SITE)

        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(BRAND_DARK)
        canvas.drawRightString(w - PAGE_MARGIN, h - PAGE_MARGIN - 7 * mm, doc_title.upper())

        canvas.setStrokeColor(BRAND)
        canvas.setLineWidth(1.6)
        y_rule = h - PAGE_MARGIN - 14 * mm
        canvas.line(PAGE_MARGIN, y_rule, w - PAGE_MARGIN, y_rule)

        # Footer: hairline, generation stamp left, page number right.
        canvas.setStrokeColor(HAIRLINE)
        canvas.setLineWidth(0.6)
        canvas.line(PAGE_MARGIN, FOOTER_H, w - PAGE_MARGIN, FOOTER_H)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        stamp = timezone.localtime().strftime("%d %b %Y at %H:%M %Z")
        canvas.drawString(PAGE_MARGIN, FOOTER_H - 5 * mm, f"Generated {stamp} by {COMPANY_SITE}")
        canvas.drawRightString(w - PAGE_MARGIN, FOOTER_H - 5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _render(story, doc_title, pdf_title):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN + HEADER_H - 8 * mm,
        bottomMargin=FOOTER_H + 8 * mm,
        title=pdf_title,
        author=COMPANY_NAME,
        subject=doc_title,
    )
    furniture = _page_furniture(doc_title)
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue()


def _kv_table(rows, col_widths=(38 * mm, 60 * mm)):
    """Label/value pairs - the shape used for both the invoice meta block and
    the report's scan summary."""
    st = _styles()
    data = [[Paragraph(k.upper(), st["label"]), Paragraph(str(v), st["body"])] for k, v in rows]
    t = Table(data, colWidths=list(col_widths))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _esc(value):
    """Paragraph() parses a mini-HTML dialect, so raw user data (a target like
    `a<b`, a JSON blob full of quotes) has to be escaped or it silently
    truncates the paragraph - or raises - at render time."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# --- Invoices ---------------------------------------------------------------

METHOD_NAMES = {
    "mtn_momo": "MTN Mobile Money",
    "airtel_money": "Airtel Money",
    "card": "Card",
}


def invoice_number(payment):
    """Stable, human-quotable identifier. Derived from the row id rather than a
    separate counter column: payment ids are already unique and monotonic, and
    a second sequence would be one more thing to keep consistent."""
    year = (payment.created_at or timezone.now()).strftime("%Y")
    return f"CR-{year}-{payment.pk or 0:05d}"


def build_invoice_pdf(payment):
    """A payment receipt as a PDF. Every figure is read off the Payment row's
    own snapshot (amount/currency/credits_amount), never recomputed from the
    current price or today's FX rate - see the "rate snapshots are forever"
    rule in CLAUDE.md. A reprint of a two-year-old receipt must show what was
    actually charged."""
    st = _styles()
    user = payment.user
    is_pack = bool(payment.pack_id or payment.credits_amount)
    priced = payment.pack if is_pack else payment.price

    if is_pack:
        item = payment.pack.label if payment.pack else "Sonnet-5 credit pack"
        item_detail = f"{payment.credits_amount} Sonnet-5 credits, valid for 12 months from purchase"
    else:
        item = payment.price.label if payment.price else "CoreRipper subscription"
        item_detail = f"Subscription access for {payment.period_days} days"

    paid = payment.status == "paid"
    story = []

    # Title block: what this is, and the headline amount.
    amount_str = (
        f"${payment.amount} USD" if payment.currency == "USD"
        else f"K{payment.amount} {payment.currency}"
    )
    head = Table(
        [[
            Paragraph("Receipt", st["h1"]),
            Paragraph(amount_str, st["rightbig"]),
        ], [
            Paragraph(
                "Paid in full - thank you." if paid else "Awaiting payment confirmation.",
                st["muted"],
            ),
            Paragraph(
                f'<font color="{"#15803d" if paid else "#b91c1c"}"><b>'
                f'{"PAID" if paid else payment.get_status_display().upper()}</b></font>',
                st["right"],
            ),
        ]],
        colWidths=[110 * mm, 64 * mm],
    )
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
    ]))
    story += [head, Spacer(1, 7 * mm)]

    # Billed-to / invoice meta, side by side.
    name = (user.get_full_name() or "").strip()
    company = getattr(getattr(user, "profile", None), "company", "") or ""
    bill_to = [line for line in (name, company, user.email) if line]
    left = [Paragraph("BILLED TO", st["label"]), Spacer(1, 1.5 * mm)]
    left += [Paragraph(_esc(line), st["body"]) for line in bill_to]

    meta = [
        ("Invoice no.", invoice_number(payment)),
        ("Date", (payment.created_at or timezone.now()).strftime("%d %b %Y")),
        ("Payment method", METHOD_NAMES.get(payment.method, payment.method or payment.provider)),
    ]
    if payment.provider_ref:
        meta.append(("Reference", _esc(payment.provider_ref)))

    cols = Table([[left, _kv_table(meta, col_widths=(30 * mm, 44 * mm))]],
                 colWidths=[96 * mm, 78 * mm])
    cols.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [cols, Spacer(1, 8 * mm)]

    # Line items.
    line_rows = [
        [Paragraph("DESCRIPTION", st["label"]), Paragraph("AMOUNT", ParagraphStyle(
            "lr", parent=st["label"], alignment=TA_RIGHT))],
        [
            Paragraph(f"<b>{_esc(item)}</b><br/><font size=8.5 color='#6b7280'>{_esc(item_detail)}</font>",
                      st["body"]),
            Paragraph(amount_str, st["right"]),
        ],
    ]
    items = Table(line_rows, colWidths=[128 * mm, 46 * mm])
    items.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, BRAND),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [items, Spacer(1, 3 * mm)]

    total = Table(
        [[Paragraph("<b>Total paid</b>" if paid else "<b>Total due</b>", st["right"]),
          Paragraph(f"<b>{amount_str}</b>", st["right"])]],
        colWidths=[128 * mm, 46 * mm],
    )
    total.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WASH),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(total)

    # A ZMW charge is derived from a USD list price, so the receipt states the
    # USD equivalent that was advertised - without implying it's re-convertible
    # at today's rate.
    if payment.currency != "USD" and priced is not None:
        story += [
            Spacer(1, 3 * mm),
            Paragraph(
                f"Charged in {payment.currency} at the exchange rate on the date of purchase. "
                f"List price ${priced.display_amount_usd} USD.",
                st["muted"],
            ),
        ]

    story += [Spacer(1, 10 * mm)]
    if is_pack:
        closing = (
            "Your Sonnet-5 credits are already in your wallet and are spent only when you "
            "choose the Sonnet-5 model. They expire 12 months from the date above."
        )
    else:
        sub = getattr(user, "subscription", None)
        until = sub.current_period_end or sub.expires_at if sub else None
        closing = (
            "Your subscription is active"
            + (f" until {until.strftime('%d %b %Y')}." if until else ".")
            + " You can review this and every earlier invoice on your Billing page."
        )
    story += [
        Paragraph(closing, st["muted"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Questions about this receipt? Reply to this email or contact billing@{COMPANY_SITE}.",
            st["muted"],
        ),
    ]

    return _render(story, "Receipt", f"CoreRipper receipt {invoice_number(payment)}")


# --- Diagnostic reports -----------------------------------------------------

def _summarise(result_json):
    """One short line describing a tool result, for the findings table.

    Tool results have no common schema (each network tool returns its own
    dict), so this reads the handful of keys that recur and otherwise falls
    back to a truncated dump - an honest, if terse, row beats guessing at a
    structure that isn't there."""
    if not isinstance(result_json, dict):
        text = str(result_json)
        return text[:160] + ("" if len(text) <= 160 else "...")

    for key in ("status_code", "grade", "loss_pct", "status", "message", "summary"):
        if key in result_json and result_json[key] not in (None, ""):
            return f"{key.replace('_', ' ')}: {result_json[key]}"
    if result_json.get("error"):
        return f"error: {result_json['error']}"
    keys = ", ".join(list(result_json)[:6])
    return f"returned {len(result_json)} field(s): {keys}"


def build_report_pdf(*, title, target, narrative, results, prepared_for=""):
    """A client-ready diagnostic report: the AI narrative as prose, then a
    table of every tool result it was written from, then the raw payloads as an
    appendix.

    The appendix matters - a report that only paraphrases its evidence can't be
    audited by whoever receives it, and this is a document a Workbench user
    hands to their own client.

    `results` is a list of dicts with tool_key / target / created_at /
    result_json, i.e. the shape dashboard's `_result_json` already produces.
    """
    st = _styles()
    story = []

    story += [
        Paragraph(_esc(title), st["h1"]),
        Paragraph(
            f"Diagnostic findings for <b>{_esc(target)}</b>" if target else "Diagnostic findings",
            st["muted"],
        ),
        Spacer(1, 6 * mm),
    ]

    meta = [
        ("Report date", timezone.localtime().strftime("%d %b %Y")),
        ("Checks run", str(len(results))),
    ]
    if target:
        meta.insert(0, ("Target", _esc(target)))
    if prepared_for:
        meta.append(("Prepared for", _esc(prepared_for)))
    story += [_kv_table(meta), Spacer(1, 7 * mm)]

    if narrative:
        story.append(Paragraph("Summary", st["h2"]))
        for para in [p.strip() for p in narrative.split("\n") if p.strip()]:
            story.append(Paragraph(_esc(para), st["prose"]))
        story.append(Spacer(1, 3 * mm))

    if results:
        story.append(Paragraph("Checks performed", st["h2"]))
        rows = [[
            Paragraph("CHECK", st["label"]),
            Paragraph("TARGET", st["label"]),
            Paragraph("RESULT", st["label"]),
            Paragraph("RUN", st["label"]),
        ]]
        for r in results:
            created = r.get("created_at") or ""
            if isinstance(created, str) and len(created) >= 10:
                created = created[:10]
            elif isinstance(created, datetime):
                created = created.strftime("%Y-%m-%d")
            rows.append([
                Paragraph(_esc(r.get("tool_key", "")), st["body"]),
                Paragraph(_esc(r.get("target", "") or "-"), st["body"]),
                Paragraph(_esc(_summarise(r.get("result_json"))), st["body"]),
                Paragraph(_esc(created), st["muted"]),
            ])
        table = Table(rows, colWidths=[36 * mm, 42 * mm, 74 * mm, 22 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, BRAND),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, HAIRLINE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, WASH]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

        story += [PageBreak(), Paragraph("Appendix: raw results", st["h2"]),
                  Paragraph(
                      "The complete, unedited output of each check, exactly as the tool "
                      "returned it.", st["muted"]),
                  Spacer(1, 4 * mm)]
        import json as _json
        for r in results:
            payload = _json.dumps(r.get("result_json"), indent=2, ensure_ascii=False, default=str)
            # Long single-token payloads (a base64 blob, a huge header string)
            # won't wrap on their own and would overflow the frame silently.
            wrapped = "\n".join(
                line if len(line) <= 96 else "\n".join(
                    line[i:i + 96] for i in range(0, len(line), 96))
                for line in payload.splitlines()
            )
            block = [
                Paragraph(
                    f"<b>{_esc(r.get('tool_key', ''))}</b> - {_esc(r.get('target', '') or '-')}",
                    st["body"],
                ),
                Spacer(1, 1.5 * mm),
                Paragraph(_esc(wrapped).replace("\n", "<br/>"), st["mono"]),
                Spacer(1, 5 * mm),
            ]
            # Keep a short payload with its heading; let a long one flow.
            story.append(KeepTogether(block) if len(wrapped) < 1200 else block[0])
            if len(wrapped) >= 1200:
                story += block[1:]

    story += [
        Spacer(1, 6 * mm),
        Paragraph(
            "Prepared with CoreRipper. Findings reflect the state of the target at the "
            "time each check ran and may change.",
            st["muted"],
        ),
    ]
    return _render(story, "Report", f"CoreRipper report - {title}")
