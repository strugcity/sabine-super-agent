# ADR-003: Sandbox Provider for Skill Acquisition

## Status

**Accepted**

## Date

2026-02-13

## Deciders

Tech Lead, PM, CTO

---

## Context

### The Problem Sabine Needs to Solve

Sabine 2.0 introduces **Autonomous Skill Acquisition** as one of its four core pillars. Today, Sabine has a static skill registry (`lib/skills/`) where each skill is a hand-written `handler.py` + `manifest.json` pair deployed as part of the application. Adding a new skill requires a code change, a review, and a deployment. This constrains Sabine to learning zero new skills per month.

The target state is fundamentally different: Sabine should be able to detect capability gaps (e.g., she fails at `.msg` file parsing 5 times), research a solution, generate candidate skill code, test it safely, present a Skill Proposal to the user, and promote approved skills into the live registry -- all without a manual deployment cycle.

This lifecycle requires **sandboxed code execution**. When Sabine auto-generates a Python skill, that code is untrusted by definition. It may contain bugs, infinite loops, excessive memory usage, or accidental side effects. Running it in the same process as the production agent is unacceptable. Running it with access to production environment variables (Supabase credentials, API keys, user tokens) would be a security incident waiting to happen.

### What the Sandbox Must Provide

1. **Isolated Python execution.** The generated code runs in a separate environment with its own filesystem, process space, and network stack.
2. **No access to production secrets.** The sandbox must not inherit the host's environment variables, mounted volumes, or network routes to internal services.
3. **Ephemeral lifecycle.** Spin up, execute, capture output, tear down. No persistent state between sandbox invocations.
4. **Output capture.** Stdout, stderr, exit code, and structured results (e.g., DataFrames, plots) must be returned to the caller.
5. **Timeout enforcement.** Execution must be hard-capped to prevent infinite loops from consuming resources indefinitely.
6. **Package installation.** Generated skills may require pip packages not present in the base image. The sandbox must support on-demand package installation.
7. **Reasonable cold start.** Skill testing is an asynchronous workflow (not a user-facing hot path), so cold starts under 5 seconds are acceptable.

### Current State

Sabine already has a working E2B integration at `lib/skills/e2b_sandbox/`. This skill exposes `run_python_sandbox` as a tool the agent can invoke, using the `e2b-code-interpreter` Python SDK. It handles sandbox creation, package installation, code execution, output capture, and cleanup. This ADR formalizes E2B as the chosen sandbox provider and defines how it fits into the broader Skill Acquisition lifecycle.

---

## Decision

