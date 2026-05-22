"""Kafka Connect REST API adapter — implements ConnectorRegistryPort"""
from __future__ import annotations
import json
from typing import List
import urllib.request
import urllib.error
from ...domain.models import ConnectorState, ConnectorStatus
from ...domain.ports import ConnectorRegistryPort


class KafkaConnectAdapter(ConnectorRegistryPort):
    """Calls Kafka Connect REST API (no extra deps, stdlib only)."""

    def __init__(self, base_url: str, timeout: int = 30) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def create_connector(self, config: dict) -> ConnectorState:
        data = json.dumps(config).encode()
        req = urllib.request.Request(
            f"{self._base}/connectors",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                body = json.load(r)
                return ConnectorState(
                    connector_name=body.get("name", config["name"]),
                    status=ConnectorStatus.UNASSIGNED,
                )
        except urllib.error.HTTPError as e:
            if e.code == 409:  # already exists
                return await self.get_connector_status(config["name"])
            raise

    async def delete_connector(self, name: str) -> None:
        req = urllib.request.Request(
            f"{self._base}/connectors/{name}",
            method="DELETE",
        )
        try:
            urllib.request.urlopen(req, timeout=self._timeout)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    async def get_connector_status(self, name: str) -> ConnectorState:
        url = f"{self._base}/connectors/{name}/status"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as r:
                body = json.load(r)
                connector_state = body.get("connector", {}).get("state", "UNASSIGNED")
                tasks = body.get("tasks", [])
                running = sum(1 for t in tasks if t.get("state") == "RUNNING")
                return ConnectorState(
                    connector_name=name,
                    status=ConnectorStatus(connector_state),
                    tasks_total=len(tasks),
                    tasks_running=running,
                    error_message=body.get("connector", {}).get("trace"),
                )
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return ConnectorState(name, ConnectorStatus.UNASSIGNED)
            raise

    async def list_connectors(self) -> List[str]:
        with urllib.request.urlopen(
            f"{self._base}/connectors", timeout=self._timeout
        ) as r:
            return json.load(r)

    async def pause_connector(self, name: str) -> None:
        req = urllib.request.Request(
            f"{self._base}/connectors/{name}/pause", method="PUT"
        )
        urllib.request.urlopen(req, timeout=self._timeout)

    async def resume_connector(self, name: str) -> None:
        req = urllib.request.Request(
            f"{self._base}/connectors/{name}/resume", method="PUT"
        )
        urllib.request.urlopen(req, timeout=self._timeout)
