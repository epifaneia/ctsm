# CTSM · Customer-to-Supplier Mapping

*Read this in [Español](README.es.md).*

Audits the requirements of a customer specification (a ReqIF exported from Polarion) against the supplier's documentation (PDF), and returns **the same ReqIF file** with, for every requirement, the evidence found and its exact page. The model never writes a location. The input file is never regenerated. It runs without a network.

> AI carries risk. Code bounds it. The standard answers for what remains.

[Design philosophy](#design-philosophy) · [Why AI here](#why-ai-here) · [The five steps](#the-five-steps-in-this-project) · [Measured](#measured) · [Demo](#see-it-in-30-seconds-the-interface-in-demo-mode) · [Limitations](#limitations) · [Security & regulation](#security--regulation)

---

## Design philosophy

Every AI application has five steps. Only step 4 invokes a model; the other four are code: reproducible, testable, offline. Step 5 never patches: it flags and degrades. Full text at [epifaneia.dev](https://epifaneia.dev).

```
 1 CLEANING      2 CONTEXT       3 INPUT GUARDRAIL   4 PROCESS        5 OUTPUT GUARDRAIL
 ■ code          ■ code          ■ code              ▲ model          ■ code
```

## Why AI here

A customer specification has dozens of requirements; the supplier manual that answers them has a thousand pages. Matching one against the other is reading and judgment, and a conventional tool drowns in it: keyword search over a Polarion export of thousands of XML lines and a 1,136-page manual returns noise, and a human doing it by hand takes days per document. The model does the one thing only a model can do, read a requirement and find the passage that answers it, and code does everything else: where the passage is, whether the quote is real, and that the file the customer gets back is the one it sent.

---

## The five steps in this project

★ marks where the improvement lives in this project: **context** and the **output guardrail**.

| Step | What it does here | |
|---|---|---|
| 1 · Cleaning | `s0` adds the three target fields to the ReqIF if the export lacks them (schema only, deterministic ids). `s1` parses ids, hierarchy, target fields and the status enum of the file itself. `s2` turns the supplier PDFs into chunks with section, page and a per-offset `page_map` (PyMuPDF; encrypted PDFs decrypted in memory). | |
| 2 · Context | `s3` retrieves BM25 top-K chunks per requirement, or passes the whole corpus through when it fits. Every chunk carries an id, a page and a section: the model will be able to point, never to describe. `utils/citables` splits each chunk into numbered units so a quote can be chosen by index. | ★ |
| 3 · Input guardrail | `s4` calls with a forced response schema: `status` restricted to the enum the file declares, `chunk_id` restricted, per requirement, to the candidates of that requirement. Citing a location that was not given is structurally impossible. | |
| 4 · Process | One call per requirement, no batches. Backend `ollama` (local, default) or `gemini` (cloud), same contract. Three modes (`run.py --modo`): **veredicto** (default), `s4` decides the status and quotes; **revision**, then `s5_review` judges every candidate passage (supports, contradicts, irrelevant) with a small model, and the large one arbitrates where they disagree; **evidencia**, no model call at all: `s4_evidence` anchors the passages to their pages and leaves the status open for the engineer. | |
| 5 · Output guardrail | `s6` looks for every quote **literally** in the chunk the model cited, after normalising the PDF's noise (hyphenation, line breaks, typographic quotes), and derives the exact page from the match offset. A quote that is only close (similarity ≥ 0.85) is kept only if it keeps every figure and every negation of the passage; it is then replaced by the manual's own words and flagged. A paraphrase that changes a number or a "not" does not count as evidence. What the file shows as a quote is always the manual's text, never the model's. A verdict backed only by paraphrases is kept but flagged for review before sign-off. A verdict left without verified evidence degrades to the open value, with a flag. In revision mode, one contradicting passage is enough for a "no". `s7` edits the original with lxml and `roundtrip_diff` proves nothing else changed: `tests/test_roundtrip.py` throws ten sabotages at it and it catches all ten. | ★ |

### What it writes, and where

| Field in the customer ReqIF | What gets written |
|---|---|
| `Status` (enumeration) | The verdict, by `ENUM-VALUE-REF` to a value the file already declares. Never free text. |
| `Rationale` (XHTML) | The analysis plus anchored citations: `[RM0008 p.81 §6.1] "quote..."`. |
| `Comments from/to External` (XHTML) | A short message back to the customer: confirmation, deviation request, or question. |

## Measured

Set: 9 requirements written against the STM32F10xxx reference manual RM0008 (1,136 pages, public document from ST), with ground truth built by hand. Machine: RTX 2060 (6 GB VRAM), 16 GB RAM, Ryzen 5 3500X; the 14B does not fit entirely on the card and runs split between GPU and CPU.

| Engine | Hits vs ground truth | False "compliant" | Seconds / requirement |
|---|---|---|---|
| **qwen2.5:14b, local** | **9 / 9** | **0** | 150 (Ollama autofit) |
| qwen2.5:7b, local | 8 / 9 (7 / 9 in a second run) | 0 | 25–29 |
| gemini (cloud) | not re-measured yet | | |

Measured on 2026-10-27 and re-run on 2026-10-29 with every output saved: log, raw verdicts, sealed results and score for each run are in [`mediciones/2026-10-29/`](mediciones/2026-10-29/). The re-run gave the same hits; the seconds are from it. n = 9: a small set, read it as a smoke test, not a benchmark. Runs are not identical: in its second pass the 7B lost REQ-STM-002, a *Compliant* that `s6` demoted to *Unconfirmed* because its quote was not in the passage it cited. An earlier version of this table used requirement ids that hinted the expected answer (`REQ-STM-ACC-001`, `-REJ-`, `-OPN-`), and the id reaches the prompt. The ids are now neutral and shuffled, and both local models were re-measured; both scored higher than before. The cloud row has not been re-run.

Two things follow from that table. The local model removes the data leaving the machine, and the bounded task is what makes a 14B enough. What a model misses, the guardrail flags instead of letting through: the 7B miss is a *Not compliant* where the expected answer was *Unconfirmed*, flagged by `s6` because one of its two quotes did not verify; neither model produced a false *Compliant*.

What the literal check catches, on this very run. For REQ-STM-001 the 14B quoted *"The **4 to 16 MHz** external oscillator has the advantage of producing a very accurate rate on the main clock"*; the passage it pointed to says ***3 to 25 MHz***. A similarity threshold alone accepts it (0.96). `s6` sees that the figures differ, discards that quote as evidence and records why: `cifras distintas: modelo 4 16 / manual 3 25`. Of the 16 quotes in the run, 12 are literal, 3 are paraphrases that keep every figure (shown with the manual's text) and 1 is this one, discarded. The verdicts do not change: 9/9.

`tools/score_vs_fixture.py` reproduces the table. Calibrate Ollama threads with the **longest** prompt of the set, not the shortest: a short prompt makes a setting look faster than it is on real requirements.

Beyond the public set, the pipeline has been run on a real customer specification (53 requirements) and its supplier manuals. That data is not in this repository; the screenshots below are from the public set.

## Polarion

Public data in a Polarion trial: the nine STM32 requirements against RM0008. Nothing to redact.

*The demo document after import: one heading, nine requirements, each with its verbatim identifier as title.*

![STM32 validation document in Polarion](docs/img/polarion-02-tree.png)

*The same requirement after the pipeline wrote back into the file: the status enum set, the rationale with the citation, and the page and section derived by code from the supplier manual.*

![Requirement with status and rationale filled by CTSM](docs/img/polarion-04-status-rationale.png)

*The ReqIF import mapping in Polarion: the pipeline's fields map onto the project's own fields; nothing is created on the Polarion side.*

![ReqIF import mapping](docs/img/polarion-01-import.png)

## See it in 30 seconds: the interface in demo mode

```bash
pip install -r requirements.txt
python ui/app.py --demo                           # → http://127.0.0.1:8078
```

The demo replays a real recorded run (`ui/demo/stm32/`: qwen2.5:14b on the RTX 2060 above) at ×12, and says so on screen. No model, no network, no data to download. If RM0008 is in `data/inputs/supplier_docs/`, each quote is shown highlighted on its page of the manual. The recording is made by `ui/grabar_demo.py` from a `run.py` log; verdicts and quotes are copied, never edited.

Live mode, `python ui/app.py` (needs `CUSTODIA_ACTOR`, like `run.py`), takes a ReqIF and the supplier PDFs, runs the same pipeline in a sandbox per job, shows each verdict as `s4` writes it, and offers the output ReqIF and the three `roundtrip_diff` locks.

## The full pipeline on public data

```bash
pip install -r requirements.txt
ollama pull qwen2.5:7b                            # with `ollama serve` running in another terminal
export CUSTODIA_ACTOR=demo                        # the pipeline does not run anonymously

# 1. a starting ReqIF from the fixture, cloning the schema of any ReqIF exported from your Polarion
CTSM_STK_TEMPLATE=path/to/any_export.reqif python tools/build_demo_stk.py
# 2. drop RM0008 (st.com, reference manual STM32F10xxx) in data/inputs/supplier_docs/
python run.py STM32                               # s0 → s7 on the demo file (s2: 1,136 pages in ~2 s)
python tools/score_vs_fixture.py STM32 tools/fixtures/stm32_validation_9reqs.json
```

`s7` runs `roundtrip_diff` itself against the prepared input and fails if anything outside the three target fields changed.

This repository ships no data: no inputs, no intermediates, no outputs. `data/` is ignored by git.

## Limitations

- The demo needs a ReqIF exported from *your* Polarion as schema template. Exports differ by project, so `build_demo_stk` clones yours by `LONG-NAME` instead of shipping one.
- `s5_config` (extraction of configuration parameters) is a stub taken out of scope.
- The scoring that `s6` promises in its docstring never runs on real files. Use `tools/score_vs_fixture.py`.
- The import into Polarion of a pipeline-written file was verified structurally (roundtrip_diff) and visually (screenshots); the import itself is a manual step.
- Docling is reserved for scanned documents and is not wired by default: it downloads models on first run, which would break the air gap of `s2`.
- Only the quotes are verified. The analysis and the comment that go back in the ReqIF are the model's words: in REQ-STM-001 the comment still says "4-16 MHz or 3-25 MHz". The verdict is backed by verified quotes; the prose next to it is not.
- Identity, events and sign-off are shipped as a contract with a local default (environment variable, JSONL file, HMAC key). The adapters to a company's Entra ID, SIEM or PKI are not here and cannot be tested here: see [docs/INTEGRATION.md](docs/INTEGRATION.md).

---

## Security & regulation

Same four headings in every repository. Rows marked **today** are what the code does. Rows marked **wire** are the three integration wires the repository ships as a contract (identity, events, sign-off) and the company connects to its own systems: see [docs/INTEGRATION.md](docs/INTEGRATION.md). Local tests, no network and no model: `python tests/todas.py` (the custody wires, literal quotes, the ten round-trip sabotages).

| | | |
|---|---|---|
| **Confidentiality** | Local by default: Ollama on `127.0.0.1` (qwen2.5:7b by default; the measured run used the 14B), no byte leaves the machine, the whole pipeline runs with the network unplugged. The task is bounded enough for a local model to be enough (9/9 with the 14B, 0 false "compliant"). The cloud backend is for non-confidential data and comparison only: when on, `s4` prints on every run that it sends the requirement text and up to 10 chunks of the supplier manual (~28,000 characters) to Google. Encrypted PDFs are decrypted in memory; no cleartext copy is written. `data/` and `.env` are outside git. | **today** |
| **Traceability** | Every verdict carries its evidence with document, page, section and match ratio; the citation is composed by code, never by the model. `results.json` keeps, per requirement, every verified quote with its page, whether it is literal or approximate (with the model's version aside), and every flag of the verifier. | **today** |
| | **Wire 2 · events.** Every model call goes through `custodia/ledger`: one JSON line with actor, step, engine, endpoint, whether data left the machine, input size and hash. Never the text. `logs/custody.jsonl` or stdout. The company points its SIEM at it. | **wire** |
| **Leak prevention** | The model holds no credentials; the step that invokes it holds the endpoint and sees only the chunks selected for that requirement. Everything else is code with no network access. | **today** |
| | **Wire 1 · identity.** `run.py` refuses to start without a named actor (`custodia/identity`, default `CUSTODIA_ACTOR`); the actor is stamped on every event and every signature. The company replaces the provider with Entra ID, LDAP, Kerberos or its SSO in one call. Per-layer permissions on inputs, intermediates, model and outputs are the company's, on its file system and its vault. | **wire** |
| **Human in the loop** | Any requirement without verified evidence stays at the open value with a flag; the reviewer looks at what is flagged, not at everything. In evidencia mode the system never rules: it anchors the evidence to its page and the engineer decides. | **today** |
| | **Wire 3 · sign-off.** An output is a proposal until `tools/signoff.py sign` writes its manifest (file hash, actor, timestamp, signature) and `verify` passes; a changed file or a wrong key fails. Nothing the model touched is imported or sent without a manifest that verifies. The company replaces the local HMAC key with its PKI or its Polarion approval workflow by registering two functions. | **wire** |

Written with reference to the EU AI Act (2024/1689), GDPR, ISO/IEC 42001, ISO/IEC 27001 and TISAX. No certification or conformity is claimed: the table says which part the code covers and which part belongs to the company.

---

## Structure

```
ui/          app · engine · static · demo/ (a recorded real run) · grabar_demo
pipeline/    s0..s7 (s5_config retired)      docs/       PLAN.md · RISK_roundtrip.md · INTEGRATION.md · pipeline_arquitectura.html
clients/     ollama (local, default) · gemini (cloud) · docling_adapter
prompts/     evaluar_status.txt (taxonomy injected at runtime)
tools/       roundtrip_diff · reqif_lint · score_vs_fixture · build_demo_stk · signoff
utils/       citables · text_norm · json_helpers
tests/       todas · custodia · s6 (literal quotes) · roundtrip (ten sabotages)
custodia/    identity · ledger · signoff · cli  — the three integration wires
data/        inputs · interim · outputs — all outside git
```

Daniel Martín · [epifaneia.dev](https://epifaneia.dev) · Apache-2.0
