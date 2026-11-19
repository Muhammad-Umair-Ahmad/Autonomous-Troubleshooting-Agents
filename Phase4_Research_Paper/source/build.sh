#!/bin/sh
set -eu
cd "$(dirname "$0")"
for name in architecture performance ablation case-trace; do
  pdflatex -interaction=nonstopmode -halt-on-error -output-directory figures "figures/$name.tex" > "figures/$name-build.log"
done
pdflatex -interaction=nonstopmode -halt-on-error paper.tex > paper-build.log
bibtex paper > bibliography-build.log
pdflatex -interaction=nonstopmode -halt-on-error paper.tex > paper-build.log
pdflatex -interaction=nonstopmode -halt-on-error paper.tex > paper-build.log
