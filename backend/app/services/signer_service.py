from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import IO, Any

import httpx

# fcntl does not exist on Windows; msvcrt.locking is the equivalent byte-range lock.
if os.name == "nt":
    import msvcrt

    fcntl = None
else:
    import fcntl

    msvcrt = None


logger = logging.getLogger("qoderroute.signer")

SIGNER_URL = "http://127.0.0.1:8123"
SIGNER_DIR = Path(__file__).resolve().parents[2] / "signer"
SIGNER_SCRIPT = SIGNER_DIR / "signer_server.mjs"
SIGNER_LOG = SIGNER_DIR / "signer.log"
SIGNER_LOCK = SIGNER_DIR / ".start.lock"
SIGNER_PID = SIGNER_DIR / "signer.pid"

_START_TIMEOUT_SECONDS = 12.0
_LOCK_TIMEOUT_SECONDS = 20.0
_SUPERVISOR_INTERVAL_SECONDS = 2.0

_ensure_lock = asyncio.Lock()
_spawned_process: subprocess.Popen[bytes] | None = None


class SignerUnavailableError(RuntimeError):
    """The local signer sidecar could not be reached or recovered."""


async def signer_is_healthy(timeout: float = 1.0) -> bool:
    """Return whether the local signer is accepting requests."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{SIGNER_URL}/health")
        return response.status_code == 200 and response.json().get("ok") is True
    except (httpx.HTTPError, OSError, ValueError, AttributeError):
        return False


def _try_lock(handle: IO[str]) -> bool:
    """Non-blocking exclusive lock on the lock file; False when another process holds it."""
    if msvcrt is not None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(handle: IO[str]) -> None:
    if msvcrt is not None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


async def _acquire_process_lock(timeout: float) -> IO[str] | None:
    """Acquire the cross-Uvicorn signer start lock without blocking the loop."""
    SIGNER_DIR.mkdir(parents=True, exist_ok=True)
    handle = SIGNER_LOCK.open("a+", encoding="utf-8")
    deadline = time.monotonic() + timeout
    try:
        while True:
            if _try_lock(handle):
                return handle
            if time.monotonic() >= deadline:
                handle.close()
                return None
            await asyncio.sleep(0.1)
    except BaseException:
        if not handle.closed:
            handle.close()
        raise


def _release_process_lock(handle: IO[str]) -> None:
    try:
        _unlock(handle)
    except OSError:
        pass
    finally:
        handle.close()


def _spawn_signer() -> subprocess.Popen[bytes]:
    """Start a detached signer whose lifetime is independent of Uvicorn."""
    global _spawned_process

    SIGNER_LOG.parent.mkdir(parents=True, exist_ok=True)
    # Detach from the backend so a Uvicorn restart never takes the signer down
    # with it: setsid() on POSIX, a detached process group on Windows.
    detach_kwargs: dict[str, Any] = (
        {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with SIGNER_LOG.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            ["node", str(SIGNER_SCRIPT)],
            cwd=SIGNER_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **detach_kwargs,
        )
    SIGNER_PID.write_text(f"{process.pid}\n", encoding="utf-8")
    _spawned_process = process
    return process


async def _retire_unhealthy_owned_process() -> None:
    """Reap, or stop, an unhealthy signer spawned by this backend process."""
    global _spawned_process

    process = _spawned_process
    if process is None:
        return
    if process.poll() is None:
        logger.error("Stopping unhealthy signer sidecar (pid %s)", process.pid)
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.to_thread(process.wait, 3)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                process.kill()
            await asyncio.to_thread(process.wait)
    else:
        process.wait()
    _spawned_process = None


async def ensure_signer() -> bool:
    """Ensure exactly one signer is running, even across overlapping backends."""
    if await signer_is_healthy():
        return True

    async with _ensure_lock:
        if await signer_is_healthy():
            return True

        process_lock = await _acquire_process_lock(_LOCK_TIMEOUT_SECONDS)
        if process_lock is None:
            logger.error("Timed out waiting for signer start lock")
            return await signer_is_healthy()

        try:
            # A different Uvicorn generation may have started it while this
            # process was waiting for the filesystem lock.
            if await signer_is_healthy():
                return True

            await _retire_unhealthy_owned_process()
            try:
                process = _spawn_signer()
            except (OSError, subprocess.SubprocessError) as exc:
                logger.exception("Unable to spawn signer sidecar: %s", exc)
                return False

            deadline = time.monotonic() + _START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if await signer_is_healthy():
                    logger.warning("Signer sidecar started (pid %s)", process.pid)
                    return True
                return_code = process.poll()
                if return_code is not None:
                    logger.error(
                        "Signer sidecar exited during startup (pid %s, code %s); "
                        "see %s",
                        process.pid,
                        return_code,
                        SIGNER_LOG,
                    )
                    return False
                await asyncio.sleep(0.25)

            # Do not kill a signer that became ready at the deadline boundary.
            if await signer_is_healthy():
                logger.warning("Signer sidecar started (pid %s)", process.pid)
                return True
            logger.error(
                "Signer sidecar did not become healthy (pid %s); see %s",
                process.pid,
                SIGNER_LOG,
            )
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.to_thread(process.wait, 3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    process.kill()
                await asyncio.to_thread(process.wait)
            return False
        finally:
            _release_process_lock(process_lock)


async def signer_supervisor() -> None:
    """Recover a signer that exits after application startup."""
    while True:
        try:
            await asyncio.sleep(_SUPERVISOR_INTERVAL_SECONDS)
            if not await signer_is_healthy():
                logger.error("Signer health check failed; attempting recovery")
                await ensure_signer()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Signer supervisor iteration failed")


async def post_to_signer(
    path: str,
    *,
    json: dict[str, Any],
    client: httpx.AsyncClient,
) -> httpx.Response:
    """POST to signer, recovering it and retrying once on transport failure."""
    url = f"{SIGNER_URL}{path}"
    try:
        return await client.post(url, json=json)
    except (httpx.TransportError, OSError) as first_error:
        logger.warning("Signer request failed; attempting recovery: %s", first_error)
        if not await ensure_signer():
            raise SignerUnavailableError(str(first_error)) from first_error
        try:
            return await client.post(url, json=json)
        except (httpx.TransportError, OSError) as retry_error:
            raise SignerUnavailableError(str(retry_error)) from retry_error
