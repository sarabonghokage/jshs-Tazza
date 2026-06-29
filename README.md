# 한라산 작두 — 온라인 랭킹 서버

전체 랭킹을 위한 작은 API 서버입니다. (FastAPI + SQLite)

배포 후 받은 **https 주소**를 게임의 `game/leaderboard_config.py` →
`LEADERBOARD_URL` 에 넣고 웹/APK 를 다시 빌드하면 전체 랭킹이 켜집니다.

> 모바일(APK)에서는 반드시 **https** 주소여야 합니다. http 는 WebView 가 차단합니다.

---

## 가장 쉬운 방법: Render (무료 · 신용카드 불필요 · 자동 HTTPS)

준비물: GitHub 계정, Render 계정 (둘 다 무료).

### 1) 코드를 GitHub 에 올리기

이 `server/` 폴더만 올리면 됩니다. PowerShell 에서:

```powershell
cd c:\Users\user\Desktop\card\server
git init
git add .
git commit -m "leaderboard server"
git branch -M main
git remote add origin https://github.com/<내아이디>/hallasan-leaderboard.git
git push -u origin main
```

(먼저 GitHub 에서 빈 저장소 `hallasan-leaderboard` 를 하나 만들어 두세요.)

### 2) Render 에서 배포

1. https://render.com 가입/로그인
2. **New +** → **Web Service**
3. 방금 만든 GitHub 저장소 연결
4. 설정값 (대부분 자동 인식):
   - Language/Runtime: **Docker**
   - Region: Singapore (한국에서 가장 가까움)
   - Plan: **Free**
5. **Create Web Service** 클릭 → 빌드/배포가 끝나면
   `https://hallasan-leaderboard.onrender.com` 같은 주소가 나옵니다.

### 3) 동작 확인

브라우저로 `https://<주소>/api/health` 열어서 `{"ok":true}` 가 보이면 성공.

### 4) 게임에 주소 연결

`game/leaderboard_config.py` 수정:

```python
LEADERBOARD_URL = "https://hallasan-leaderboard.onrender.com"
```

그 뒤 APK 재빌드:

```powershell
cd c:\Users\user\Desktop\card
python -m pygbag --build main.py
cd mobile
node scripts/copy-web.mjs
npx cap sync android
cd android
./gradlew.bat assembleDebug
```

> Render 무료 플랜 주의:
> - 15분간 요청이 없으면 서버가 잠들고, 다음 첫 요청은 30초쯤 느립니다(정상).
> - 무료 플랜은 영구 디스크가 없어 **재배포 시 랭킹이 초기화**됩니다.
>   영구 보존이 필요하면 Render 유료 디스크나 아래 Fly.io 볼륨을 쓰세요.

---

## 대안 A: Fly.io (영구 볼륨으로 랭킹 영구 보존)

준비물: Fly.io 계정(가입 시 카드 등록 필요), flyctl CLI.

```powershell
# 1) flyctl 설치
iwr https://fly.io/install.ps1 -useb | iex
# 2) 로그인
fly auth login
# 3) server 폴더에서 앱 생성(이미 fly.toml 있음 — 이름 충돌 시 app 값 변경)
cd c:\Users\user\Desktop\card\server
fly launch --no-deploy --copy-config --name <원하는고유이름>
# 4) 랭킹 영구 보존 볼륨 생성
fly volumes create data --size 1 --region nrt
# 5) 배포
fly deploy
```

배포 후 `https://<앱이름>.fly.dev` 주소가 나옵니다.

---

## 대안 B: Railway

준비물: Railway 계정, Railway CLI.

```powershell
npm i -g @railway/cli
railway login
cd c:\Users\user\Desktop\card\server
railway init
railway up
```

대시보드에서 **Settings → Networking → Generate Domain** 으로 https 주소를 만듭니다.

---

## 로컬 테스트 (PC 에서만)

```powershell
cd c:\Users\user\Desktop\card\server
pip install -r requirements.txt
python app.py
```

`http://127.0.0.1:8787/api/health` 확인.
(폰에서는 127.0.0.1 이 폰 자신이라 PC 서버에 닿지 않습니다 — 반드시 배포해야 함.)

---

## API 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 상태 확인 |
| POST | `/api/scores` | 기록 업로드(기기별 중복 방지) |
| GET | `/api/leaderboard?sort=stage\|damage&limit=50` | 전체 랭킹 조회 |

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `PORT` | 8787 | 서버 포트(호스팅이 자동 주입) |
| `DATA_DIR` | 스크립트 폴더 | DB 저장 위치(영구 볼륨 경로로 지정 권장) |
| `DB_PATH` | `DATA_DIR/leaderboard.db` | DB 파일 경로 직접 지정 |
