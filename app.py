"""한라산 작두 온라인 랭킹 API — FastAPI + (Postgres | SQLite).

저장소:
  - 환경변수 DATABASE_URL 이 있으면 Postgres(Neon 등)를 사용한다. (영구 보존)
    Render 무료 플랜은 디스크가 휘발성이라, 외부 DB(Neon)를 써야 셧다운/재배포
    후에도 랭킹이 남는다.
  - DATABASE_URL 이 없으면 로컬 개발용 SQLite 파일을 쓴다.

로컬 실행:
  cd server
  pip install -r requirements.txt
  python app.py            # SQLite
  # 또는 DATABASE_URL=postgres://... python app.py   # Postgres

기본 포트: 8787
"""

from __future__ import annotations

import json as _json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# 클라우드 호스팅(Render 등)은 PORT 환경변수를 주입한다.
PORT = int(os.environ.get("PORT", "8787"))
MAX_NAME_LEN = 16
MAX_RUNS_PER_REQUEST = 20

# Render Postgres 는 가끔 'postgres://' 스킴을 주는데 psycopg 는 'postgresql://'
# 도 받는다. 둘 다 그대로 동작하지만 통일해 둔다.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
  DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
USE_PG = bool(DATABASE_URL)

# 게임 웹 빌드(정적 파일)를 같은 서버에서 서빙한다. (build/web 을 여기로 복사)
_DEFAULT_DIR = Path(__file__).resolve().parent
WEB_DIR = Path(os.environ.get("WEB_DIR", str(_DEFAULT_DIR / "web")))

if USE_PG:
  import psycopg
  from psycopg.rows import dict_row
else:
  import sqlite3

  DATA_DIR = Path(os.environ.get("DATA_DIR", str(_DEFAULT_DIR)))
  DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "leaderboard.db")))
  try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
  except Exception:
    pass

# 방언별 차이
PH = "%s" if USE_PG else "?"          # 파라미터 자리표시자
GREATEST = "GREATEST" if USE_PG else "MAX"  # 두 값 중 큰 값 (스칼라)
NOW = "NOW()" if USE_PG else "datetime('now')"
_ID_COL = "BIGSERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"

app = FastAPI(title="Hallasan Jakdu Leaderboard", version="2")
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)


def _connect():
  if USE_PG:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)
  conn = sqlite3.connect(DB_PATH)
  conn.row_factory = sqlite3.Row
  return conn


@contextmanager
def _db():
  conn = _connect()
  try:
    yield conn
    conn.commit()
  finally:
    conn.close()


def _init_db() -> None:
  with _db() as conn:
    conn.execute(f"""
      CREATE TABLE IF NOT EXISTS scores (
        id {_ID_COL},
        device_id TEXT NOT NULL,
        run_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stage INTEGER NOT NULL DEFAULT 0,
        damage INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        submitted_at TEXT NOT NULL DEFAULT '',
        UNIQUE(device_id, run_id)
      )
    """)
    conn.execute(
      "CREATE INDEX IF NOT EXISTS idx_scores_stage ON scores(stage DESC, damage DESC)"
    )
    conn.execute(
      "CREATE INDEX IF NOT EXISTS idx_scores_damage ON scores(damage DESC, stage DESC)"
    )


def _sanitize_name(name: str) -> str:
  text = re.sub(r"\s+", " ", (name or "").strip())
  if not text:
    return "익명"
  return text[:MAX_NAME_LEN]


def _ascii_json(payload: dict) -> Response:
  """랭킹 응답은 ASCII(\\uXXXX)로 직렬화한다.

  pygbag(웹) 클라이언트는 fetch 응답 텍스트를 JS→Python 으로 변환하는데, 이때
  멀티바이트(한글)가 깨진다. 응답을 ASCII 로 보내면 변환에 안전하고, 클라이언트
  의 json.loads 가 원래 문자로 복원한다.
  """
  return Response(
    content=_json.dumps(payload, ensure_ascii=True),
    media_type="application/json",
  )


class RunEntry(BaseModel):
  run_id: str = Field(min_length=4, max_length=64)
  stage: int = Field(ge=0, le=9999)
  damage: int = Field(ge=0, le=999_999_999)
  wins: int = Field(ge=0, le=9999)


class SubmitBody(BaseModel):
  device_id: str = Field(min_length=8, max_length=64)
  name: str = Field(default="익명", max_length=MAX_NAME_LEN)
  runs: list[RunEntry] = Field(default_factory=list, max_length=MAX_RUNS_PER_REQUEST)


@app.get("/api/health")
def health() -> dict[str, bool]:
  return {"ok": True}


@app.post("/api/scores")
def submit_scores(body: SubmitBody) -> Response:
  name = _sanitize_name(body.name)
  inserted = 0
  upsert = f"""
    INSERT INTO scores (device_id, run_id, name, stage, damage, wins, submitted_at)
    VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {NOW})
    ON CONFLICT(device_id, run_id) DO UPDATE SET
      name = excluded.name,
      stage = {GREATEST}(scores.stage, excluded.stage),
      damage = {GREATEST}(scores.damage, excluded.damage),
      wins = {GREATEST}(scores.wins, excluded.wins),
      submitted_at = {NOW}
  """
  with _db() as conn:
    for run in body.runs[:MAX_RUNS_PER_REQUEST]:
      cur = conn.execute(
        upsert,
        (body.device_id, run.run_id, name, run.stage, run.damage, run.wins),
      )
      rc = cur.rowcount
      if rc and rc > 0:
        inserted += 1
  return _ascii_json({"accepted": inserted, "total": len(body.runs)})


@app.get("/api/leaderboard")
def leaderboard(
  sort: Literal["stage", "damage"] = "stage",
  limit: int = 50,
) -> Response:
  limit = max(1, min(limit, 100))
  order = (
    "best_stage DESC, best_damage DESC, best_wins DESC"
    if sort == "stage"
    else "best_damage DESC, best_stage DESC, best_wins DESC"
  )
  query = f"""
    SELECT name, best_stage AS stage, best_damage AS damage, best_wins AS wins
    FROM (
      SELECT
        device_id,
        MAX(name) AS name,
        MAX(stage) AS best_stage,
        MAX(damage) AS best_damage,
        MAX(wins) AS best_wins
      FROM scores
      GROUP BY device_id
    ) AS agg
    ORDER BY {order}
    LIMIT {PH}
  """
  with _db() as conn:
    rows = conn.execute(query, (limit,)).fetchall()
  out: list[dict] = []
  for i, row in enumerate(rows, start=1):
    out.append({
      "rank": i,
      "name": row["name"],
      "stage": int(row["stage"]),
      "damage": int(row["damage"]),
      "wins": int(row["wins"]),
    })
  return _ascii_json({"sort": sort, "entries": out})


_init_db()

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
