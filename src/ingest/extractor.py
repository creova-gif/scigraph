import re
from collections.abc import Sequence

from scigraph.models import (
    ClaimTuple,
    ComparisonOperator,
    EffectDirection,
    EvidenceSpan,
    LayoutBlock,
    Paper,
    PaperSection,
    ScientificClaim,
    SectionKind,
    StatisticalEvidence,
)

_HEADING_MAP: dict[str, SectionKind] = {
    "abstract": SectionKind.ABSTRACT,
    "introduction": SectionKind.INTRODUCTION,
    "methods": SectionKind.METHODS,
    "materials and methods": SectionKind.METHODS,
    "results": SectionKind.RESULTS,
    "discussion": SectionKind.DISCUSSION,
}

_DIRECTION_VERBS: dict[str, EffectDirection] = {
    "increased": EffectDirection.INCREASES,
    "elevated": EffectDirection.INCREASES,
    "improved": EffectDirection.INCREASES,
    "enhanced": EffectDirection.INCREASES,
    "accelerated": EffectDirection.INCREASES,
    "upregulated": EffectDirection.INCREASES,
    "decreased": EffectDirection.DECREASES,
    "reduced": EffectDirection.DECREASES,
    "suppressed": EffectDirection.DECREASES,
    "inhibited": EffectDirection.DECREASES,
    "attenuated": EffectDirection.DECREASES,
    "lowered": EffectDirection.DECREASES,
    "did not significantly alter": EffectDirection.NO_EFFECT,
    "had no significant effect on": EffectDirection.NO_EFFECT,
    "showed no significant change in": EffectDirection.NO_EFFECT,
}

_PROSE_CLAIM_PATTERN = re.compile(
    r"Treatment with (?P<intervention>[^,;]+?) under (?P<condition>[^,;]+?) "
    r"(?P<verb>increased|elevated|improved|enhanced|accelerated|upregulated|"
    r"decreased|reduced|suppressed|inhibited|attenuated|lowered|"
    r"did not significantly alter|had no significant effect on|showed no significant change in) "
    r"(?P<outcome>[^,;()]+?) compared with (?P<comparator>[^,;()]+?) "
    r"\((?:(?P<effect>[^;()]+?);\s*)?(?P<n_raw>[nN]\s*=\s*(?P<n_val>\d+)),\s*"
    r"(?P<p_raw>p\s*(?P<p_op><=|>=|<|=)\s*(?P<p_val>0?\.\d+))\)\."
)

_PDF_BLOCK_PATTERN = re.compile(
    r"BT\s+/F1\s+\d+\s+Tf\s+"
    r"(?P<x0>\d+(?:\.\d+)?)\s+(?P<y0>\d+(?:\.\d+)?)\s+"
    r"(?P<x1>\d+(?:\.\d+)?)\s+(?P<y1>\d+(?:\.\d+)?)\s+"
    r"(?P<page>\d+)\s+Tm\s+\((?P<text>(?:\\.|[^\\)])*)\)\s+Tj\s+ET",
    re.DOTALL,
)


def normalize_pdf_text(text: str) -> str:
    replaced = (
        text.replace("\ufb01", "fi")
        .replace("\ufb02", "fl")
        .replace("\u2212", "-")
        .replace("\u2013", "-")
        .replace("\u2264", "<=")
    )
    return replaced.strip()


def order_layout_blocks(
    blocks: Sequence[LayoutBlock],
    page_width: float = 612.0,
) -> tuple[LayoutBlock, ...]:
    midline = page_width / 2.0
    pages: dict[int, list[LayoutBlock]] = {}
    for block in blocks:
        pages.setdefault(block.page_number, []).append(block)

    ordered: list[LayoutBlock] = []
    for page_num in sorted(pages):
        page_blocks = pages[page_num]
        spanning_top: list[LayoutBlock] = []
        left_col: list[LayoutBlock] = []
        right_col: list[LayoutBlock] = []
        spanning_bottom: list[LayoutBlock] = []

        column_y_min = min(
            (
                b.y0
                for b in page_blocks
                if (b.x1 - b.x0) <= page_width * 0.55
            ),
            default=float("inf"),
        )

        for block in page_blocks:
            width = block.x1 - block.x0
            if width > page_width * 0.55:
                if block.y0 <= column_y_min:
                    spanning_top.append(block)
                else:
                    spanning_bottom.append(block)
            elif block.x0 < midline and block.x1 <= page_width * 0.58:
                left_col.append(block)
            else:
                right_col.append(block)

        spanning_top.sort(key=lambda b: (b.y0, b.x0))
        left_col.sort(key=lambda b: (b.y0, b.x0))
        right_col.sort(key=lambda b: (b.y0, b.x0))
        spanning_bottom.sort(key=lambda b: (b.y0, b.x0))

        ordered.extend(spanning_top)
        ordered.extend(left_col)
        ordered.extend(right_col)
        ordered.extend(spanning_bottom)

    return tuple(ordered)


