# Codex Cloud Docker verification

Date: 2026-06-21 (UTC)
Repository: `to4kawa/MADO-queue`
Scope: Codex Cloud environment capability check only. Repository files were not changed during the Docker capability probes.

## Summary

Codex Cloud cannot currently be used for `docker build` or `docker compose up` verification in this repository.

The previous baseline audit recorded Docker verification as unavailable because the `docker` executable was not present. This follow-up confirmed that Docker CLI and the `dockerd` binary can be installed, but Docker daemon startup still fails because the Codex Cloud execution environment does not allow the low-level operations required by Docker daemon.

## Result

- OS: Ubuntu 24.04.4 LTS (Noble Numbat)
- User: `root`
- `apt-get update`: succeeded
- `apt-get install -y docker.io`: succeeded
- `docker --version`: succeeded
- `dockerd --version`: succeeded
- `docker info`: failed
- `/var/run/docker.sock`: unavailable
- `docker compose version`: unavailable in the checked environment
- Repository file changes during probe: none
- `git status --short`: empty

## Failure mode

Manual `dockerd` startup failed during bridge network / iptables initialization.

Representative error:

```text
failed to start daemon: Error initializing network controller:
error obtaining controller instance:
failed to register "bridge" driver:
failed to create NAT chain DOCKER:
iptables ... Permission denied
```

Because the process was running as `root`, this is not ordinary user permission failure. It is treated as an execution-environment limitation, likely involving container capabilities, cgroups, iptables, network namespace, or related kernel-level restrictions.

The environment also appeared to expose `/sys` and `/sys/fs/cgroup` as read-only, which is consistent with Docker daemon startup being unavailable in this environment.

## Classification

- Docker CLI: installable
- `dockerd` binary: installable
- Docker daemon: not usable
- Docker socket: not usable
- Docker Compose: not usable for repository verification in this environment
- `docker build` / `docker compose up`: not executable in Codex Cloud for this repository

## Impact on MADO-queue verification

The following checks cannot be completed in Codex Cloud:

- `docker build`
- `docker compose build`
- `docker compose up`
- HTTP smoke tests against a containerized service
- In-container timezone checks such as `date`, Python `datetime.now()`, and SQLite `localtime`

## What can still be verified in Codex Cloud

Codex Cloud can still be used for non-Docker checks, including:

- Python unit tests
- Static review of `Dockerfile`
- Static review of `docker-compose.yml`
- Review of timezone-sensitive application code
- Python / SQLite timezone behavior outside Docker

## Recommended follow-up

Docker startup verification should be rerun in an environment that provides a usable Docker daemon, such as:

- a local development machine
- a CI runner with Docker daemon enabled
- an environment with Docker socket mount enabled
- a privileged Docker-in-Docker environment

If Docker-related changes are proposed from Codex Cloud, mark Docker build/start verification as not executed and describe the verification as static review only.
