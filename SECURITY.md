# Security Policy

## Supported Versions

FieldFlow is pre-1.0. Security fixes are maintained on the latest `main` branch and will be included in the next release. Older commits and branches are not supported unless a maintainer explicitly says otherwise.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues.

Send vulnerability reports to:

```text
guillaume.gay@protonmail.com
```

Include as much detail as you can:

- Affected FieldFlow version, commit, or branch.
- The OpenAPI spec shape or generated tool surface involved.
- Reproduction steps or a minimal proof of concept.
- Whether credentials, upstream API data, or generated tool output can be exposed.
- Any suggested mitigation if you already have one.

## Scope

Security-relevant issues include:

- Credential leakage in logs, errors, generated tool output, or docs.
- Incorrect forwarding of authentication headers.
- Request routing bugs that call the wrong upstream endpoint.
- Response filtering bugs that expose fields the caller did not request.
- Unsafe handling of untrusted OpenAPI specs.

Please do not include real secrets, production API keys, or private customer data in reports. Use redacted examples whenever possible.
