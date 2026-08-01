# ATLAS

ATLAS(Aegis Transaction Ledger & Accounting System)는 Aegis의 회계 검증과
동아리연합회 제출 자료, 월간 회원 공개 자료, Discord 공지를 자동화하는 웹 서비스다.

## v1 범위

- 수입·지출 및 거래별 잔액 연속성 검증
- 지출 거래의 영수증 또는 소명자료 매핑 검증
- 동연 제출용 Excel, DOCX, 검증 리포트 및 ZIP 생성
- 로그인 없이 볼 수 있는 월간 회계 공개 페이지 생성
- Discord 메시지 미리보기 및 승인 후 Webhook 전송
- Google Sheets/Drive 연동용 API 인터페이스와 파일 업로드 API

> 현재 Google Sheets/Drive 화면은 연동 인터페이스를 확인하는 단계다. 실제 Google
> OAuth와 파일 조회는 Google Cloud 자격 증명을 발급한 뒤 연결해야 한다. v1 로그인도
> 개발용 역할 선택 방식이므로 외부 공개 배포 전 실제 인증으로 교체해야 한다.

## 가장 빠른 실행: Docker

Docker Desktop을 실행한 뒤 프로젝트 루트에서 다음 명령을 실행한다.

```bash
docker compose up --build
```

- 운영 화면: <http://localhost:5173>
- 백엔드 API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/health>

종료할 때는 실행 중인 터미널에서 `Ctrl+C`를 누른 뒤 다음 명령을 실행한다.

```bash
docker compose down
```

## Docker 없이 실행

터미널 1에서 백엔드를 실행한다.

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

터미널 2에서 프론트엔드를 실행한다.

```bash
cd frontend
npm install
npm run dev
```

## 화면에서 전체 흐름 테스트

초기 화면에는 검증을 통과하는 예시 거래 3건과 증빙 2건이 들어 있다.

1. 사용자 `aegis`, 역할 `회계담당자`로 로그인한다.
2. `제출 패키지 생성`을 누르고 결과의 `validation.status`가 `passed`인지 확인한다.
3. `제출 ZIP 다운로드`를 눌러 Excel, DOCX 2개, HTML 리포트가 들어 있는지 확인한다.
4. `월간 공개 생성`을 누른 뒤 `공개 페이지 열기`로 회원 공개 화면을 확인한다.
5. Discord 채널 설정에서 Webhook URL을 발급해 입력하고 `Webhook 저장`을 누른다.
6. `메시지 미리보기`에서 상태가 `pending_approval`인지 확인한다.
7. 실제 테스트 채널로 보내도 될 때만 `승인 전송`을 누르고 상태가 `sent`인지 확인한다.

잔액 검증 실패도 확인하려면 `최종 잔액`을 예시 계산잔액인 `1,080,400`과 다르게
바꾼 뒤 제출 패키지를 다시 생성한다. 이 경우 검증 결과에
`CLOSING_BALANCE_MISMATCH`가 포함되어야 한다.

## 자동 테스트

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

```bash
cd frontend
npm run build
```

## GitHub 업로드

이 디렉터리에는 아직 Git 저장소가 초기화되어 있지 않다. 새 GitHub 저장소를 만든 뒤
아래 명령에서 `<OWNER>`와 `<REPOSITORY>`를 실제 값으로 바꾼다.

```bash
git init
git add .
git status
git commit -m "feat: implement ATLAS v1"
git branch -M main
git remote add origin https://github.com/<OWNER>/<REPOSITORY>.git
git push -u origin main
```

`git status`에서 `backend/storage`, `.env`, `node_modules`, 실제 은행 거래내역
`sample/*.xlsx`가 포함되지 않았는지 확인한다. 공개 저장소라면 매뉴얼과 공식 양식의
재배포 권한도 먼저 확인한다.

## 배포 환경 변수

- `PUBLIC_FRONTEND_BASE_URL`: 월간 공개 페이지의 외부 주소
- `CORS_ORIGINS`: 쉼표로 구분한 허용 프론트엔드 주소
- `VITE_API_BASE_URL`: 프론트엔드 빌드 시 사용할 백엔드 외부 주소

예를 들어 프론트엔드가 `https://atlas.example.com`, API가
`https://api.atlas.example.com`이면 백엔드에는 앞의 두 값을 설정하고 프론트엔드
Docker 빌드에는 다음 인자를 사용한다.

```bash
docker build \
  --build-arg VITE_API_BASE_URL=https://api.atlas.example.com \
  -t atlas-frontend ./frontend
```

## 디렉터리

- `backend/`: FastAPI API, 검증 및 문서 생성
- `frontend/`: React 운영 화면과 월간 공개 화면
- `sample/`: 공식 양식 샘플
- `manual/`: 공식 회계 매뉴얼