We will use **E2B** (https://e2b.dev) as the sandbox provider for all auto-generated skill testing in Sabine 2.0.

E2B sandboxes will be invoked through the existing `e2b-code-interpreter` Python SDK, orchestrated by the Skill Acquisition pipeline during the test phase of the skill lifecycle.

---

## Options Considered

### Option 1: E2B (Recommended)

E2B is a sandbox-as-a-service designed specifically for AI agent code execution. It provides ephemeral Linux micro-VMs with a Python SDK optimized for the "generate code, run it, capture output" workflow.

**Strengths:**
- Purpose-built for AI agents executing generated code
- Python SDK (`e2b-code-interpreter`) is clean, well-documented, and actively maintained
- Cold start approximately 2 seconds (micro-VM, not container)
- Network isolation enforced at the VM level by default
- Built-in support for package installation, file I/O, and structured result capture
- Pay-per-use pricing with no minimum commitment
- Already integrated into Sabine (`lib/skills/e2b_sandbox/handler.py`)

**Weaknesses:**
- External dependency; E2B outage blocks skill testing
- Requires `E2B_API_KEY` environment variable in production
- Limited customization of the base VM image on free/standard tiers

### Option 2: Modal

Modal is a serverless compute platform for Python. It supports running arbitrary Python functions in isolated containers with on-demand scaling.

**Strengths:**
- Mature, production-grade infrastructure
- Supports GPU workloads (relevant if skills need ML inference)
- Good Python SDK
- Container-based isolation

**Weaknesses:**
- Not designed specifically for AI agent sandboxing; more general-purpose
- Cold start approximately 5 seconds (container image pull)
- Higher setup complexity (requires Modal account, CLI setup, image configuration)
- Pricing model oriented toward compute-heavy workloads, not ephemeral micro-executions
- No existing integration in Sabine

### Option 3: Local Docker (Docker-in-Docker)

Run generated code inside Docker containers on the same host as the Sabine backend (Railway).

**Strengths:**
- No external service dependency
- Always warm (no cold start)
- Full control over the container image

**Weaknesses:**
- Docker-in-Docker on Railway is not natively supported and adds significant operational complexity
- Network isolation must be manually configured and maintained (iptables rules, network namespaces)
- Filesystem isolation is the operator's responsibility; misconfiguration risks exposing host volumes
- Environment variable leakage is a real risk without careful `--env` flag management
- No built-in timeout enforcement; must implement with external process management
- Increases Railway compute costs (containers share host resources)
- Significant engineering effort to build what E2B provides out of the box

### Comparison Matrix

| Criterion | E2B | Modal | Local Docker |
|---|---|---|---|
| **Setup complexity** | Low (SDK + API key) | Medium (account + CLI + image) | High (DinD + networking) |
| **Cold start** | ~2s | ~5s | N/A (always warm) |
| **Pricing model** | Pay-per-use (micro) | Pay-per-use (compute) | Railway compute cost |
| **Python SDK quality** | Excellent | Good | N/A |
| **AI-agent focus** | Yes (core design goal) | No (general compute) | No |
| **Network isolation** | Enforced by platform | Enforced by platform | Manual configuration |
| **Env var isolation** | Enforced by platform | Enforced by platform | Manual configuration |
| **File system isolation** | Virtual, mountable | Virtual | Shared host (risky) |
| **Package installation** | Built-in | Built-in | Manual Dockerfile |
| **Structured output** | Native (text, HTML, PNG, data) | Manual serialization | Manual serialization |
| **Existing integration** | Yes (`lib/skills/e2b_sandbox/`) | No | No |
| **Vendor lock-in risk** | Low (simple API, replaceable) | Medium | None |

---

## Rationale

### Primary Factors

1. **AI-agent alignment.** E2B is the only option designed from the ground up for the exact use case Sabine has: an AI agent generating code and needing to run it safely. The SDK's ergonomics reflect this -- `Sandbox.create()`, `sandbox.run_code(code)`, and `sandbox.kill()` map directly to our lifecycle.

2. **Security by default.** E2B micro-VMs provide process, network, and filesystem isolation at the hypervisor level. With Local Docker, we would need to manually replicate these guarantees and maintain them through infrastructure changes. One misconfiguration in Docker networking could expose production credentials.

3. **Existing integration.** The `lib/skills/e2b_sandbox/handler.py` already implements sandbox creation, package installation, code execution, output capture, and cleanup. This is not a greenfield decision -- it is a formalization of a pattern that is already working.

4. **Operational simplicity.** E2B requires one environment variable (`E2B_API_KEY`) and one pip package (`e2b-code-interpreter`). Modal requires account setup, CLI installation, and image configuration. Local Docker requires Docker-in-Docker support, network policy configuration, and custom timeout management.

5. **Cold start is acceptable.** Skill testing is not user-facing. It happens asynchronously after gap detection identifies a missing capability. A 2-second cold start is invisible in a workflow that involves LLM-based code generation (which itself takes 5-15 seconds).

6. **Cost predictability.** E2B charges per sandbox-second. At the expected volume of 2-10 skill tests per day during active development, the cost is negligible (estimated under $5/month). Modal's compute-oriented pricing would be comparable, but Local Docker's cost is hidden in increased Railway resource consumption.

### Secondary Factors

- E2B's structured output capture (text, HTML, PNG, DataFrame representations) eliminates custom serialization work.
- E2B's community and documentation focus on AI agent use cases means the patterns we need are first-class examples, not edge cases.
- The vendor lock-in risk is low. The E2B API surface is small (`create`, `run_code`, `kill`). If E2B becomes unavailable, switching to Modal or a custom Docker solution would require changing approximately 50 lines of code in `handler.py`.

---

## Consequences

### Positive

1. **Secure skill testing out of the box.** Generated code runs in hardware-isolated micro-VMs with no access to production secrets, network, or filesystem. This is the strongest isolation model available without running our own hypervisor.

2. **Minimal engineering investment.** The existing `lib/skills/e2b_sandbox/handler.py` provides a working foundation. The Skill Acquisition pipeline needs to orchestrate it, not rewrite it.

3. **Fast iteration on generated skills.** The 2-second cold start and built-in package installation mean the "generate, test, iterate" loop for auto-generated skills can complete in under 30 seconds per attempt.

4. **Clean separation of concerns.** The sandbox is a pure execution environment. It does not need to know about Sabine's memory system, skill registry, or user context. This keeps the architecture modular.

5. **Observability.** E2B returns structured stdout, stderr, error tracebacks, and execution metadata. The Skill Acquisition pipeline can use this to make informed promote/reject decisions and to present meaningful Skill Proposals to the user.

### Negative

1. **External service dependency.** If E2B is down, skill testing is blocked. Mitigation: skill testing is asynchronous and can be retried. An E2B outage does not impact Sabine's core conversational capability.

2. **Network latency.** Each sandbox invocation involves a round trip to E2B's infrastructure. At ~2 seconds cold start plus execution time, a single test takes 3-10 seconds. Mitigation: this is acceptable for an async workflow.

3. **Cost at scale.** If Sabine begins generating and testing skills at high volume (100+ tests/day), costs could grow. Mitigation: implement rate limiting and budget alerts. Current estimate is under $5/month at expected volumes.

4. **Limited base image customization.** E2B's standard tier provides a Python environment with common data science packages. If a generated skill needs system-level dependencies (e.g., `ffmpeg`, `ImageMagick`), custom images may be needed (available on higher tiers). Mitigation: most generated skills will be pure Python; escalate to custom images only if needed.

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| E2B service outage blocks skill testing | Low | Medium | Retry with exponential backoff; skill testing is async, not user-blocking |
| Generated code attempts network exfiltration | Medium | Low | E2B enforces network isolation by default; no outbound access unless explicitly configured |
| Sandbox execution exceeds timeout | Medium | Low | Hard timeout cap at 300 seconds (existing implementation); skills that need more are rejected |
| E2B pricing changes unfavorably | Low | Medium | SDK abstraction layer keeps switching cost low (~50 lines); Modal is a viable fallback |
| Generated skill installs malicious pip package | Low | Low | Sandbox isolation contains blast radius; package allowlist for production promotion |
| API key exposure | Low | High | `E2B_API_KEY` stored in Railway environment variables; never committed to source; rotated quarterly |

---

## Security Model

### Isolation Guarantees

| Layer | Mechanism | Notes |
|---|---|---|
| **Process isolation** | Micro-VM (Firecracker-based) | Each sandbox is a separate VM, not a container |
| **Network isolation** | No outbound access by default | Generated skills cannot call external APIs or exfiltrate data |
| **Filesystem isolation** | Virtual filesystem, destroyed on teardown | No persistent storage between invocations |
| **Environment variable isolation** | Clean environment | Production secrets (`SUPABASE_URL`, `OPENAI_API_KEY`, etc.) are not passed to the sandbox |
| **Execution time limits** | Hard timeout (default 30s, max 300s) | Prevents infinite loops and resource exhaustion |
| **Resource limits** | E2B-managed CPU and memory caps | Prevents single sandbox from consuming excessive resources |

### What the Sandbox Can Access

- Python standard library
- Pre-installed data science packages (pandas, numpy, matplotlib, etc.)
- Packages installed via `install_packages` parameter
- Files explicitly uploaded to the sandbox filesystem

### What the Sandbox Cannot Access

- Production environment variables
- Supabase database
- Railway internal network
- Host filesystem
- Other sandboxes
- The internet (unless explicitly allowed, which we do not enable)

### Promotion Security Gate

When a skill passes sandbox testing, it does not automatically enter the live registry. The promotion flow includes:

1. **Sandbox test results review** -- stdout, stderr, exit code must indicate success
2. **User approval** -- the Skill Proposal is presented to the user with a description of what the skill does, what it was tested against, and the results
3. **Code review (optional)** -- for skills that interact with external services, the generated code can be reviewed before promotion
4. **Allowlisted imports only** -- promoted skills may only import from an approved package list

---

## Implementation Notes

### E2B SDK Integration Pattern

The current integration in `lib/skills/e2b_sandbox/handler.py` follows this pattern:

```python
from e2b_code_interpreter import Sandbox

# Create an ephemeral sandbox
sandbox = Sandbox.create(timeout=30)

try:
    # Optional: install additional packages
    sandbox.run_code("pip install some-package")

    # Execute the generated skill code
    execution = sandbox.run_code(generated_code)

    # Capture results
    stdout = execution.logs.stdout
    stderr = execution.logs.stderr
    error = execution.error
    results = execution.results  # Structured output (text, HTML, PNG, data)
finally:
    # Always clean up
    sandbox.kill()
```

### Skill Testing Workflow

The Skill Acquisition pipeline will invoke the sandbox as follows:

1. **Prepare test harness.** Wrap the generated skill code in a test harness that:
   - Imports the skill function
   - Calls it with sample inputs derived from the gap detection context
   - Asserts expected output structure (returns a dict with `status`, relevant keys)
   - Captures any exceptions

2. **Execute in sandbox.** Call the E2B sandbox with the test harness code and a timeout appropriate for the skill complexity (default 30s, up to 300s for data-intensive skills).

3. **Evaluate results.** Parse stdout/stderr/error to determine:
   - **Pass:** Exit code 0, no errors, output matches expected structure
   - **Fail:** Non-zero exit code, uncaught exception, or output validation failure
   - **Retry:** Timeout or transient error; retry once with increased timeout

4. **Generate Skill Proposal.** If the skill passes testing, assemble a Skill Proposal containing:
   - Skill name and description
   - Generated `manifest.json`
   - Generated `handler.py`
   - Test results (stdout, execution time)
   - Gap detection context (why this skill was created)

### Output Capture

E2B's `execution.results` provides structured output beyond plain text:

| Result Type | Use Case | Handling |
|---|---|---|
| `text` | Plain text output, function return values | Stored directly |
| `html` | Formatted tables, rich output | Stored (truncated to 500 chars for proposals) |
| `png` | Matplotlib plots, visualizations | Stored as base64 reference |
| `data` | DataFrames, structured data | Stored as string representation (truncated to 1000 chars) |

### Configuration

| Parameter | Default | Max | Notes |
|---|---|---|---|
| `timeout` | 30 seconds | 300 seconds | Per-execution hard cap |
| `install_packages` | `[]` | No hard limit | Packages installed before execution |
| `E2B_API_KEY` | Required env var | N/A | Stored in Railway, never in source |

---

## Skill Lifecycle: End-to-End

The sandbox provider is one component in the broader Skill Acquisition lifecycle. Here is the complete flow:

```
1. GAP DETECTION
   Sabine notices repeated failures for a specific capability
   (e.g., 5 failed attempts to parse .msg files in 7 days)
        |
        v
2. SKILL RESEARCH
   Sabine uses its LLM reasoning to research a solution:
   - Identify relevant Python packages
   - Determine the approach (library wrapper, API call, etc.)
   - Draft candidate skill code (handler.py + manifest.json)
        |
        v
3. SANDBOX TESTING  <-- This is where E2B is used
   Generated code is executed in an E2B sandbox:
   - Install required packages
   - Run test harness with sample inputs
   - Capture stdout, stderr, exit code, structured results
   - Evaluate pass/fail criteria
        |
        |--- FAIL --> Iterate (back to step 2, up to 3 attempts)
        |
        v
4. SKILL PROPOSAL
   Present to user:
   - "I noticed I keep failing at [X]. I've developed a skill
     that can handle it. Here's what it does, how it was tested,
     and the results. Should I add it to my capabilities?"
        |
        |--- REJECTED --> Log rejection reason, do not retry
        |
        v
5. PROMOTION
   Approved skill is written to lib/skills/<skill_name>/:
   - handler.py (generated code)
   - manifest.json (generated metadata)
   Skill registry picks it up on next scan cycle.
        |
        v
6. MONITORING
   Track promoted skill usage:
   - Success/failure rate
   - Execution time
   - User satisfaction signals
   If failure rate exceeds threshold, flag for review or demotion.
```

### Lifecycle State Machine

```
[gap_detected] --> [researching] --> [testing] --> [proposing] --> [promoted]
                        |               |              |
                        v               v              v
                   [abandoned]     [test_failed]  [rejected]
                   (max retries)   (iterate x3)   (user said no)
```

---

## Future Considerations

1. **Custom E2B images.** If generated skills frequently need system-level dependencies, we may create a custom E2B sandbox image with common tools pre-installed (reducing per-invocation setup time).

2. **Parallel testing.** Multiple skill candidates could be tested simultaneously in separate sandboxes to speed up the iteration loop.

3. **Sandbox result caching.** If the same generated code is tested multiple times (e.g., after a failed promotion attempt), cache sandbox results to avoid redundant execution.

4. **Modal as fallback.** If E2B's reliability or pricing proves insufficient, Modal provides a viable fallback. The abstraction layer in `handler.py` keeps the switching cost at approximately 50 lines of code.

5. **Network-enabled sandboxes.** Some generated skills may legitimately need network access (e.g., a skill that calls a public API). This would require a separate sandbox configuration with explicit network allowlists and additional security review before promotion.

---

## References

- `lib/skills/e2b_sandbox/handler.py` -- Current E2B sandbox integration
- `lib/skills/e2b_sandbox/manifest.json` -- Sandbox skill manifest
- `lib/skills/README.md` -- Skill registry documentation
- `lib/skills/__init__.py` -- Skill registry loader
- `docs/Sabine_2.0_Technical_Decisions.md` -- ADR-003 decision framework
- `docs/Sabine_2.0_Executive_Summary.md` -- Skill Acquisition pillar overview
- E2B documentation: https://e2b.dev/docs
- E2B Code Interpreter SDK: https://github.com/e2b-dev/code-interpreter
