"""Execution backends for repository test commands.

DockerRunner is the isolated backend: no network, capped memory / pids / CPU,
dropped capabilities, non-root user, no host environment or credentials, and a
wall-clock timeout. The working tree is a plain export without `.git`.

LocalRunner exists for development and for hosts without Docker. It enforces the
timeout, scrubs the environment (no credentials are passed), gives the command a
throwaway HOME and applies rlimits where the OS supports them, but it CANNOT
block network access. Reports record which guarantees actually held.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import workspace

TAIL = 4000


@dataclass
class RawRun:
    exit_code: Optional[int]
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    infra_error: Optional[str] = None


@dataclass
class Limits:
    timeout: float = 120.0
    memory_mb: int = 1024
    cpus: float = 1.0
    pids: int = 256


def _tail(s: str) -> str:
    return s if len(s) <= TAIL else "...[truncated]...\n" + s[-TAIL:]


class Runner:
    name = "abstract"

    def __init__(self, limits: Limits, pass_env: Sequence[str] = ()):
        self.limits = limits
        self.pass_env = list(pass_env)

    def isolation(self) -> Dict[str, object]:
        raise NotImplementedError

    def run(self, workdir: Path, command: str) -> RawRun:
        raise NotImplementedError


class LocalRunner(Runner):
    name = "local"

    def isolation(self):
        return {
            "backend": "local",
            "network_isolated": False,
            "memory_limit_mb": self.limits.memory_mb if sys.platform.startswith("linux") else None,
            "timeout_s": self.limits.timeout,
            "credentials_scrubbed": True,
            "passed_env": self.pass_env,
            "warning": "Local backend does not isolate network or filesystem. Use --sandbox docker "
                       "for untrusted repositories.",
        }

    def _env(self, workdir: Path) -> Dict[str, str]:
        home = workdir.parent / (workdir.name + ".home")
        home.mkdir(exist_ok=True)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "TMPDIR": str(home),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "MERGEWEATHER": "1",
        }
        for key in self.pass_env:
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _preexec(self):
        mem = self.limits.memory_mb

        def fn():
            os.setsid()
            try:
                import resource
                if sys.platform.startswith("linux"):
                    b = mem * 1024 * 1024
                    resource.setrlimit(resource.RLIMIT_AS, (b, b))
                cpu = int(self.limits.timeout) + 5
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            except Exception:
                pass
        return fn

    def run(self, workdir: Path, command: str) -> RawRun:
        start = time.monotonic()
        try:
            proc = subprocess.Popen(["/bin/sh", "-c", command], cwd=str(workdir),
                                    env=self._env(workdir), stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                    preexec_fn=self._preexec())
        except OSError as e:
            return RawRun(None, "", "", 0.0, infra_error=str(e))
        workspace.track_pgid(proc.pid)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=self.limits.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
        except BaseException:
            try:  # interrupted: never leave the test process group behind
                os.killpg(proc.pid, 9)
            except ProcessLookupError:
                pass
            raise
        finally:
            workspace.untrack_pgid(proc.pid)
        return RawRun(None if timed_out else proc.returncode,
                      _tail(out.decode(errors="replace")), _tail(err.decode(errors="replace")),
                      round(time.monotonic() - start, 3), timed_out)


class DockerRunner(Runner):
    name = "docker"

    def __init__(self, limits: Limits, image: str = "python:3.12-slim", pass_env: Sequence[str] = (),
                 docker: str = "docker"):
        super().__init__(limits, pass_env)
        self.image = image
        self.docker = docker

    @staticmethod
    def available(docker: str = "docker") -> bool:
        if not shutil.which(docker):
            return False
        return subprocess.run([docker, "info"], capture_output=True).returncode == 0

    def isolation(self):
        return {
            "backend": "docker",
            "image": self.image,
            "network_isolated": True,
            "memory_limit_mb": self.limits.memory_mb,
            "cpus": self.limits.cpus,
            "pids_limit": self.limits.pids,
            "timeout_s": self.limits.timeout,
            "credentials_scrubbed": True,
            "passed_env": self.pass_env,
            "capabilities": "all dropped, no-new-privileges, non-root",
        }

    def build_command(self, workdir: Path, command: str, name: str) -> List[str]:
        uid = os.getuid() if hasattr(os, "getuid") else 1000
        gid = os.getgid() if hasattr(os, "getgid") else 1000
        args = [
            self.docker, "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", f"{self.limits.memory_mb}m", "--memory-swap", f"{self.limits.memory_mb}m",
            "--cpus", str(self.limits.cpus), "--pids-limit", str(self.limits.pids),
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", f"{uid}:{gid}",
            "--tmpfs", "/tmp:rw,size=256m",
            "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "MERGEWEATHER=1",
            "-v", f"{workdir}:/work:rw", "-w", "/work",
        ]
        for key in self.pass_env:
            if key in os.environ:
                args += ["-e", f"{key}={os.environ[key]}"]
        args += [self.image, "sh", "-c", command]
        return args

    def run(self, workdir: Path, command: str) -> RawRun:
        name = f"mergeweather-{uuid.uuid4().hex[:12]}"
        args = self.build_command(workdir, command, name)
        workspace.track_container(name)
        start = time.monotonic()
        try:
            proc = subprocess.run(args, capture_output=True, timeout=self.limits.timeout,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            subprocess.run([self.docker, "rm", "-f", name], capture_output=True)
            return RawRun(None, _tail((e.stdout or b"").decode(errors="replace")),
                          _tail((e.stderr or b"").decode(errors="replace")),
                          round(time.monotonic() - start, 3), timed_out=True)
        except OSError as e:
            return RawRun(None, "", "", 0.0, infra_error=str(e))
        except BaseException:
            subprocess.run([self.docker, "rm", "-f", name], capture_output=True)
            raise
        finally:
            workspace.untrack_container(name)
        err = proc.stderr.decode(errors="replace")
        # 125-127 from `docker run` itself means the container never ran the command
        if proc.returncode == 125:
            return RawRun(None, "", _tail(err), round(time.monotonic() - start, 3),
                          infra_error="docker failed to start container")
        exit_code = proc.returncode
        if exit_code == 137:  # SIGKILL, typically OOM
            err += "\n[mergeweather] container killed (exit 137, likely memory limit)"
        return RawRun(exit_code, _tail(proc.stdout.decode(errors="replace")), _tail(err),
                      round(time.monotonic() - start, 3))
