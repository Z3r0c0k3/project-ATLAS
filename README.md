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
- 장부 건수에 따른 동아리연합회 공식 40/80/120칸 원본 양식 선택 및 값 기입

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
2. `장부·증빙`에서 두 Google 장부를 연결한다.
3. 계좌 거래내역과 영수증·소명자료·계좌 캡처를 업로드한다.
4. 거래 목록에서 두 계좌가 분리되어 표시되고 증빙 돋보기로 원본이 열리는지 확인한다.
5. `스냅샷 관리`에서 계좌별 최신 버전과 이력을 확인하고 필요한 체크포인트를 생성한다.
6. `동연 패키지`에서 두 계좌 상태가 `READY`인지 확인하고 패키지를 생성한다.
7. 검증 오류가 없으면 `검토 요청`, `승인`, `ZIP 다운로드`를 차례로 실행한다.
8. `월간 공개`에서 공개 월과 링크 만료일을 지정해 ATLAS 공개 페이지를 생성한다.
9. 같은 화면에서 테스트용 Discord Webhook으로 미리보기, 승인, 전송 흐름을 확인한다.

실제 Discord 채널로 보내도 되는 경우에만 마지막 전송 버튼을 누른다.

Google 장부 연결, 증빙 연결, 계좌내역 연결은 각각 새 스냅샷을 자동 생성한다. `스냅샷 관리`의
수동 생성은 현재 최신 상태를 체크포인트로 복제하고, 복원은 선택한 과거 상태를 새 최신 버전으로
복제하므로 기존 이력을 덮어쓰지 않는다.

## 실제 파일 가져오기

지원하는 장부 헤더는 `NO, 날짜, 내용, 수입, 지출, 잔액, 처리방식, 상세정보`이며,
토스 파일은 `거래 일시, 적요, 거래 유형, 거래 금액, 거래 후 잔액, 메모` 헤더로
자동 판별한다. 파일명은 판별에 사용하지 않는다.

증빙 파일명 앞에 `#15# 2026. 3. 1. 결제 설명.pdf`처럼 `#장부ID#`를 붙이면
동아리운영계좌(토스뱅크) 자료로 확정 매칭한다. 회비입금계좌(IBK기업은행)의 환불·입금검증 소명자료는
`*15* 2026. 3. 1. 회비 환불 소명.pdf`처럼 `*장부ID*`를 붙이면 해당 장부 번호와
회비입금계좌(IBK기업은행)로 확정 매칭한다. 화면에서 번호와 계좌를 지정한 경우 입력값을 우선한다.
날짜형 파일명(`2026. 3. 1...`)의 월/일은 장부 번호로 자동 추론하지 않는다. PDF, JPEG,
PNG, HEIC, HEIF는 문서에 직접 삽입되고, DOCX 등 직접 표시할 수 없는 형식도 원본이 ZIP에서
빠지지 않는다.

제출 문서는 `sample/동연-동아리_표준회계양식`의 공식 파일을 복제해 작성하며 임의로 비슷한
서식을 새로 만들지 않는다. Docker 이미지에는 기존 `.xls` 원본을 읽기 위한 LibreOffice
Calc가 포함된다.

제출 ZIP에는 다음 항목이 포함된다.

- `수입지출관리대장.xlsx`: 거래 수에 맞는 공식 40/80/120칸 `.xls` 원본을 변환하고 기존 셀·수식·인쇄영역에 값만 기입한다. 120건 초과 시 임의 확장하지 않고 오류를 반환한다.
- `영수증_및_소명자료.docx`: 공식 DOCX의 증빙·소명 슬롯과 기존 메타데이터 칸에 연결된 이미지/PDF 전체 페이지를 기입한다.
- `계좌전체내역.docx`: 공식 DOCX의 2×2 계좌 캡처 슬롯과 동아리명·회장 서명란에 값을 기입한다.
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

Vite와 로컬 Docker 환경은 `/api` 요청을 FastAPI로 전달하므로 브라우저는 하나의 출처만 사용한다.
운영 Docker 환경은 Cloudflare Tunnel에 맞춰 프론트엔드와 백엔드를 서로 다른 호스트명으로 분리한다.

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

- `ATLAS_DOMAIN`: 프론트엔드 공개 도메인, 예: `atlas.dkuaegis.org`
- `ATLAS_API_DOMAIN`: 백엔드 공개 도메인, 예: `atlas-api.dkuaegis.org`
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

운영 Compose는 Caddy 같은 리버스 프록시를 포함하지 않는다. 호스트에는 다음 포트만
loopback으로 열린다.

- `127.0.0.1:5173`: 프론트엔드 Nginx
- `127.0.0.1:8000`: FastAPI 백엔드

Cloudflare Tunnel의 Public Hostname은 두 개를 만든다.

- `atlas.dkuaegis.org` → `http://127.0.0.1:5173`
- `atlas-api.dkuaegis.org` → `http://127.0.0.1:8000`

배포 후 원본 서버에서 `curl http://127.0.0.1:5173`와
`curl http://127.0.0.1:8000/health`가 먼저 성공해야 한다. 그 다음 외부에서
`https://atlas.dkuaegis.org`와 `https://atlas-api.dkuaegis.org/health`를 확인한다.