def extract_paper_from_layout(
    paper_id: str,
    blocks: Sequence[LayoutBlock],
    page_width: float = 612.0,
) -> Paper:
    ordered_blocks = order_layout_blocks(blocks, page_width=page_width)
    normalized_texts = [normalize_pdf_text(b.text) for b in ordered_blocks]
    full_text = "\n\n".join(normalized_texts)

    doi_match = re.search(r"DOI:\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", full_text)
    if doi_match is None:
        raise ValueError(f"Missing verbatim DOI header in paper {paper_id}")
    doi = doi_match.group(1)

    title_match = re.search(r"Title:\s*(.+)", full_text)
    title = title_match.group(1).strip() if title_match else paper_id

    authors_match = re.search(r"Authors:\s*(.+)", full_text)
    authors_raw = authors_match.group(1).strip() if authors_match else "Unknown Author"
    authors = tuple(a.strip() for a in authors_raw.split(",") if a.strip())

    year_match = re.search(r"Year:\s*(\d{4})", full_text)
    year = int(year_match.group(1)) if year_match else 2026

    venue_match = re.search(r"Venue:\s*(.+)", full_text)
    venue = venue_match.group(1).strip() if venue_match else "arXiv"

    sections: list[PaperSection] = []
    cursor = 0
    for block_text in normalized_texts:
        pos = full_text.find(block_text, cursor)
        if pos == -1:
            continue
        end_pos = pos + len(block_text)
        cursor = end_pos

        colon_idx = block_text.find(":")
        if colon_idx != -1:
            heading_candidate = block_text[:colon_idx].strip().lower()
            if heading_candidate in _HEADING_MAP:
                sections.append(
                    PaperSection(
                        kind=_HEADING_MAP[heading_candidate],
                        heading=block_text[:colon_idx].strip(),
                        text=block_text,
                        start_char=pos,
                        end_char=end_pos,
                    )
                )

    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        authors=authors,
        publication_year=year,
        venue=venue,
        full_text=full_text,
        sections=tuple(sections),
    )


def render_blocks_to_pdf_bytes(
    blocks: Sequence[LayoutBlock],
    page_width: float = 612.0,
    page_height: float = 792.0,
) -> bytes:
    lines: list[str] = [
        "%PDF-1.4",
        f"%%PageSetup {page_width:.1f} {page_height:.1f}",
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        "stream",
    ]
    for block in blocks:
        escaped = (
            block.text.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )
        lines.append(
            f"BT /F1 10 Tf {block.x0:.1f} {block.y0:.1f} "
            f"{block.x1:.1f} {block.y1:.1f} {block.page_number} Tm "
            f"({escaped}) Tj ET"
        )
    lines.append("endstream")
    lines.append("%%EOF")
    return "\n".join(lines).encode("utf-8")


def extract_paper_from_pdf_bytes(
    paper_id: str,
    pdf_bytes: bytes,
    page_width: float = 612.0,
) -> Paper:
    decoded = pdf_bytes.decode("utf-8")
    blocks: list[LayoutBlock] = []
    for match in _PDF_BLOCK_PATTERN.finditer(decoded):
        raw_text = (
            match.group("text")
            .replace("\\(", "(")
            .replace("\\)", ")")
            .replace("\\\\", "\\")
        )
        blocks.append(
            LayoutBlock(
                page_number=int(match.group("page")),
                x0=float(match.group("x0")),
                y0=float(match.group("y0")),
                x1=float(match.group("x1")),
                y1=float(match.group("y1")),
                text=raw_text,
            )
        )
    if not blocks:
        raise ValueError(f"No layout blocks found in PDF stream for {paper_id}")
    return extract_paper_from_layout(paper_id=paper_id, blocks=blocks, page_width=page_width)


def extract_claims_from_paper(paper: Paper) -> tuple[ScientificClaim, ...]:
    claims: list[ScientificClaim] = []
    claim_index = 1

    for match in _PROSE_CLAIM_PATTERN.finditer(paper.full_text):
        start_char = match.start()
        end_char = match.end()
        verbatim_text = paper.full_text[start_char:end_char]

        section_kind = _resolve_section_for_offset(paper, start_char)
        verb = match.group("verb")
        direction = _DIRECTION_VERBS[verb]

        p_op_str = match.group("p_op")
        if p_op_str == "=":
            p_operator = ComparisonOperator.EQ
        elif p_op_str == "<":
            p_operator = ComparisonOperator.LT
        else:
            p_operator = ComparisonOperator.LE

        effect_raw = match.group("effect")
        claims.append(
            ScientificClaim(
                claim_id=f"{paper.paper_id}-c{claim_index}",
                paper_id=paper.paper_id,
                doi=paper.doi,
                claim_tuple=ClaimTuple(
                    intervention=match.group("intervention").strip(),
                    condition=match.group("condition").strip(),
                    outcome=match.group("outcome").strip(),
                    direction=direction,
                    comparator=match.group("comparator").strip(),
                ),
                statistics=StatisticalEvidence(
                    p_operator=p_operator,
                    p_value=float(match.group("p_val")),
                    p_value_raw=match.group("p_raw").strip(),
                    sample_size=int(match.group("n_val")),
                    sample_size_raw=match.group("n_raw").strip(),
                    effect_size_raw=effect_raw.strip() if effect_raw else None,
                ),
                evidence_span=EvidenceSpan(
                    section=section_kind,
                    start_char=start_char,
                    end_char=end_char,
                    verbatim_text=verbatim_text,
                ),
            )
        )
        claim_index += 1

    return tuple(claims)


def _resolve_section_for_offset(paper: Paper, offset: int) -> SectionKind:
    for section in paper.sections:
        if section.start_char <= offset < section.end_char:
            return section.kind
    return SectionKind.RESULTS
