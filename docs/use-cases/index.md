# Use Cases

End-to-end walkthroughs for representative scientific and data-readiness scenarios are located in [`use_cases/`](https://github.com/AI-ModCon/dsagt/tree/main/use_cases/). Each follows one layout — Prerequisites, Setup, Execution as pasted prompts with expected results, Post-Conditions, What This Tests, Cleanup — and covers data acquisition, code or skill registration, pipeline construction, and agent-driven execution. Some run on real scientific datasets; the skill-management demos use small fixture data.

The data for every walkthrough is hosted in the [DSAgt use-case data folder](https://drive.google.com/drive/folders/1RWQAJeHaikIaD7CCf8ciJ71m55S1erp6); each Setup section gives the download command.

![DSAgt use cases](../assets/use-cases.png)

<!-- USE_CASES_TABLE -->

Each use-case folder is laid out by role: `README.md` is the walkthrough; `docs/`
holds documents the agent reads; `scripts/` holds code copied into the project;
`skills/` holds skills copied into the project; `reference/` holds expected outputs
and reference solutions that are not inputs to the demo. Only the folders a use case
needs are present.

!!! note "Adding a use case"
    Drop a `README.md` with frontmatter (`title`, `domain`, `summary`) into a
    `use_cases/<name>/` folder — it is auto-added to this table, its body is
    inlined as its own page, and it appears in the nav. Folders without
    frontmatter are left out entirely. See
    [`hooks/gen_use_cases.py`](https://github.com/AI-ModCon/dsagt/blob/main/hooks/gen_use_cases.py).
