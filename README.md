# ATLAS

ATLAS(Aegis Transaction Ledger & Accounting System)는 Aegis의 장부 검증,
동아리연합회 제출 패키지, 월간 회원 공개 자료와 Discord 공지를 관리하는 웹 서비스다.

## 구현 범위

- 장부 원본 행 해시 및 불변 스냅샷
- 잔액·기간·중복 거래·증빙 접근성·금액·날짜 검증
- `PASS`, `WARNING`, `ERROR`, `ACKNOWLEDGED` 검증 상태
- 하나의 거래에 여러 증빙을 연결하는 모델
- 비동기 제출 패키지 생성 및 작업 상태 조회
- Excel, DOCX, 검증 리포트, 증빙 원본, manifest, ZIP 생성
- 산출물별 SHA-256 및 ZIP 무결성 해시
- 패키지 `draft → pending_review → approved/rejected/superseded` 승인 흐름
- 만료·폐기·재발급·접근 로그를 지원하는 월간 공개 링크
- 검색엔진 색인 차단과 공개 필드 제한
- 암호화된 Google OAuth 토큰 및 Discord Webhook 저장
- Discord 미리보기, 별도 승인, 멱등 전송
- 이전 이벤트 해시를 연결한 감사 로그
- Google Sheets/Drive 실제 API 어댑터
- Aegis 장부와 토스뱅크 거래내역 Excel 자동 판별·파싱
- 장부 마감잔액과 은행 잔액 대사, 1:1·묶음 거래 자동 매칭
- 이미지와 다중 페이지 PDF 증빙의 DOCX 삽입
- 계좌 캡처와 토스 전체 거래내역을 함께 수록하는 계좌전체내역 DOCX
- 장부 건수에 따른 40/80/120칸 자동 확장과 원본 Excel 보존

## 로컬 테스트 서버

Docker Desktop을 실행한 뒤 프로젝트 루트에서 다음 명령을 실행한다.

```bash
docker compose up --build
```

- ATLAS: <http://localhost:5173>
- API 문서: <http://localhost:5173/api/docs>
- 상태 확인: <http://localhost:5173/api/health>

로컬 기본값은 데모 로그인 모드이므로 비밀번호를 비워둘 수 있다. 외부에 공개할 때는
반드시 `ATLAS_LOGIN_PASSWORD`를 설정해야 한다.

## 화면 테스트 순서

1. `관리자` 역할로 로그인한다.
2. `장부·증빙`에서 Aegis 회계장부 `.xlsx`와 토스뱅크 거래내역 `.xlsx`를 선택한다.
3. 영수증·소명자료·계좌 캡처의 종류와 장부 번호를 지정해 업로드한다.
4. `실제 장부 가져오기`를 누르고 잔액 차이가 `0원`인지 확인한다.
5. 증빙을 나중에 추가했다면 `증빙 반영 새 버전`으로 새 스냅샷을 만든다.
6. `동연 패키지`에서 생성 후 작업 상태와 문서 포함 건수를 확인한다.
7. 검증 오류가 없으면 `검토 요청`, `승인`, `ZIP 다운로드`를 차례로 실행한다.
8. `월간 공개`에서 공개 페이지를 생성하고 새 창에서 내용을 확인한다.
9. 테스트용 Discord Webhook으로 미리보기와 승인 흐름을 확인한다.
10. `감사 로그`에서 해시 체인이 `CHAIN VALID`인지 확인한다.

실제 Discord 채널로 보내도 되는 경우에만 마지막 전송 버튼을 누른다.

## 실제 파일 가져오기

지원하는 장부 헤더는 `NO, 날짜, 내용, 수입, 지출, 잔액, 처리방식, 상세정보`이며,
토스 파일은 `거래 일시, 적요, 거래 유형, 거래 금액, 거래 후 잔액, 메모` 헤더로
자동 판별한다. 파일명은 판별에 사용하지 않는다.

증빙 파일명에 `2_영수증.jpg`, `NO 15-소명.pdf`처럼 1~3자리 장부 번호가 있으면
번호를 자동 추론한다. 화면에서 번호를 지정한 경우 입력값을 우선한다. 이미지와 PDF는
문서에 직접 삽입되고, DOCX 등 직접 표시할 수 없는 형식도 원본이 ZIP에서 빠지지 않는다.

제출 ZIP에는 다음 항목이 포함된다.

