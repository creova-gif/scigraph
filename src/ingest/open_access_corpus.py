from scigraph.models import LayoutBlock

OPEN_ACCESS_5_PDF_LAYOUTS: dict[str, tuple[LayoutBlock, ...]] = {
    "arxiv-2401.10101": (
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=40.0,
            x1=558.0,
            y1=95.0,
            text=(
                "Title: Metformin AMPK Activation in Hypoxic Hepatocytes\n"
                "DOI: 10.48550/arXiv.2401.10101\n"
                "Authors: Elena Rostova, Marcus Chen\n"
                "Year: 2024\n"
                "Venue: arXiv q-bio"
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=105.0,
            x1=558.0,
            y1=170.0,
            text=(
                "Abstract: Treatment with Metformin under acute hepatocellular hypoxia "
                "decreased hepatic gluconeogenesis compared with vehicle control "
                "(d = -1.14; n = 64, p = 0.0012)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=320.0,
            y0=190.0,
            x1=558.0,
            y1=340.0,
            text=(
                "Results: Treatment with Metformin under normoxic hepatocyte culture "
                "decreased cellular ATP turnover compared with untreated baseline "
                "(d = -0.62; n = 48, p = 0.0084)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=190.0,
            x1=292.0,
            y1=340.0,
            text=(
                "Methods: Primary hepatocytes were cultured in two-column microfluidics "
                "chambers and assayed at 24 hours across normoxic and hypoxic tension."
            ),
        ),
    ),
    "pmc-10928374": (
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=40.0,
            x1=558.0,
            y1=95.0,
            text=(
                "Title: CRISPR Base Editing of PCSK9 in Hypercholesterolemic Mice\n"
                "DOI: 10.1038/s41586-024-07101-x\n"
                "Authors: Priya Nair, Jonas Lindqvist\n"
                "Year: 2024\n"
                "Venue: Nature"
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=105.0,
            x1=558.0,
            y1=170.0,
            text=(
                "Abstract: Treatment with Adenine Base Editor ABE8e under high-fat diet "
                "decreased plasma LDL cholesterol compared with saline lipid nanoparticles "
                "(reduction = 58%; n = 40, p < 0.0001)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=190.0,
            x1=292.0,
            y1=340.0,
            text=(
                "Methods: Ldlr-heterozygous mice received single-dose LNP-encapsulated "
                "mRNA and sgRNA targeting exon 1 of PCSK9."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=320.0,
            y0=190.0,
            x1=558.0,
            y1=340.0,
            text=(
                "Results: Treatment with Adenine Base Editor ABE8e under high-fat diet "
                "had no significant effect on serum ALT transaminase compared with "
                "saline lipid nanoparticles (n = 40, p = 0.412)."
            ),
        ),
    ),
    "arxiv-2403.08812": (
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=40.0,
            x1=558.0,
            y1=95.0,
            text=(
                "Title: Lithium-Sulfur Cathode Polysulfide Shuttle Suppression via MXene\n"
                "DOI: 10.48550/arXiv.2403.08812\n"
                "Authors: Hao Zhang, Sofia Al-Mansoor\n"
                "Year: 2024\n"
                "Venue: arXiv cond-mat.mtrl-sci"
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=105.0,
            x1=558.0,
            y1=170.0,
            text=(
                "Abstract: Treatment with Ti3C2Tx MXene interlayer under 2C charge cycling "
                "increased specific discharge capacity compared with bare polypropylene separator "
                "(delta = +215 mAh/g; n = 36, p = 0.0004)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=190.0,
            x1=292.0,
            y1=340.0,
            text=(
                "Methods: Coin cells were assembled in argon gloveboxes and cycled across "
                "500 charge-discharge loops at 25 degrees Celsius."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=320.0,
            y0=190.0,
            x1=558.0,
            y1=340.0,
            text=(
                "Results: Treatment with Ti3C2Tx MXene interlayer under 2C charge cycling "
                "decreased cyclic capacity fade rate compared with bare polypropylene separator "
                "(fade = 0.028%/cycle; n = 36, p = 0.0019)."
            ),
        ),
    ),
    "pmc-11044921": (
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=40.0,
            x1=558.0,
            y1=95.0,
            text=(
                "Title: Semaglutide Neuroinflammation Modulation in Murine Microglia\n"
                "DOI: 10.1126/scitranslmed.adn4492\n"
                "Authors: Hannah Lindholm, David Okafor\n"
                "Year: 2024\n"
                "Venue: Science Translational Medicine"
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=105.0,
            x1=558.0,
            y1=170.0,
            text=(
                "Abstract: Treatment with Semaglutide under LPS-induced neuroinflammation "
                "decreased microglial TNF-alpha secretion compared with PBS vehicle "
                "(fold = 0.41x; n = 52, p = 0.0007)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=190.0,
            x1=292.0,
            y1=340.0,
            text=(
                "Methods: Organotypic hippocampal slice cultures were stimulated with "
                "100 ng/mL LPS and quantified by ELISA."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=320.0,
            y0=190.0,
            x1=558.0,
            y1=340.0,
            text=(
                "Results: Treatment with Semaglutide under LPS-induced neuroinflammation "
                "increased hippocampal synaptic PSD95 density compared with PBS vehicle "
                "(d = 0.89; n = 52, p = 0.0031)."
            ),
        ),
    ),
    "arxiv-2405.19204": (
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=40.0,
            x1=558.0,
            y1=95.0,
            text=(
                "Title: Direct Air Capture Amine Sorbent Regeneration Under Humid Flue Streams\n"
                "DOI: 10.48550/arXiv.2405.19204\n"
                "Authors: Lucas Meyer, Mei-Ling Zhou\n"
                "Year: 2024\n"
                "Venue: arXiv physics.chem-ph"
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=105.0,
            x1=558.0,
            y1=170.0,
            text=(
                "Abstract: Treatment with PEI-Silica Sorbent under 65% relative humidity "
                "increased CO2 adsorption capacity compared with dry nitrogen purge "
                "(delta = +1.42 mmol/g; n = 30, p = 0.0021)."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=54.0,
            y0=190.0,
            x1=292.0,
            y1=340.0,
            text=(
                "Methods: Fixed-bed breakthrough reactors were thermally cycled at 95 C "
                "across 30 adsorption-desorption runs."
            ),
        ),
        LayoutBlock(
            page_number=1,
            x0=320.0,
            y0=190.0,
            x1=558.0,
            y1=340.0,
            text=(
                "Results: Treatment with PEI-Silica Sorbent under 130 C oxidative regeneration "
                "decreased CO2 adsorption capacity compared with 90 C steam regeneration "
                "(delta = -0.95 mmol/g; n = 30, p = 0.0015)."
            ),
        ),
    ),
}
