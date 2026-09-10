# Quality and Efficiency Roadmap

Status: planned engineering work following the production desktop GUI. This
document defines measurable targets, not claims about the current product.

Throughout, "the reference implementation" means a mature commercial agentic
assistant used as the comparison baseline. It is deliberately unnamed here:
the targets below are stated as measurements Sleipnir must be able to
reproduce, so they remain meaningful whichever baseline is chosen.

## North star

Sleipnir must become an intelligence amplifier, not merely a budget router.
Using the same underlying model as the reference implementation wherever a
controlled match is technically possible, Sleipnir must deliver a decisive,
measured improvement in every product dimension that matters:

- accepted cost per task;
- provider credit and subscription-window usage;
- time to verified completion;
- useful work per token, tool call, credit, and minute;
- reasoning and task-completion quality;
- adaptation to new requirements, missing inputs, tool failures, and provider
  outages;
- non-interference while work proceeds in the background;
- correctness, polish, editability, and evidentiary quality of outputs;
- reliability, recoverability, safety, and auditability.

A composite score is not enough. Sleipnir may not hide a regression in one
dimension behind a large improvement in another. The release comparison must
show no statistically meaningful loss in any required category and decisive
wins across the suite.

This is effective system intelligence. Sleipnir cannot change a foundation
model's weights, but it can make that model substantially more capable through
better problem formulation, scoped context, specialized skills, diverse
candidates, tools, verification, repair, memory, and synthesis.

## Required sequence

1. Finish and validate the production desktop GUI on the existing engine.
2. Freeze a reproducible GUI/CLI behavioral-parity suite.
3. Build the benchmark harness and the hidden comparison corpus.
4. Implement the skill, outcome, judging, repair, and learned-routing work in
   this document.
5. Run controlled same-model and product-level comparisons.
6. Publish a claim only after the demolition gate passes.

The GUI must remain a client of the same run-owning core as the CLI. The
intelligence program must improve both surfaces simultaneously; no quality
feature may exist only as GUI state.

## The demolition gate

Outperforming the baseline is an engineering gate, not an adjective. A qualifying
release must:

1. win every benchmark family on its primary correctness/quality measure;
2. show no statistically meaningful regression in cost, credits, latency,
   efficiency, adaptability, non-interference, or output quality;
3. show a material improvement, with confidence intervals, in each of those
   dimensions across the complete suite;
4. retain the wins on a rotating hidden holdout set that skill authors and
   prompt authors have not seen;
5. reproduce the result across enough independent runs to expose stochastic
   variance, warm-cache effects, and provider incidents;
6. preserve Sleipnir's safety and bounded-context invariants.

Initial calibration targets for a decisive win are:

| Dimension | Initial target |
|---|---|
| End-to-end verified completion | at least 15 percentage points higher, or at least 25% lower error when the baseline is already high |
| Blind output preference | Sleipnir preferred in at least 70% of non-tied comparisons |
| Accepted cost per task | at least 30% lower median and no worse p95 |
| Provider credits/window usage | at least 30% lower per accepted task |
| Time to verified completion | at least 25% faster median and no worse p95 |
| Efficiency | at least 40% more accepted work per million tokens/credit-hour |
| Adaptation and recovery | at least twice the successful recovery rate on injected changes and failures |
| Human intervention | at least 50% fewer required corrections or permission-independent rescues |
| Non-interference | zero focus theft by default; background runs survive GUI closure and remain independently resource-bounded |
| Output validity | 100% structural validity for required file formats; no unsupported factual claim accepted |

These numbers are pre-registered targets and may be made stricter after the
baseline is measured. They may not be relaxed after results are visible merely
to turn a failed comparison into a pass.

## Comparison lanes

No single comparison answers every product question. The harness must report
all of these lanes separately.

### Same-model lane

Use the identical public model identifier, version, reasoning setting, and
sampling controls on both sides when both products expose them. Give both sides
the same source material, task, time limit, permission envelope, and accessible
tools. Record every mismatch.

The baseline's private system prompt, internal tools, caching, model snapshot, and
credit conversion may not be observable or reproducible. When an exact match is
impossible, label the run `model-match-unverified`; never describe it as an
identical-model result.

### Equal-budget lane

Give each product the same wall-clock limit and the same measurable token,
credit, or dollar allowance. Compare final accepted outcomes, not how confident
the product sounds.

### Best-product lane

Run each product with its recommended default configuration. This measures what
a user actually receives, including proprietary prompts, tools, memory,
connectors, and orchestration.

