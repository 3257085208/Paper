# JNSM submission package — checklist (v3, 2026-10-14)

## Files
- **`JNSM_manuscript.docx`** — primary editable source (required by JNSM): 31 figures embedded,
  24 real Word tables and 185 native Office Math objects, title page with affiliation (Fuzhou, China) and corresponding email,
  "Statements and Declarations" section (funding / competing interests / data availability /
  author contributions / AI-assisted tools) and references. Equations are rendered as readable
  Unicode text (the PDF carries typeset math; Word equation-editor conversion can follow at revision).
- `JNSM_manuscript.pdf` — typeset A4 copy (64 pages, figures embedded) for review convenience.
- `JNSM_manuscript.rtf` / `.html` / `.md` — alternate/source copies.
- `Cover_Letter.md` — cover letter; three suggested reviewers with institutional emails (JNSM requirement).
- `Declarations.md` — same statements as the manuscript section, for the submission interface.
- `FIGURES.md` + `figures/` — 31 PNG files (fig1–fig31); **no titles embedded in the images** per
  JNSM artwork guidelines; captions live in the manuscript text.

## Submit at (JNSM has moved off Editorial Manager)
**https://submission.nature.com/new-submission/10922/3** (Springer Nature submission platform)

## Steps (short form)
1. Log in / register on the Springer Nature submission platform.
2. Research Paper -> paste title/abstract/keywords (abstract 227 words; 6 keywords).
3. Authors: Kaixiang Nie (Fujian Chuanzheng Communications College, Fuzhou, China), corresponding,
   email me@niekaixiang.com.
4. Attach `JNSM_manuscript.docx` as Manuscript (editable source), `JNSM_manuscript.pdf` as Other;
   paste cover letter into Comments; paste Declarations into the declaration fields.
5. Fill Author Contribution + Competing Interests **in the interface** (interface entries are what
   gets published); AI-tool use is documented in the manuscript (Section 6.3 + Statements and
   Declarations) per Springer's LLM policy.
6. Inspect the generated PDF -> Approve -> Submit.

## Known pending (honest, non-blocking)
- The full-chain ablation, arrival-order repeats (show6/show12), dense sampling, guard-metric
  sensitivity and phase-selective admission are **reported in Section 7.4.2 of this version**.
- Word equation-editor formatting of the display equations can be added at revision if the editors
  request it (the PDF shows them typeset; the DOCX carries them as editable text).
- One integrated validation of the probation variant with the full chain is **reported in Section 7.4.2**
  (random 14 / aligned 6 - lower than the full chain's 16/8, a deliberately reported negative result);
  reconciling candidate pricing with the background reserve, and a faithful re-implementation of the
  full AUDIBLE system, are marked as future work.
