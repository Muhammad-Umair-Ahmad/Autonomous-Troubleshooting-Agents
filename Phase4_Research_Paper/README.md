# Phase 4 research paper

The manuscript uses the supplied Springer Nature class, its supported two-column layout, and numbered mathematical/physical-sciences references. Author: Muhammad Umair Ahmad, 24i-2545, Section AI-C.

- `Phase4_Research_Paper_24i-2545.pdf`: compiled manuscript.
- `source/paper.tex`: editable manuscript, with all sections in one file.
- `source/references.bib`: editable bibliography.
- `source/figures/`: vector figures and editable TikZ/PGFPlots sources.
- `evidence/`: original saved summaries, paired statistics, revised outcomes, and a numerical audit.
- `REPRODUCIBILITY.md`: experimental replay and evidence locations.
- `build_evidence.py`: standard-library Python audit and figure-source generator. Run from the unchanged Phase 3 parent folder.

Build the manuscript with `sh source/build.sh`. A complete TeX Live installation with BibTeX, TikZ/PGFPlots, and the packages named in `paper.tex` is required. The supplied Springer class and bibliography style are included. Upload the `source/` contents to Overleaf and select `paper.tex` as the main document to edit online.

The manuscript preserves the distinction between the original matched study and the revised exploratory follow-up. Published base-paper scores are marked as such; local SADE measurements are explicitly identified as an adaptation. No experimental results were invented or rerun for this paper.

Contact: [i242545@isb.nu.edu.pk](mailto:i242545@isb.nu.edu.pk). The code and complete experimental artifact are available in the [project repository](https://github.com/Muhammad-Umair-Ahmad/Autonomous-Troubleshooting-Agents). Institutional affiliation remains to be supplied. Review the manuscript and declarations before submission; AI-writing assistance is declared.

The humanizer pass reviewed the abstract and all 10 sections. The prose-preservation report in `evidence/prose-preservation.json` records checks that the LaTeX command sequence, equations, tables, figures, pseudocode, numbers, citations, and labels were preserved. The author email and repository URL were added separately as requested.