### Background lane

Measure unattended work with the foreground application in active use, with
the GUI closed, after reconnect, and across interrupted network/provider
conditions. A run is not non-interfering merely because it is asynchronous.

## Measurement contract

Every run must record enough raw evidence to recompute the score:

- task and hidden-case version;
- product, model, model snapshot if exposed, provider, reasoning setting, and
  skill versions;
- cold/warm state and cache state when observable;
- input, output, cached, server-tool, and reasoning tokens;
- provider-reported credits and account-window deltas when exposed;
- metered cost, notional cost, and subscription consumption as separate values;
- wall-clock time, active model time, tool time, queue time, and repair time;
- attempts, tool calls, failures, interventions, and permission prompts;
- deterministic check results and blinded judge results;
- artifact hashes, provenance, citations, and render captures;
- CPU, memory, disk, network, focus changes, and foreground responsiveness for
  non-interference tests.

If the baseline does not expose an input, token, or credit measure, use repeated
account-delta experiments where possible and report an uncertainty interval.
An unavailable measurement is `unknown`, never zero.

Cost is always cost per *accepted* task. Failed cheap attempts are part of the
cost of the eventual accepted result. Speed is time to *verified completion*,
not time to the first plausible answer.

## Benchmark families

The hidden suite must include clean and deliberately messy cases in every
family:

1. cited research and decision memos;
2. analytical spreadsheets with formulas, reconciliation, and charts;
3. narrative presentations with editable source and rendered review;
4. formatted documents and PDFs;
5. cross-source synthesis over files, web sources, email, calendar, and team
   systems;
6. browser and desktop workflows;
7. file organization and bulk transformation;
8. repository implementation, debugging, tests, review, and migration;
9. long-running scheduled and recurring operations;
10. ambiguous tasks that require clarification or principled assumptions;
11. mid-run requirement changes and missing or contradictory evidence;
12. provider outage, malformed tool result, partial output, process death, and
    resume scenarios.

Use real deliverables and adversarial variants. Polished demo prompts are not a
benchmark. Holdouts must rotate, and a skill's own examples may never appear in
its evaluation partition.

## Intelligence architecture

The quality path is:

```text
goal
  -> task compiler and benchmark-aware decomposition
  -> skill selection and scoped evidence retrieval
  -> one worker, or diverse candidates when uncertainty warrants them
  -> deterministic checks and independent rubric judges
  -> targeted diagnosis and repair
  -> artifact-scoped synthesis
  -> verified deliverable with provenance
```

The bounded-control invariant remains unchanged. Full artifacts may be read by
explicit worker, critic, judge, repair, or synthesis tasks through declared
`ArtifactRef`s. They never enter the sparse control brain or the `Manifest`.
The control plane decides what work is needed; it does not become the working
memory for all produced content.

### 1. Versioned executable skills

A skill is a tested capability package, not a prompt fragment. `SkillSpec`
must declare:

- stable id, version, owners, and supported task families;
- selection triggers, prerequisites, incompatibilities, and confidence;
- typed inputs and outputs;
- tools, connectors, binaries, permissions, and network destinations;
- context-selection and evidence-retrieval policy;
- instructions, reusable scripts, templates, and examples;
- deterministic validators and rubric-based evaluators;
- cost, token, latency, and expected-quality profile;
- provider/model affinities backed by benchmark evidence;
- regression cases and a minimum supported environment.

Skills run in isolated, pinned environments so professional-output skills may
use rich dependencies without expanding or destabilizing Sleipnir's core.
Selection is deterministic where metadata suffices and model-assisted only
where ambiguity remains. Every attempt records which skill versions were used.
Runtime skill downloads are untrusted code and require the same review and
containment discipline as an executable plan.

### 2. Structured outcome capsules

Replace freeform `summary.md` as the semantic handoff with a bounded,
machine-readable `outcome.json` containing:

- completion state and requirement coverage;
- produced artifacts and hashes;
- claims with artifact/source evidence;
- checks executed and their results;
- confidence and uncertainty;
- missing or failed requirements;
- repair hints and recommended next actions.

The existing bounded manifest synopsis is derived from this capsule. Downstream
tasks receive selected claims and evidence, rather than trusting arbitrary
prose. Human-readable summaries remain available as a rendered view.

### 3. Independent quality plane

Implement `llm_judge` end to end. Judges must be blind to producer and provider
identity, use task-specific rubrics, cite the evidence for deductions, and
return structured repair prescriptions. Prefer a different model family from
the producer. Escalate to a second judge only for uncertainty, disagreement,
high-impact work, or benchmark measurement.

