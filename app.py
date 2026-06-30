"""한라산 작두 온라인 랭킹 API — FastAPI + SQLite.

실행:
  cd server
  pip install -r requirements.txt
  python app.py

기본 포트: 8787
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 클라우드 호스팅(Render/Railway/Fly 등)은 PORT 환경변수를 주입한다.
# 영구 디스크가 있으면 DATA_DIR 을 그 경로로 지정하면 DB 가 재배포에도 보존된다.
_DEFAULT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(_DEFAULT_DIR)))
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "leaderboard.db")))
# 게임 웹 빌드(정적 파일)를 같은 서버에서 서빙한다. (build/web 을 여기로 복사)
WEB_DIR = Path(os.environ.get("WEB_DIR", str(_DEFAULT_DIR / "web")))
PORT = int(os.environ.get("PORT", "8787"))
MAX_NAME_LEN = 16
MAX_RUNS_PER_REQUEST = 20

try:
  DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
  pass

app = FastAPI(title="Hallasan Jakdu Leaderboard", version="1")
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)


def _sanitize_name(name: str) -> str:
  text = re.sub(r"\s+", " ", (name or "").strip())
  if not text:
    return "익명"
  return text[:MAX_NAME_LEN]


@contextmanager
def _db():
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  try:
    conn.execute("""
      CREATE TABLE IF NOT EXISTS scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stage INTEGER NOT NULL DEFAULT 0,
        damage INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(device_id, run_id)
      )
    """)
    conn.execute(
      "CREATE INDEX IF NOT EXISTS idx_scores_stage ON scores(stage DESC, damage DESC)"
    )
    conn.execute(
      "CREATE INDEX IF NOT EXISTS idx_scores_damage ON scores(damage DESC, stage DESC)"
    )
    conn.commit()
    yield conn
    conn.commit()
  finally:
    conn.close()


class RunEntry(BaseModel):
  run_id: str = Field(min_length=4, max_length=64)
  stage: int = Field(ge=0, le=9999)
  damage: int = Field(ge=0, le=999_999_999)
  wins: int = Field(ge=0, le=9999)


class SubmitBody(BaseModel):
  device_id: str = Field(min_length=8, max_length=64)
  name: str = Field(default="익명", max_length=MAX_NAME_LEN)
  runs: list[RunEntry] = Field(default_factory=list, max_length=MAX_RUNS_PER_REQUEST)


class LeaderboardRow(BaseModel):
  rank: int
  name: str
  stage: int
  damage: int
  wins: int


@app.get("/api/health")
def health() -> dict[str, bool]:
  return {"ok": True}


@app.post("/api/scores")
def submit_scores(body: SubmitBody) -> dict[str, int]:
  name = _sanitize_name(body.name)
  inserted = 0
  with _db() as conn:
    for run in body.runs[:MAX_RUNS_PER_REQUEST]:
      cur = conn.execute(
        """
        INSERT INTO scores (device_id, run_id, name, stage, damage, wins)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id, run_id) DO UPDATE SET
          name = excluded.name,
          stage = MAX(scores.stage, excluded.stage),
          damage = MAX(scores.damage, excluded.damage),
          wins = MAX(scores.wins, excluded.wins),
          submitted_at = datetime('now')
        """,
        (body.device_id, run.run_id, name, run.stage, run.damage, run.wins),
      )
      if cur.rowcount:
        inserted += 1
  return {"accepted": inserted, "total": len(body.runs)}


@app.get("/api/leaderboard")
def leaderboard(
  sort: Literal["stage", "damage"] = "stage",
  limit: int = 50,
) -> dict[str, Any]:
  limit = max(1, min(limit, 100))
  order = (
    "best_stage DESC, best_damage DESC, best_wins DESC"
    if sort == "stage"
    else "best_damage DESC, best_stage DESC, best_wins DESC"
  )
  with _db() as conn:
    rows = conn.execute(
      f"""
      SELECT name, best_stage AS stage, best_damage AS damage, best_wins AS wins
      FROM (
        SELECT
          device_id,
          name,
          MAX(stage) AS best_stage,
          MAX(damage) AS best_damage,
          MAX(wins) AS best_wins
        FROM scores
        GROUP BY device_id
      )
      ORDER BY {order}
      LIMIT ?
      """,
      (limit,),
    ).fetchall()
  out: list[dict] = []
  for i, row in enumerate(rows, start=1):
    out.append({
      "rank": i,
      "name": row["name"],
      "stage": int(row["stage"]),
      "damage": int(row["damage"]),
      "wins": int(row["wins"]),
    })
  return {"sort": sort, "entries": out}


# 게임 정적 파일을 루트에 마운트한다. API 라우트(/api/*)는 위에서 먼저 정의되어
# 우선 매칭되고, 그 외 경로(/, /card.apk, /favicon.png 등)는 정적 파일로 서빙된다.
# web 폴더가 없으면(서버만 배포한 경우) 안내용 JSON 루트를 제공한다.
if WEB_DIR.is_dir():
  app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:
  @app.get("/")
  def root() -> dict[str, str]:
    return {"service": "hallasan-jakdu-leaderboard", "health": "/api/health"}


if __name__ == "__main__":
  import uvicorn
  uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
