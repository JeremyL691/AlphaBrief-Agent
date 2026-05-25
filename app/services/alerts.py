from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.market.spreads import SpreadCandidate
from app.models import Alert


def create_spread_alerts(db: Session, spreads: list[SpreadCandidate], threshold_pct: float) -> int:
    inserted = 0
    for spread in spreads:
        if spread.net_spread_pct < threshold_pct:
            continue
        message = (
            f"{spread.symbol} net spread is {spread.net_spread_pct:.4f}% "
            f"buying on {spread.buy_exchange} and selling on {spread.sell_exchange}."
        )
        db.add(
            Alert(
                alert_type="spread_threshold",
                symbol=spread.symbol,
                severity="warning" if spread.net_spread_pct < threshold_pct * 1.5 else "critical",
                message=message,
                trigger_data_json=json.dumps(
                    {
                        "buy_exchange": spread.buy_exchange,
                        "sell_exchange": spread.sell_exchange,
                        "net_spread_pct": spread.net_spread_pct,
                        "estimated_profit": spread.estimated_profit,
                    }
                ),
            )
        )
        inserted += 1
    return inserted
