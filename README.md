AI기반 비즈니스 진화_전략 및 실습 

14조 박건민/안정희/이준범/최보미

## 로컬 실행

```bash
source .venv/bin/activate
uvicorn api.index:app --reload --port 3000
```

## Google 로그인 환경변수

Google OAuth를 쓰려면 Vercel 환경변수나 `.env.local`에 아래 값을 설정합니다.

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:3000/auth/google/callback
SESSION_SECRET=change-me
```