An LLM judge can never override a failed deterministic check. Judge agreement
is not truth; factual claims, formulas, code, citations, and file structure need
their own executable validation wherever possible.

### 4. Adaptive reasoning patterns

Choose the smallest pattern that is likely to succeed:

- routine: one worker plus deterministic validation;
- ambiguous: framing/planning pass plus worker;
- difficult: diverse best-of-N candidates plus independent selection;
- high impact: researcher, producer, adversarial critic, judge, then repair;
- failed: diagnose cause before changing skill, context, model, or approach;
- cohesive deliverable: specialists produce evidence, one strong synthesis
  worker owns final coherence.

Permanent swarms are forbidden as a default. Additional agents must earn their
cost through measured uncertainty or failure reduction.

### 5. Empirical routing

Extend routing from price and declared capability toward expected accepted
utility. Track success by task family, skill version, provider/model, input
size, tool requirements, failure kind, cost, and latency. The learned signal
must remain inspectable and uncertainty-aware; insufficient evidence falls
back to operator policy.

Optimize acceptance probability, quality, cost, credits, latency, and failure
risk as separate reported dimensions. Do not collapse them into an opaque score
that prevents the operator from understanding a route.

### 6. Professional output skills

The first production skill pack must cover:

- sourced research and decision briefs;
- DOCX and PDF composition, rendering, and visual inspection;
- XLSX formulas, recalculation, reconciliation, charts, and render inspection;
- PPTX narrative, layout, editability, and slide rendering;
- connected-app retrieval and actions;
- browser/desktop execution with API or connector preference;
- repository coding, testing, review, and visual QA;
- bulk file transformation and organization;
- recurring operations and exception reporting;
- final cross-artifact synthesis and executive summaries.

Each skill owns both creation and verification. Producing a file that opens is
not sufficient evidence that the file is correct or useful.

## Non-interference requirements

Background work must be a product property, not a visual illusion:

- a run-owning service continues when the GUI closes;
- GUI and CLI reconnect without losing or duplicating state;
- repository work is isolated by attempt/worktree so parallel jobs do not
  overwrite foreground work;
- CPU, memory, disk, network, and provider concurrency are bounded per run;
- connectors and direct APIs are preferred over screen interaction;
- browser automation uses an isolated background profile/context;
- physical pointer, keyboard, clipboard, microphone, camera, and focused-window
  control require explicit operator intent and never occur as a hidden fallback;
- notifications replace focus stealing;
- suspend, restart, network loss, provider outage, and process death have
  explicit recovery tests;
- foreground responsiveness and focus changes are measured in the benchmark.

Running on the local machine after the GUI closes requires a background
service. Continuing after the machine sleeps or powers off requires an
operator-owned remote worker or a cloud execution plane; documentation must not
conflate those two guarantees.

## Product parity that precedes superiority

Before claiming a win, Sleipnir needs comparable access to projects,
memory, local files, browser/computer capabilities, connectors, schedules,
professional files, background work, and cross-device steering. Current baseline
capabilities must be re-audited from its official documentation when each
benchmark release is cut; the competitor baseline is moving.

Sleipnir's durable differentiators are then:

- same-model intelligence amplification rather than reliance on a model-name
  advantage;
- provider-diverse candidate generation and independent adjudication;
- explicit output contracts and executable verification;
- artifact and claim provenance;
- recoverable DAG execution;
- transparent cost, credit, quota, and routing decisions;
- operator-controlled local, remote, or cloud placement;
- bounded control context and isolated worker capabilities.

## Restrictions and honest claims

- Never claim identical-model performance without a verified identical model
  snapshot and comparable inference settings.
- Never infer a baseline's hidden credits or tokens as zero.
- Never publish only a composite score or only the best run.
- Never use the producer as its sole judge.
- Never tune against the hidden test partition.
- Never trade away deterministic correctness, credential separation, explicit
  destructive-action approval, or the bounded-manifest invariant for a higher
  benchmark score.
- Never describe local background execution as surviving host sleep or power
  loss.
- Never call a benchmark won until raw artifacts and scoring inputs can be
  independently audited.

## Exit condition

This program is complete only when the controlled same-model lane and the
best-product lane both pass the demolition gate, the result reproduces on the
hidden suite, and the GUI makes every quality, evidence, routing, resource, and
background-execution decision inspectable without changing CLI semantics.
