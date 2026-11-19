# Research paper sources

The [final 12-page paper](../Phase4_Research_Paper_24i-2545.pdf) is at the repository root. This directory retains its editable manuscript, bibliography, Springer template files, final figures, and supporting summary data.

- [Manuscript](source/paper.tex)
- [References](source/references.bib)
- [Figures](source/figures/)
- [Saved summary data](evidence/)
- [Setup and experimental evidence](../docs/REPRODUCIBILITY.md)

Upload the contents of `source/` to Overleaf and select `paper.tex` as the main document. With a complete TeX Live installation, the manuscript can also be compiled directly:

```sh
cd source
pdflatex paper.tex
bibtex paper
pdflatex paper.tex
pdflatex paper.tex
```

Muhammad Umair Ahmad · 24i-2545 · Section AI-C<br>
Department of Artificial Intelligence, FAST NUCES, Islamabad<br>
[i242545@isb.nu.edu.pk](mailto:i242545@isb.nu.edu.pk)
