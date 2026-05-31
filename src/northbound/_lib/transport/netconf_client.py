"""NETCONF adapter around the sync ncclient library.

ncclient is blocking, so every call is wrapped in ``asyncio.to_thread``.
The class exposes only the operations Northbound drivers actually need:
``get_config``, ``edit_config``, ``commit`` (incl. confirmed-commit).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, cast


class _NetconfManager(Protocol):
    """The slice of ncclient.manager.Manager we use.

    Defined narrowly so tests can supply a fake without importing ncclient.
    The parameter NAMES mirror the real ``ncclient`` operation signatures
    (``edit_config(config, format, target, default_operation, test_option,
    error_option)``, ``get_config(source, ...)``, ``commit(confirmed, timeout,
    ...)``) because we call them by KEYWORD — a positional call mis-maps
    against the real library (our ``target`` would land in ncclient's
    ``config`` slot). The Protocol therefore documents the real contract.
    """

    def get_config(self, source: str) -> Any: ...
    def edit_config(
        self,
        config: str,
        target: str | None = ...,
        default_operation: str | None = ...,
        test_option: str | None = ...,
        error_option: str | None = ...,
    ) -> Any: ...
    def commit(self, confirmed: bool = ..., timeout: str | None = ...) -> Any: ...
    def discard_changes(self) -> Any: ...
    def close_session(self) -> None: ...


@dataclass(frozen=True)
class NetconfParams:
    host: str
    username: str
    password: str | None = None
    private_key: str | None = None
    port: int = 830
    timeout_seconds: float = 30.0
    hostkey_verify: bool = False  # lab default; flip on for prod


class NetconfClient:
    """Async wrapper over a sync ncclient session."""

    def __init__(
        self,
        params: NetconfParams,
        *,
        manager_factory: object | None = None,
    ) -> None:
        self._params = params
        self._manager: _NetconfManager | None = None
        # Tests inject a factory (callable returning _NetconfManager).
        self._manager_factory = manager_factory

    async def _ensure_manager(self) -> _NetconfManager:
        if self._manager is not None:
            return self._manager
        if self._manager_factory is not None:
            factory = self._manager_factory
            # asyncio.to_thread loses the factory's return-type narrowing; cast back.
            result = await asyncio.to_thread(factory)  # type: ignore[arg-type]
            self._manager = cast(_NetconfManager, result)
            return self._manager
        from ncclient import manager  # type: ignore[import-untyped]  # ncclient has no stubs

        def _connect() -> _NetconfManager:
            kwargs: dict[str, object] = {
                "host": self._params.host,
                "port": self._params.port,
                "username": self._params.username,
                "hostkey_verify": self._params.hostkey_verify,
                "timeout": self._params.timeout_seconds,
            }
            if self._params.password is not None:
                kwargs["password"] = self._params.password
            if self._params.private_key is not None:
                kwargs["key_filename"] = self._params.private_key
            return manager.connect(**kwargs)  # type: ignore[return-value]

        self._manager = await asyncio.to_thread(_connect)
        return self._manager

    async def get_config(self, source: str = "running") -> str:
        mgr = await self._ensure_manager()
        result = await asyncio.to_thread(mgr.get_config, source)
        return str(result)

    async def edit_config(
        self,
        target: str,
        config: str,
        *,
        default_operation: str | None = None,
        test_option: str | None = None,
        error_option: str | None = None,
    ) -> Any:
        mgr = await self._ensure_manager()
        # MUST call by keyword: real ncclient is
        # edit_config(config, format='xml', target='candidate', default_operation,
        # test_option, error_option). A positional call would put our ``target``
        # into ncclient's ``config`` slot and our XML into ``format``. Pass only
        # the kwargs we set so ncclient defaults (format='xml') stand.
        kwargs: dict[str, Any] = {"config": config, "target": target}
        if default_operation is not None:
            kwargs["default_operation"] = default_operation
        if test_option is not None:
            kwargs["test_option"] = test_option
        if error_option is not None:
            kwargs["error_option"] = error_option
        return await asyncio.to_thread(lambda: mgr.edit_config(**kwargs))

    async def commit(self, *, confirmed: bool = False, timeout: int | None = None) -> Any:
        mgr = await self._ensure_manager()
        # ncclient writes <confirm-timeout>{timeout}</confirm-timeout> via lxml,
        # which requires str text — passing an int raises
        # "TypeError: Argument must be bytes or unicode, got 'int'". Coerce here so
        # callers (drivers) can pass an int seconds value naturally.
        timeout_str = str(timeout) if timeout is not None else None
        return await asyncio.to_thread(lambda: mgr.commit(confirmed=confirmed, timeout=timeout_str))

    async def discard_changes(self) -> Any:
        mgr = await self._ensure_manager()
        return await asyncio.to_thread(mgr.discard_changes)

    async def close(self) -> None:
        if self._manager is None:
            return
        mgr = self._manager
        self._manager = None
        await asyncio.to_thread(mgr.close_session)