Cloudflare Universal SSL을 쓰는 일반적인 full setup에서는 `*.dkuaegis.org` 같은
1단계 서브도메인까지만 자동 인증서가 적용된다. 따라서 `api.atlas.dkuaegis.org`처럼
2단계 서브도메인을 쓰면 브라우저가 `ERR_SSL_VERSION_OR_CIPHER_MISMATCH`를 낼 수 있다.
이 주소를 꼭 써야 한다면 Cloudflare Advanced Certificate Manager, Total TLS 또는
해당 호스트명을 포함한 Custom SSL 인증서가 필요하다.

## Google 연동

Google Cloud Console에서 OAuth 클라이언트를 만들고 `.env`에 `GOOGLE_CLIENT_ID`와
`GOOGLE_CLIENT_SECRET`을 설정한다. 현재 ATLAS OAuth 콜백은 프론트엔드에서 처리하므로
승인된 리디렉션 URI에는 로컬 테스트용 `http://localhost:5173/`와 운영 주소
`https://<ATLAS_DOMAIN>/`를 등록한다. 백엔드 도메인 `https://<ATLAS_API_DOMAIN>/`는
Google OAuth 리디렉션 URI가 아니라 API 호출과 CORS 대상이다.
ATLAS는 장부 읽기와 월별 공개 시트 생성·공유를 위해 Sheets/Drive 쓰기 Scope를 요청한다.
월별 공개 대상 Spreadsheet는 파일 전체가 링크 공개되므로, 다른 내부 자료가 없는 공개 전용 파일을 사용한다.
OAuth `state`는 로그인 세션에 묶고 한 번 사용하면 폐기한다. 이전 읽기 전용 연결이
저장되어 있다면 화면에서 연결 해제 후 다시 연결해야 한다.

OAuth 클라이언트가 속한 Google Cloud 프로젝트에서는 다음 API를 반드시 활성화한다.

- Google Drive API: 파일 조회와 월별 공개 Spreadsheet의 링크 공유 설정에 사용
- Google Sheets API: 장부 읽기와 월별 공개 시트 생성·값 쓰기에 사용

`Google Drive API has not been used ... or it is disabled` 오류가 나오면 해당 프로젝트의
Google Drive API를 Enable하고 몇 분 뒤 다시 시도한다.

승인된 JavaScript 원본에는 `http://localhost:5173`와 `https://<ATLAS_DOMAIN>`을
등록한다. Google 계정 연결은 성공했는데 Sheets/Drive 버튼에서 502가 뜬다면
리디렉션 URI보다 Cloudflare Tunnel의 `api.<도메인>` 라우팅과 백엔드 컨테이너 상태를
먼저 확인한다.

- `GET /auth/google/authorize-url`
- `POST /auth/google/connect`
- `GET /auth/google/status`
- `POST /auth/google/disconnect`
- `GET /google/sheets`
- `GET /google/drive/files`
- `POST /google/sheets/snapshot`
- `POST /google/sheets/{spreadsheet_id}/snapshot`
- `POST /monthly-reports/google-sheet`

운영 장부는 화면의 `Google 자료 연결` 패널에서 Google 계정 연결 후 회계장부 URL 또는
스프레드시트 ID를 입력하고 `Google 장부 가져오기`를 누르면 ATLAS 스냅샷으로 저장된다.
운영에서 기본 장부 URL을 미리 채우려면 `.env`에 `ATLAS_DEFAULT_LEDGER_SHEET_URL`을 설정한다.
월별 공개 대상 Spreadsheet를 미리 채우려면 `ATLAS_DEFAULT_MONTHLY_PUBLIC_SHEET_URL`을 설정한다.
장부 데이터는 `B:I`(`No`, `날짜`, `내용`, `수입`, `지출`, `잔액`, `처리방식`,
`상세정보`) 범위에서 가져온다. 시트 탭 이름이 필요한 경우 범위를 `시트명!B:I`
형식으로 입력한다.

파일 기반 운영 API:

- `POST /imports/upload`
- `POST /imports/workbook-snapshot`
- `POST /evidence/upload`
- `POST /ledger-snapshots/{snapshot_id}/evidence`
- `POST /ledger-snapshots/{snapshot_id}/bank-transactions`
- `POST /ledger-snapshots/{snapshot_id}/transactions`
- `PUT /ledger-snapshots/{snapshot_id}/transactions/{transaction_id_or_number}`
- `DELETE /ledger-snapshots/{snapshot_id}/transactions/{transaction_id_or_number}`
- `GET /ledger-snapshots/{snapshot_id}`

## 운영 주의사항

- `backend/storage`, `.env`, 실제 은행 거래내역 `sample/*.xlsx`는 Git에서 제외된다.
- 운영 백업에는 `backend/storage` 디렉터리 전체를 포함해야 한다.
- 기본 업로드 한도는 파일당 50MB이며 `ATLAS_MAX_UPLOAD_BYTES`로 조정한다.
- `ATLAS_SECRET_KEY`를 변경하면 기존 암호화 토큰과 Webhook을 복호화할 수 없다.
- 현재 내장 JSON 저장소와 작업 큐는 단일 VPS·소규모 동아리 운영을 기준으로 한다.
  다중 서버 배포나 대량 작업이 필요하면 PostgreSQL과 Redis 기반 Worker로 교체한다.
- 공개 저장소에 올리기 전 공식 매뉴얼과 양식의 재배포 권한을 확인한다.
