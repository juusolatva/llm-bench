# Security Policy

## Supported Versions

Only the latest release, or the default branch if there are no releases, receives security fixes.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public issues, pull requests, or discussions.

Report them privately through GitHub's private vulnerability reporting:

1. Go to the repository's Security tab.
2. Click Report a vulnerability.

If that option is unavailable, please contact me using the email address on my GitHub profile.

Please include:

- A description of the issue and its potential impact
- Steps to reproduce, or a proof of concept
- Affected version, commit, or configuration

## What to Expect

This is a personal project maintained on a best-effort basis. I aim to acknowledge reports within 7 days and will keep you updated on progress. Once a fix is released, you will be credited in the advisory unless you prefer to remain anonymous.

## System and Scope

llm-bench is a local command-line benchmark that requests code from operator-selected OpenAI-compatible API endpoints and builds and tests it in a mandatory Linux sandbox. It is not an inbound network service.

Security review covers the runner, API response handling, task loading, sandbox setup and cleanup, result and transcript handling, and repository automation. Task harnesses and reference solutions remain relevant where they affect these boundaries.

Assets include host files and credentials, host availability, benchmark artifacts, and isolation between attempts.

## Threat Model and Trust Boundaries

Treat API responses, model identifiers, generated source, and build/test output as attacker-controlled. Selecting an endpoint does not make its responses or generated code trustworthy.

The intended operator controls CLI arguments, endpoint selection, task directories, and output locations. Whether hostile local users can modify those directories during a run is deployment-dependent; state that prerequisite when assessing a finding rather than assuming it away.

The host kernel, systemd, bubblewrap, Python runtime, and installed toolchains provide the execution foundation. Their presence alone does not prove that isolation or resource limits are effective.

Task prompts are sent to the selected endpoint. Build/test feedback is also sent on retries. A configured API key is sent to every selected endpoint. Hidden harnesses are available inside the sandbox, so “hidden” does not mean confidential from executing code or its feedback.

## Security Invariants

- All model-generated code, including compilation and build-time execution, must run through the mandatory sandbox. Missing isolation or unenforced required cgroup limits must fail closed.
- Generated code must not access the host network, home directory, credentials, or files beyond the explicitly exposed runtime, toolchain, and task inputs. The sandbox environment must not inherit host secrets.
- Attempts must not modify host inputs, parent-owned reports, or other attempts. Generated files and symlinks must remain inside private sandbox storage.
- Only trusted Go cache warm-up code may use the writable host cache. Generated code must use a private overlay or a private cache.
- Memory, swap, process count, CPU, runtime, file size, and captured output must remain bounded. Cleanup must terminate sandbox descendants on completion and interruption.
- API bodies must be capped before JSON parsing, and completion text must be capped before transcript or source writes. Untrusted parsing must not permit disproportionate resource consumption.
- Names derived from endpoints, tags, and models must not escape intended output directories. Model name collisions must not overwrite another model's transcripts.
- Credentials must not leak through sandbox inputs, logs, artifacts, or unintended network destinations.

## Reportable Findings and Severity Context

Report reachable violations of these boundaries, including host execution, sandbox escape, unintended credential or file disclosure, writes outside intended locations, cross-attempt interference, and resource-limit bypasses.

Assess severity from demonstrated impact and realistic attacker control. Distinguish malicious endpoint responses from attacks requiring local filesystem access or changes to trusted configuration. A configured endpoint is an intended request destination; unintended credential forwarding or attacker-directed destinations still require review.

## Exclusions and Known Limitations

No blanket finding-class exclusions or accepted vulnerabilities are established by this policy. Ordinary wrong answers or failed task tests are benchmark outcomes; assess security impact separately.

A harness's final line catches solutions that end the process early by accident. It is not a security boundary: a solution that prints the line on purpose, or otherwise games a harness, affects only its own result, inside the sandbox. Report it as a task issue, not a vulnerability.

Sandbox tests can skip when required host facilities are unavailable. Passing unit tests or a CI run with skipped sandbox tests is not evidence that containment works. This policy describes required properties, not a completed security audit.
