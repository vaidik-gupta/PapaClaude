# PapaClaude — Plan

PapaClaude is a parent agent that builds tailored context for a task and hands it
to child Claude agents that do the work. This document tracks what we're building.

## Functional Requirements

### FR1. Golden dataset
A curated evaluation set to test against: docs, API specifications, and the
respective codebases for the content, plus a graded set of issues sized
**small / medium / large**. This is the ground truth we measure context quality
and agent output against.

### FR2. Context generation engine
An engine that, for any given task, assembles a context from the available
content (docs, specs, codebases, content tree) and provides it to the child
Claude agents — the core "papa builds the context for its children" capability.

### FR3. Tools, system prompts (personas), and skills
Decide the tool surface, the system prompts / personas, and the skills that
PapaClaude needs — both for the parent and for the children it spawns.

### FR4. Guardrails
Decide the guardrails for the agent: what it may and may not do, and the limits
that keep it safe and predictable.

### FR5. UI
A UI that lets us talk to both PapaClaude and its children.

### FR6. Content tree in daily use
Populate the content tree with everything I actually work on and take it into
daily use.

## Use Cases — Personalization

The point of the content is to make Claude work the way *I* work: it captures my
environment, my knowledge, and the artifacts we build together, so a handover to
Claude produces what I would have produced myself.

### UC1. Personalized handover
For each project I'm part of, the content holds my environment details, the tools
I use for development and for debugging issues, and my personal way of working on
that specific project. So whenever I hand work over to Claude, it does it exactly
the way I would.

### UC2. Accumulated knowledge with references
All the docs and architectures I accumulate while working on projects are stored,
each with reference links back to their source.

### UC3. Co-created artifacts
While working, Claude and I can also store things we derive: architecture diagrams
inferred from the codebase, subsystem documentation we generate, and sample inputs
and outputs of a service (like an API specification, but the sample inputs carry
more context than a bare spec).

### UC4. Issue → resolution memory
A searchable record of issues I've solved and how — root cause plus fix, with
links to the relevant tickets/PRs — so Claude reuses prior solutions instead of
re-deriving them.

### UC5. Operational runbooks
Recurring, step-by-step procedures per project: how to run, deploy, and debug it
(commands, relay workspaces, container/env setup). Where UC1 holds static
environment facts, this holds the repeatable "how to do X" procedures.

### UC6. Feedback / learning loop
Corrections I give Claude during work get captured back into the content, so it
gets better at working like me over time. This is how the content grows.

### UC7. Shareable engineer's diary
Everything above accumulates into a real, shareable engineer's diary. The
databases — or parts of them — can be handed to juniors, either through a
project-level share feature (added later) or simply by sharing the database
container with all its content.
