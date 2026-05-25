"""
PDF report generation via reportlab.

v4.0: Styled PDF reports for matches, ranking, and players data.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ACCENT = HexColor("#00d4aa")
DARK = HexColor("#0a0e17")
LIGHT = HexColor("#f8fafc")
MUTED = HexColor("#94a3b8")


async def generate_pdf_report(
    client: Any, data_type: str, page: int = 1,
) -> bytes:
    """Generate a styled PDF report from HLTV data.

    Args:
        client: HLTVClient instance.
        data_type: 'matches', 'ranking', or 'players'.
        page: Page number for paginated data.

    Returns:
        PDF file as bytes.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        textColor=ACCENT, fontSize=22, spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ReportSub", parent=styles["Normal"],
        fontSize=9, textColor=MUTED, spaceAfter=16,
    )
    header_style = ParagraphStyle(
        "TblHeader", parent=styles["Normal"],
        fontSize=9, textColor=LIGHT, fontName="Helvetica-Bold",
    )
    cell_style = ParagraphStyle(
        "TblCell", parent=styles["Normal"],
        fontSize=8, textColor=HexColor("#1e293b"),
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    story = [
        Paragraph(
            f"HLTV Pro v4.0 — {data_type.title()} Report",
            title_style,
        ),
        Paragraph(
            f"Generated: {now} | Data source: HLTV.org",
            subtitle_style,
        ),
        Spacer(1, 0.2 * inch),
    ]

    if data_type == "ranking":
        from src.endpoints.teams import TeamsEndpoint

        ranking_data = await TeamsEndpoint(client).get_ranking()
        teams = ranking_data.teams or []

        table_data = [
            [
                Paragraph("Rank", header_style),
                Paragraph("Team", header_style),
                Paragraph("Points", header_style),
                Paragraph("Change", header_style),
            ],
        ]
        for team in teams[:50]:
            change = (
                f"+{team.change}"
                if team.change and team.change > 0
                else str(team.change or "-")
            )
            table_data.append([
                Paragraph(str(team.rank), cell_style),
                Paragraph(team.name, cell_style),
                Paragraph(str(team.points), cell_style),
                Paragraph(change, cell_style),
            ])

        tbl = Table(
            table_data,
            colWidths=[0.6 * inch, 3.8 * inch, 0.8 * inch, 0.8 * inch],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), LIGHT),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
            (
                "ROWBACKGROUNDS", (0, 1), (-1, -1),
                [HexColor("#ffffff"), HexColor("#f8fafc")],
            ),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(tbl)

    elif data_type == "matches":
        from src.endpoints.matches import MatchesEndpoint

        matches_data = await MatchesEndpoint(client).get_results(page=page)

        table_data = [
            [
                Paragraph("Date", header_style),
                Paragraph("Team 1", header_style),
                Paragraph("Score", header_style),
                Paragraph("Team 2", header_style),
                Paragraph("Event", header_style),
            ],
        ]
        for match in (matches_data or [])[:30]:
            date_str = (
                match.date.strftime("%Y-%m-%d")
                if hasattr(match, "date") and match.date
                else "-"
            )
            s1 = getattr(match.team1, "score", None)
            s2 = getattr(match.team2, "score", None)
            score = f"{s1 or '-'} - {s2 or '-'}"
            evt = (
                match.event.name
                if hasattr(match, "event") and match.event
                else "-"
            )
            table_data.append([
                Paragraph(date_str, cell_style),
                Paragraph(match.team1.name, cell_style),
                Paragraph(score, cell_style),
                Paragraph(match.team2.name, cell_style),
                Paragraph(evt, cell_style),
            ])

        tbl = Table(
            table_data,
            colWidths=[
                0.9 * inch, 1.6 * inch, 0.7 * inch,
                1.6 * inch, 1.2 * inch,
            ],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
            (
                "ROWBACKGROUNDS", (0, 1), (-1, -1),
                [HexColor("#ffffff"), HexColor("#f8fafc")],
            ),
        ]))
        story.append(tbl)

    elif data_type == "players":
        from src.endpoints.players import PlayersEndpoint

        players_data = await PlayersEndpoint(client).get_top_players("last3months")
        players = players_data.players if hasattr(players_data, "players") else []

        table_data = [
            [
                Paragraph("Rank", header_style),
                Paragraph("Player", header_style),
                Paragraph("Team", header_style),
                Paragraph("Rating", header_style),
                Paragraph("Maps", header_style),
            ],
        ]
        for p in players[:50]:
            player_name = getattr(p.player, "name", "—") if p.player else "—"
            team_name = getattr(p.team, "name", "—") if p.team else "—"
            table_data.append([
                Paragraph(str(p.rank), cell_style),
                Paragraph(player_name, cell_style),
                Paragraph(team_name, cell_style),
                Paragraph(f"{p.rating:.2f}", cell_style),
                Paragraph(str(p.maps_played), cell_style),
            ])

        tbl = Table(
            table_data,
            colWidths=[
                0.6 * inch, 2.4 * inch, 1.8 * inch,
                0.8 * inch, 0.6 * inch,
            ],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), LIGHT),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e2e8f0")),
            (
                "ROWBACKGROUNDS", (0, 1), (-1, -1),
                [HexColor("#ffffff"), HexColor("#f8fafc")],
            ),
        ]))
        story.append(tbl)

    doc.build(story)
    return buffer.getvalue()
