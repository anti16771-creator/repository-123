# PredictX 배포 가이드 — Vercel (프론트) + Render (백엔드)

## 전체 흐름

```
GitHub 저장소
    ├── backend/   →  Render  (FastAPI + AI 모델)  무료
    └── frontend/  →  Vercel  (HTML 대시보드)       무료
```

---

## STEP 1 — GitHub 저장소 만들기

```bash
# 압축 해제 후
cd predictx
git init
git add .
git commit -m "first commit"
```

github.com → New repository → 이름: `predictx` → Create

```bash
git remote add origin https://github.com/YOUR_ID/predictx.git
git push -u origin main
```

---

## STEP 2 — Render 백엔드 배포 (무료)

1. **render.com** 접속 → 회원가입 (GitHub 로그인 가능)
2. `New` → `Web Service`
3. GitHub 저장소 `predictx` 선택
4. 설정 확인:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
5. `Create Web Service` 클릭
6. 배포 완료 후 주소 복사:
   ```
   https://predictx-backend-xxxx.onrender.com   ← 이 주소를 메모
   ```

> ⚠️ Render 무료 플랜은 15분 비활성 시 슬립합니다.
> 첫 요청 시 30초~1분 웜업 시간이 있습니다.

---

## STEP 3 — Vercel 프론트엔드 배포 (무료)

1. **vercel.com** 접속 → 회원가입 (GitHub 로그인)
2. `New Project` → GitHub 저장소 `predictx` import
3. **Framework Preset**: `Other`
4. **Root Directory**: `frontend` (중요!)
5. **Environment Variables** 추가:
   ```
   이름:  NEXT_PUBLIC_BACKEND_URL   (무시해도 됨, 아래 방법 사용)
   ```
6. `Deploy` 클릭

**배포 후 백엔드 주소 연결:**

`frontend/index.html` 파일에서 아래 줄을 찾아 수정:
```js
const BACKEND_URL = window.__BACKEND_URL__ || '';
```
→ Render 주소로 변경:
```js
const BACKEND_URL = 'https://predictx-backend-xxxx.onrender.com';
```

수정 후 git push → Vercel 자동 재배포됩니다.

---

## STEP 4 — 완료 확인

| 항목 | 주소 |
|------|------|
| 대시보드 | `https://predictx-xxxx.vercel.app` |
| API 문서 | `https://predictx-backend-xxxx.onrender.com/docs` |
| 헬스체크 | `https://predictx-backend-xxxx.onrender.com/health` |

---

## 무료 플랜 한도 정리

| 서비스 | 무료 한도 | 제한 사항 |
|--------|-----------|-----------|
| Vercel | 무제한 | 상업용은 Pro 필요 |
| Render | 월 750시간 | 15분 비활성 시 슬립 |

## Render 슬립 방지 (선택)

무료로 슬립을 방지하려면 UptimeRobot (무료)으로 5분마다 헬스체크:
1. uptimerobot.com 가입
2. `New Monitor` → HTTP(s)
3. URL: `https://predictx-backend-xxxx.onrender.com/health`
4. Interval: 5분