- `수입지출관리대장.xlsx`: 거래 수에 맞춰 40/80/120칸을 자동 선택하며 120건 초과도 자르지 않는다.
- `영수증_및_소명자료.docx`: 지출별 메타데이터와 연결된 이미지/PDF 전체 페이지
- `계좌전체내역.docx`: 업로드된 계좌 캡처 전체와 토스 거래내역 전체 행
- `증빙자료/`: 업로드한 증빙 원본
- `원본자료/`: Aegis 장부와 토스뱅크 Excel 원본
- `검증_리포트.html`, `manifest.json`: 장부·은행 대사 결과와 모든 파일의 SHA-256

## 개발 실행

백엔드:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

프론트엔드:

```bash
cd frontend
npm install
npm run dev
```

Vite와 Nginx 모두 `/api` 요청을 FastAPI로 전달하므로 브라우저는 하나의 출처만 사용한다.

## 자동 테스트

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

```bash
cd frontend
npm run build
npm audit --audit-level=moderate
```

## VPS 배포

서버에서 `.env.example`을 `.env`로 만들고 다음 값을 반드시 변경한다.

- `ATLAS_DOMAIN`: DNS가 VPS를 가리키는 실제 도메인
- `ATLAS_SECRET_KEY`: OAuth와 Webhook 암호화용 긴 난수
- `ATLAS_LOGIN_PASSWORD`: 운영 화면 로그인 비밀번호
- `ATLAS_USER_ROLES`: 사용자명과 역할을 연결한 JSON 객체
- `PUBLIC_FRONTEND_BASE_URL`, `CORS_ORIGINS`: 실제 HTTPS 주소

안전한 난수는 다음처럼 만들 수 있다.

```ba
openssl rand -hex 32
```

배포 명령:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

Caddy가 도메인의 TLS 인증서를 자동 발급하고, 외부에는 80/443 포트만 노출한다.

Cloudflare Tunnel을 사용하는 경우 Public Hostname의 서비스는
`http://127.0.0.1:5173`으로 지정한다. 운영 Compose는 이 포트를 loopback에만
게시하므로 외부에서는 직접 접근할 수 없고 Tunnel을 통해서만 접근한다. 배포 후에는
원본 서버에서 `curl http://127.0.0.1:5173/api/health`가 먼저 성공해야 한다.

## Google 연동

Google Cloud Console에서 OAuth 클라이언트를 만들고 `.env`에 `GOOGLE_CLIENT_ID`와
`GOOGLE_CLIENT_SECRET`을 설정한다. 승인된 리디렉션 URI에는 로컬 테스트용
`http://localhost:5173/`와 운영 주소 `https://<ATLAS_DOMAIN>/`를 등록한다.
ATLAS는 계정 이메일과 읽기 전용 Sheets/Drive Scope만 요청하며 OAuth `state`는
로그인 세션에 묶고 한 번 사용하면 폐기한다.

- `GET /auth/google/authorize-url`
- `POST /auth/google/connect`
- `GET /auth/google/status`
- `POST /auth/google/disconnect`
- `GET /google/sheets`
- `GET /google/drive/files`
- `POST /google/sheets/{spreadsheet_id}/snapshot`

파일 기반 운영 API:

- `POST /imports/upload`
- `POST /imports/workbook-snapshot`
- `POST /evidence/upload`
- `POST /ledger-snapshots/{snapshot_id}/evidence`
- `GET /ledger-snapshots/{snapshot_id}`

## 운영 주의사항

- `backend/storage`, `.env`, 실제 은행 거래내역 `sample/*.xlsx`는 Git에서 제외된다.
- 운영 백업에는 `backend/storage` 디렉터리 전체를 포함해야 한다.
- 기본 업로드 한도는 파일당 50MB이며 `ATLAS_MAX_UPLOAD_BYTES`로 조정한다.
- `ATLAS_SECRET_KEY`를 변경하면 기존 암호화 토큰과 Webhook을 복호화할 수 없다.
- 현재 내장 JSON 저장소와 작업 큐는 단일 VPS·소규모 동아리 운영을 기준으로 한다.
  다중 서버 배포나 대량 작업이 필요하면 PostgreSQL과 Redis 기반 Worker로 교체한다.
- 공개 저장소에 올리기 전 공식 매뉴얼과 양식의 재배포 권한을 확인한다.
