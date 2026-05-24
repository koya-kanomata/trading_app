from __future__ import annotations

import csv
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List


@dataclass
class OrderRequest:
    code: str
    side: str
    qty: int
    order_type: str
    limit_price: float
    stop_loss: float
    take_profit: float
    reason: str


@dataclass
class OrderResult:
    order_id: str
    status: str
    message: str


class BrokerAdapter:
    def place_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    def fetch_positions(self) -> List[Dict]:
        return []

    def fetch_fills(self) -> List[Dict]:
        return []


class PaperBrokerAdapter(BrokerAdapter):
    def __init__(self, base_dir: Path, queue_csv: str) -> None:
        self.base_dir = base_dir
        self.queue_path = base_dir / queue_csv

    def place_order(self, order: OrderRequest) -> OrderResult:
        order_id = str(uuid.uuid4())
        new_file = not self.queue_path.exists()

        with self.queue_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "created_at",
                    "order_id",
                    "code",
                    "side",
                    "qty",
                    "order_type",
                    "limit_price",
                    "stop_loss",
                    "take_profit",
                    "reason",
                    "status",
                ],
            )
            if new_file:
                writer.writeheader()
            writer.writerow(
                {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "order_id": order_id,
                    "code": order.code,
                    "side": order.side,
                    "qty": order.qty,
                    "order_type": order.order_type,
                    "limit_price": f"{order.limit_price:.1f}",
                    "stop_loss": f"{order.stop_loss:.1f}",
                    "take_profit": f"{order.take_profit:.1f}",
                    "reason": order.reason,
                    "status": "QUEUED",
                }
            )

        return OrderResult(order_id=order_id, status="QUEUED", message="Queued for broker execution")


class SbiBrokerAdapter(BrokerAdapter):
    def __init__(self, env_map: Dict[str, str]) -> None:
        self.user = os.getenv(env_map.get("user", "SBI_USER"), "")
        self.password = os.getenv(env_map.get("password", "SBI_PASSWORD"), "")
        self.token = os.getenv(env_map.get("token", "SBI_API_TOKEN"), "")

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not (self.user and self.password):
            return OrderResult(
                order_id="",
                status="REJECTED",
                message="Missing SBI credentials in environment variables",
            )

        return OrderResult(
            order_id="",
            status="REJECTED",
            message="SBI execution adapter is a placeholder until official API spec is configured",
        )


def build_broker(config: Dict, base_dir: Path) -> BrokerAdapter:
    broker_name = str(config.get("broker", "paper")).lower()
    if broker_name == "sbi":
        return SbiBrokerAdapter(config.get("sbi_env", {}))
    return PaperBrokerAdapter(base_dir, str(config["order_queue_csv"]))
