"""有料の呼び出しの1日の上限（設計 8章、決まり C-04）。

全体の上限（300回/日）に加え、同じ接続元（IP）ごとの上限も数える。1人に全体の
上限を使い切られて、審査員が使えなくなるのを防ぐため。

インスタンスのメモリで数える。再起動で数え直しになるが、最大1インスタンスなので
大きくはずれない。提出後（11/14 まで）に人が止められなくても、費用が膨らまないため。
"""

import threading
from collections import Counter
from datetime import date

from app.errors import ApiError
from app.services.clock import now_jst


class DailyCallLimit:
    """日本時間の1日ごとに、有料の呼び出しの回数を全体と接続元ごとに数える。"""

    def __init__(self, limit: int, per_client: int):
        """1日に許す回数（全体・接続元ごと）で作る。"""
        self._limit, self._per_client = limit, per_client
        self._day: date | None = None
        self._total = 0
        self._by_client: Counter[str] = Counter()
        self._lock = threading.Lock()

    def _roll_over(self) -> None:
        """日が変わっていたら数え直す（ロックの中で呼ぶ）。"""
        today = now_jst().date()
        if self._day != today:
            self._day, self._total = today, 0
            self._by_client.clear()

    def take(self, calls: int, client: str) -> None:
        """これから呼ぶ回数を数える。上限を超えるなら呼ぶ前に止める。

        Raises:
            ApiError: 全体か接続元ごとの、今日の上限を超える場合（429）
        """
        with self._lock:
            self._roll_over()
            if self._total + calls > self._limit:
                raise ApiError(
                    429,
                    "daily_limit",
                    "今日の利用回数の上限に達しました。明日もう一度お試しください",
                )
            if self._by_client[client] + calls > self._per_client:
                raise ApiError(
                    429,
                    "client_daily_limit",
                    "この端末からの今日の利用回数の上限に達しました。明日もう一度お試しください",
                )
            self._total += calls
            self._by_client[client] += calls

    def give_back(self, calls: int, client: str) -> None:
        """失敗して下書きを返せなかった分を戻す（日が変わっていれば何もしない）。"""
        with self._lock:
            if self._day != now_jst().date():
                return
            self._total = max(0, self._total - calls)
            self._by_client[client] = max(0, self._by_client[client] - calls)
