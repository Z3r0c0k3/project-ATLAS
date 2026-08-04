import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Archive,
  BookOpenCheck,
  CheckCircle2,
  Download,
  ExternalLink,
  FileArchive,
  FileSpreadsheet,
  History,
  Landmark,
  Link2,
  LockKeyhole,
  RefreshCw,
  ReceiptText,
  Send,
  ShieldCheck,
  Unlink,
  Upload,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

type TransactionInput = {
  number: number;
  date: string;
  description: string;
  income: number;
  expense: number;
  balance: number;
  category?: string;
  note?: string;
  evidence_ids?: string[];
};

type EvidenceInput = {
  id: string;
  transaction_number?: number;
  filename: string;
  kind: "receipt" | "explanation" | "account_capture" | "other";
  accessible?: boolean;
  amount?: number;
  evidence_date?: string;
};

const initialTransactions: TransactionInput[] = [
  { number: 1, date: "2026-03-01", description: "3월 동아리 회비", income: 340000, expense: 0, balance: 1340000, category: "회비", note: "20,000 * 17명" },
  { number: 2, date: "2026-03-04", description: "동아리 홍보용 X배너", income: 0, expense: 22000, balance: 1318000, category: "홍보", evidence_ids: ["ev-banner"] },
  { number: 3, date: "2026-03-12", description: "동아리 행사 굿즈", income: 0, expense: 237600, balance: 1080400, category: "행사", evidence_ids: ["ev-goods"] },
];

const initialEvidence: EvidenceInput[] = [
  { id: "ev-banner", transaction_number: 2, filename: "banner_receipt.png", kind: "receipt", accessible: true, amount: 22000, evidence_date: "2026-03-04" },
  { id: "ev-goods", transaction_number: 3, filename: "goods_receipt.pdf", kind: "receipt", accessible: true, amount: 237600, evidence_date: "2026-03-12" },
];

type Tab = "ledger" | "package" | "public" | "discord" | "history";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    const raw = await response.text();
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("text/html") || raw.trimStart().startsWith("<!DOCTYPE html")) {
      throw new Error(`서버 연결에 실패했습니다 (${response.status}). ATLAS 컨테이너와 Cloudflare Tunnel 상태를 확인해주세요.`);
    }
    let parsed: any = null;
    try { parsed = JSON.parse(raw); } catch { /* Plain-text API response. */ }
    throw new Error(parsed?.detail || parsed?.message || raw || response.statusText);
  }
  return response.json() as Promise<T>;
}

function parseArray<T>(value: string): { data: T[]; error: string } {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? { data: parsed, error: "" } : { data: [], error: "배열 형식이어야 합니다." };
  } catch {
    return { data: [], error: "JSON 문법을 확인해주세요." };
  }
}

function money(value: number): string {
  return `${Number(value || 0).toLocaleString("ko-KR")}원`;
}

function PublicReport() {
  const shareId = window.location.pathname.split("/").pop() ?? "";
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const robots = document.createElement("meta");
    robots.name = "robots";
    robots.content = "noindex,nofollow,noarchive";
    document.head.appendChild(robots);
    api<any>(`/public/monthly/${shareId}`).then(setReport).catch((err) => setError(err.message));
    return () => robots.remove();
  }, [shareId]);

  if (error) return <main className="public-shell"><div className="empty-state"><LockKeyhole size={28} /><h1>공개 자료를 열 수 없습니다</h1><p>{error}</p></div></main>;
  if (!report) return <main className="public-shell"><div className="empty-state"><RefreshCw className="spin" size={28} /><p>회계 자료를 확인하고 있습니다.</p></div></main>;

  return (
    <main className="public-shell">
      <header className="public-heading">
        <div><p>{report.club_name}</p><h1>{report.month} 회계 투명성 자료</h1></div>
        <span className="verified"><ShieldCheck size={16} /> ATLAS 공개본</span>
      </header>
      <section className="metric-grid">
        <Metric label="수입" value={money(report.summary.total_income)} />
        <Metric label="지출" value={money(report.summary.total_expense)} />
        <Metric label="잔액" value={money(report.summary.closing_balance)} />
        <Metric label="거래 수" value={`${report.summary.transaction_count}건`} />
      </section>
      <section className="table-wrap"><h2>거래 내역</h2><TransactionTable rows={report.transactions} /></section>
      <footer className="public-footer">계좌번호, 증빙 원본, 거래 상대방 및 내부 검토 정보는 공개되지 않습니다.</footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function TransactionTable({ rows }: { rows: TransactionInput[] }) {
  return (
    <table>
      <thead><tr><th>번호</th><th>날짜</th><th>분류</th><th>내용</th><th>수입</th><th>지출</th><th>잔액</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.number}><td>{row.number}</td><td>{row.date}</td><td>{row.category || "미분류"}</td><td>{row.description}</td><td>{row.income ? money(row.income) : "-"}</td><td>{row.expense ? money(row.expense) : "-"}</td><td>{money(row.balance)}</td></tr>)}</tbody>
    </table>
  );
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  return <span className={`badge badge-${normalized}`}>{value}</span>;
}

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("ledger");
  const [username, setUsername] = useState(() => window.sessionStorage.getItem("atlas_username") || "aegis-admin");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(() => window.sessionStorage.getItem("atlas_role") || "admin");
  const [authToken, setAuthToken] = useState(() => window.sessionStorage.getItem("atlas_token") || "");
  const [clubName, setClubName] = useState("Aegis");
  const [semester, setSemester] = useState("2026년 1학기");
  const [month, setMonth] = useState("2026년 3월");
  const [periodStart, setPeriodStart] = useState("2026-03-01");
  const [periodEnd, setPeriodEnd] = useState("2026-06-30");
  const [openingBalance, setOpeningBalance] = useState(1000000);
  const [expectedClosingBalance, setExpectedClosingBalance] = useState(1080400);
  const [treasurerName, setTreasurerName] = useState("회계담당자");
  const [presidentName, setPresidentName] = useState("회장");
  const [reviewerName, setReviewerName] = useState("검토자");
  const [transactionsText, setTransactionsText] = useState(JSON.stringify(initialTransactions, null, 2));
  const [evidenceText, setEvidenceText] = useState(JSON.stringify(initialEvidence, null, 2));
  const [ledgerUpload, setLedgerUpload] = useState<any>(null);
  const [bankUpload, setBankUpload] = useState<any>(null);
  const [evidenceUploads, setEvidenceUploads] = useState<any[]>([]);
  const [evidenceKind, setEvidenceKind] = useState<EvidenceInput["kind"]>("receipt");
  const [evidenceTransactionNumber, setEvidenceTransactionNumber] = useState("");
  const [googleConnection, setGoogleConnection] = useState<any>(null);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [packageData, setPackageData] = useState<any>(null);
  const [job, setJob] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [webhookName, setWebhookName] = useState("Aegis 회계 공지");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhook, setWebhook] = useState<any>(null);
  const [message, setMessage] = useState<any>(null);
  const [auditData, setAuditData] = useState<any>(null);
  const [output, setOutput] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const transactionParse = useMemo(() => parseArray<TransactionInput>(transactionsText), [transactionsText]);
  const evidenceParse = useMemo(() => parseArray<EvidenceInput>(evidenceText), [evidenceText]);
  const transactions = transactionParse.data;
  const evidence = evidenceParse.data;
  const totalIncome = transactions.reduce((sum, row) => sum + Number(row.income || 0), 0);
  const totalExpense = transactions.reduce((sum, row) => sum + Number(row.expense || 0), 0);
  const computedClosing = openingBalance + totalIncome - totalExpense;
  const jsonValid = !transactionParse.error && !evidenceParse.error;

  useEffect(() => {
    if (!authToken) return;
    const params = new URLSearchParams(window.location.search);
    const authorizationCode = params.get("code");
    const oauthState = params.get("state");
    if (!authorizationCode || !oauthState) {
      api<any>("/auth/google/status", { headers: { "X-ATLAS-Token": authToken } }).then(setGoogleConnection).catch(() => undefined);
      return;
    }
    const redirectUri = `${window.location.origin}${window.location.pathname}`;
    setBusy("Google 계정 연결");
    api<any>("/auth/google/connect", {
      method: "POST",
      headers: { "X-ATLAS-Token": authToken },
      body: JSON.stringify({ authorization_code: authorizationCode, state: oauthState, redirect_uri: redirectUri }),
    }).then((result) => {
      setGoogleConnection(result);
      setOutput(result);
      window.history.replaceState({}, "", window.location.pathname);
    }).catch((err) => setError(err instanceof Error ? err.message : "Google 계정 연결에 실패했습니다.")).finally(() => setBusy(""));
  }, [authToken]);

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    return api<T>(path, { ...init, headers: { ...(authToken ? { "X-ATLAS-Token": authToken } : {}), ...(init?.headers ?? {}) } });
  }

  async function run<T>(label: string, action: () => Promise<T>): Promise<T | undefined> {
    setBusy(label); setError("");
    try { const result = await action(); setOutput(result); return result; }
    catch (err) { setError(err instanceof Error ? err.message : "요청 처리 중 오류가 발생했습니다."); }
    finally { setBusy(""); }
  }

  async function waitForJob(jobId: string): Promise<any> {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const current = await request<any>(`/jobs/${jobId}`);
      setJob(current);
      if (current.status === "completed") return current;
      if (current.status === "failed") throw new Error(current.error || "문서 생성 작업이 실패했습니다.");
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    throw new Error("문서 생성 시간이 초과되었습니다.");
  }

  async function uploadForm(path: string, form: FormData): Promise<any> {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "X-ATLAS-Token": authToken },
      body: form,
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }

  async function uploadWorkbook(file: File, kind: "ledger" | "bank") {
    const result = await run(kind === "ledger" ? "Aegis 장부 분석" : "토스 거래내역 분석", async () => {
      const form = new FormData();
      form.append("file", file);
      return uploadForm("/imports/upload", form);
    });
    if (result) {
      if (kind === "ledger") setLedgerUpload(result);
      else setBankUpload(result);
    }
  }

  async function beginGoogleConnect() {
    const redirectUri = `${window.location.origin}${window.location.pathname}`;
    const result: any = await run("Google 연결 준비", () => request(`/auth/google/authorize-url?redirect_uri=${encodeURIComponent(redirectUri)}`));
    if (result?.authorization_url) window.location.assign(result.authorization_url);
  }

  async function disconnectGoogle() {
    const result = await run("Google 연결 해제", () => request("/auth/google/disconnect", { method: "POST" }));
    if (result) setGoogleConnection(result);
  }

  async function uploadEvidenceFiles(files: FileList) {
    const result = await run("증빙자료 업로드", async () => {
      const uploaded: any[] = [];
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        form.append("kind", evidenceKind);
        if (evidenceTransactionNumber) form.append("transaction_number", evidenceTransactionNumber);
        uploaded.push(await uploadForm("/evidence/upload", form));
      }
      return uploaded;
    });
    if (result) {
      setEvidenceUploads((current) => [...current, ...result]);
      setEvidenceText((current) => {
        const parsed = parseArray<EvidenceInput>(current).data;
        return JSON.stringify([...parsed.filter((item) => !result.some((added: any) => added.id === item.id)), ...result], null, 2);
      });
    }
  }

  async function importWorkbooks() {
    if (!ledgerUpload) return;
    const result: any = await run("실제 장부 스냅샷 생성", () => request("/imports/workbook-snapshot", {
      method: "POST",
      body: JSON.stringify({
        ledger_upload_id: ledgerUpload.id,
        bank_upload_id: bankUpload?.id || null,
        evidence_ids: evidenceUploads.map((item) => item.id),
        period: semester,
        period_start: null,
        period_end: null,
        opening_balance: 0,
      }),
    }));
    if (!result) return;
    setSnapshot(result);
    setTransactionsText(JSON.stringify(result.transactions, null, 2));
    setEvidenceText(JSON.stringify(result.evidence, null, 2));
    setOpeningBalance(Number(result.ledger?.opening_balance || 0));
    setExpectedClosingBalance(Number(result.ledger?.closing_balance || 0));
    if (result.ledger?.period_start) setPeriodStart(result.ledger.period_start);
    if (result.ledger?.period_end) setPeriodEnd(result.ledger.period_end);
  }

  async function attachEvidenceToSnapshot() {
    if (!snapshot?.id || !evidenceUploads.length) return;
    const result: any = await run("증빙 반영 스냅샷 생성", () => request(`/ledger-snapshots/${snapshot.id}/evidence`, {
      method: "POST",
      body: JSON.stringify({ evidence_ids: evidenceUploads.map((item) => item.id) }),
    }));
    if (!result) return;
    setSnapshot(result);
    setTransactionsText(JSON.stringify(result.transactions, null, 2));
    setEvidenceText(JSON.stringify(result.evidence, null, 2));
  }

  const snapshotPayload = { organization_id: "aegis", account_id: "primary", period: semester, period_start: periodStart, period_end: periodEnd, transactions, evidence };

  async function downloadPackage() {
    if (!packageData?.id || !authToken) return;
    setBusy("제출 ZIP 다운로드"); setError("");
    try {
      const response = await fetch(`${API_BASE}/packages/${packageData.id}/download`, { headers: { "X-ATLAS-Token": authToken } });
      if (!response.ok) throw new Error(await response.text());
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = blobUrl; anchor.download = `${clubName}_${semester}_동연제출.zip`; anchor.click(); URL.revokeObjectURL(blobUrl);
    } catch (err) { setError(err instanceof Error ? err.message : "ZIP 다운로드 중 오류가 발생했습니다."); }
    finally { setBusy(""); }
  }

  const tabs: Array<{ id: Tab; label: string; icon: React.ReactNode }> = [
    { id: "ledger", label: "장부·증빙", icon: <BookOpenCheck size={17} /> },
    { id: "package", label: "동연 패키지", icon: <FileArchive size={17} /> },
    { id: "public", label: "월간 공개", icon: <Link2 size={17} /> },
    { id: "discord", label: "Discord", icon: <Send size={17} /> },
    { id: "history", label: "감사 로그", icon: <History size={17} /> },
  ];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-mark">A</div><div><p>ATLAS</p><h1>Aegis 회계 자동화</h1></div></div>
        <div className="session-state"><span className={`dot ${authToken ? "online" : ""}`} />{authToken ? `${username} · ${role}` : "로그인 필요"}</div>
      </header>

      {!authToken ? (
        <section className="login-surface">
          <div><p className="eyebrow">ACCOUNTING OPERATIONS</p><h2>회계 작업을 시작합니다</h2><p>배포 환경에서는 서버의 로그인 비밀번호가 적용됩니다.</p></div>
          <div className="login-form">
            <label>사용자<input value={username} onChange={(event) => setUsername(event.target.value)} /></label>
            <label>역할<select value={role} onChange={(event) => setRole(event.target.value)}><option value="admin">관리자</option><option value="accountant">회계담당자</option><option value="president">회장</option><option value="reviewer">검토자</option></select></label>
            <label>비밀번호<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="로컬 데모는 비워둠" /></label>
            <button onClick={async () => { const session: any = await run("로그인", () => api("/auth/login", { method: "POST", body: JSON.stringify({ username, role, password: password || null }) })); if (session?.token) { window.sessionStorage.setItem("atlas_token", session.token); window.sessionStorage.setItem("atlas_username", session.username); window.sessionStorage.setItem("atlas_role", session.role); setAuthToken(session.token); setUsername(session.username); setRole(session.role); } }}><LockKeyhole size={17} /> 로그인</button>
          </div>
          {error && <pre className="error-box">{error}</pre>}
        </section>
      ) : (
        <>
          <nav className="tabs" aria-label="ATLAS 메뉴">{tabs.map((tab) => <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>{tab.icon}{tab.label}</button>)}</nav>

          <section className="metric-grid">
            <Metric label="수입총액" value={money(totalIncome)} /><Metric label="지출총액" value={money(totalExpense)} /><Metric label="계산잔액" value={money(computedClosing)} /><Metric label="기대잔액" value={money(expectedClosingBalance)} />
          </section>

          {activeTab === "ledger" && <>
            <section className="section-head"><div><p className="eyebrow">LEDGER SOURCE</p><h2>장부 스냅샷</h2><p>제출과 공개 자료는 생성 시점의 해시가 고정된 스냅샷을 사용합니다.</p></div>{snapshot && <StatusBadge value="SNAPSHOT SAVED" />}</section>
            <section className="workspace-grid">
              <div className="panel"><h3>회계 기본 정보</h3><div className="form-grid"><label>동아리명<input value={clubName} onChange={(e) => setClubName(e.target.value)} /></label><label>회계 기간<input value={semester} onChange={(e) => setSemester(e.target.value)} /></label><label>시작일<input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} /></label><label>종료일<input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} /></label><label>이전 잔액<input type="number" value={openingBalance} onChange={(e) => setOpeningBalance(Number(e.target.value))} /></label><label>최종 잔액<input type="number" value={expectedClosingBalance} onChange={(e) => setExpectedClosingBalance(Number(e.target.value))} /></label></div></div>
              <div className="panel"><div className="panel-heading"><h3>Google 자료 연결</h3>{googleConnection && <StatusBadge value={googleConnection.connected ? "CONNECTED" : "DISCONNECTED"} />}</div><p className="muted">{googleConnection?.connected ? `${googleConnection.account_email} · 읽기 전용 연결` : "운영 계정의 Sheets 장부와 Drive 증빙을 읽기 전용으로 연결합니다."}</p><div className="button-row">{googleConnection?.connected ? <button className="secondary danger" onClick={disconnectGoogle}>연결 해제</button> : <button onClick={beginGoogleConnect}>Google 계정 연결</button>}<button className="secondary" disabled={!googleConnection?.connected} onClick={() => run("Sheets 조회", () => request("/google/sheets"))}>Google Sheets</button><button className="secondary" disabled={!googleConnection?.connected} onClick={() => run("Drive 조회", () => request("/google/drive/files"))}>Google Drive</button></div></div>
            </section>
            <section className="import-surface">
              <div className="import-heading"><div><p className="eyebrow">PRODUCTION IMPORT</p><h3>실제 파일 가져오기</h3></div>{snapshot?.reconciliation && <StatusBadge value={snapshot.reconciliation.status} />}</div>
              <div className="upload-grid">
                <label className={`upload-slot ${ledgerUpload ? "ready" : ""}`}><FileSpreadsheet size={22} /><span>Aegis 회계장부</span><small>{ledgerUpload?.filename || ".xlsx"}</small><input type="file" accept=".xlsx,.xlsm" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadWorkbook(file, "ledger"); }} /></label>
                <label className={`upload-slot ${bankUpload ? "ready" : ""}`}><Landmark size={22} /><span>토스뱅크 거래내역</span><small>{bankUpload?.filename || ".xlsx"}</small><input type="file" accept=".xlsx,.xlsm" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadWorkbook(file, "bank"); }} /></label>
                <div className="upload-slot evidence-slot"><ReceiptText size={22} /><span>영수증·소명·캡처</span><div className="evidence-options"><select aria-label="증빙 종류" value={evidenceKind} onChange={(event) => setEvidenceKind(event.target.value as EvidenceInput["kind"])}><option value="receipt">영수증</option><option value="explanation">소명자료</option><option value="account_capture">계좌 캡처</option><option value="other">기타</option></select><input aria-label="장부 번호" type="number" min="1" placeholder="장부 번호" value={evidenceTransactionNumber} onChange={(event) => setEvidenceTransactionNumber(event.target.value)} /></div><label className="mini-file-button"><Upload size={15} /> 파일 선택<input type="file" multiple accept="image/*,.pdf,.docx" onChange={(event) => { if (event.target.files?.length) uploadEvidenceFiles(event.target.files); }} /></label><small>{evidenceUploads.length ? `${evidenceUploads.length}개 업로드됨` : "여러 파일 선택 가능"}</small></div>
              </div>
              {snapshot?.reconciliation && <div className="reconciliation-line"><ShieldCheck size={18} /><strong>잔액 차이 {money(snapshot.reconciliation.balance_delta)}</strong><span>장부 {snapshot.reconciliation.ledger_transaction_count}건 · 은행 {snapshot.reconciliation.bank_transaction_count}건 · 자동 매칭 {snapshot.reconciliation.matched_ledger_count}건</span></div>}
              <div className="action-bar"><button disabled={!ledgerUpload || !!busy} onClick={importWorkbooks}><Archive size={17} /> 실제 장부 가져오기</button><button className="secondary" disabled={!snapshot?.id || !evidenceUploads.length || !!busy} onClick={attachEvidenceToSnapshot}><ReceiptText size={17} /> 증빙 반영 새 버전</button>{snapshot && <code>{snapshot.id} · {snapshot.data_hash.slice(0, 16)}…</code>}</div>
            </section>
            <details className="advanced-editor"><summary>고급 데이터 편집</summary><section className="editor-grid"><label className="editor-block">거래 데이터 JSON<textarea value={transactionsText} onChange={(e) => setTransactionsText(e.target.value)} />{transactionParse.error && <span className="field-error">{transactionParse.error}</span>}</label><label className="editor-block">증빙 데이터 JSON<textarea value={evidenceText} onChange={(e) => setEvidenceText(e.target.value)} />{evidenceParse.error && <span className="field-error">{evidenceParse.error}</span>}</label></section><div className="action-bar"><button className="secondary" disabled={!jsonValid || !!busy} onClick={async () => { const result = await run("수동 스냅샷 생성", () => request("/ledger-snapshots", { method: "POST", body: JSON.stringify(snapshotPayload) })); if (result) setSnapshot(result); }}><Archive size={17} /> 수동 스냅샷 생성</button></div></details>
          </>}

          {activeTab === "package" && <>
            <section className="section-head"><div><p className="eyebrow">SUBMISSION PACKAGE</p><h2>동아리연합회 제출본</h2><p>생성, 검토 요청, 승인 이력을 버전 단위로 보존합니다.</p></div>{packageData && <StatusBadge value={packageData.status} />}</section>
            <section className="workspace-grid"><div className="panel"><h3>서명 정보</h3><div className="form-grid"><label>회계담당자<input value={treasurerName} onChange={(e) => setTreasurerName(e.target.value)} /></label><label>회장<input value={presidentName} onChange={(e) => setPresidentName(e.target.value)} /></label><label>검토자<input value={reviewerName} onChange={(e) => setReviewerName(e.target.value)} /></label></div></div><div className="panel"><h3>현재 작업</h3>{job ? <div className="job-state"><RefreshCw className={job.status === "running" ? "spin" : ""} size={20} /><div><strong>{job.status}</strong><span>{job.id}</span></div></div> : <p className="muted">생성 요청 전입니다.</p>}{packageData?.validation && <div className="validation-line"><StatusBadge value={packageData.validation.status} /><span>오류 {packageData.validation.error_count} · 경고 {packageData.validation.warning_count}</span></div>}{packageData?.document_coverage && <div className="coverage-grid"><span>장부 <strong>{packageData.document_coverage.ledger_transaction_rows}건 / {packageData.document_coverage.ledger_row_capacity}칸</strong></span><span>증빙 삽입 <strong>{packageData.document_coverage.evidence_document.embedded_files}개</strong></span><span>계좌 캡처 <strong>{packageData.document_coverage.account_document.embedded_capture_pages}쪽</strong></span><span>은행 거래 <strong>{packageData.document_coverage.account_document.bank_transaction_rows}건</strong></span></div>}</div></section>
            <div className="action-bar"><button disabled={!jsonValid || !!busy} onClick={async () => { await run("패키지 생성", async () => { const created: any = await request("/packages/submission", { method: "POST", body: JSON.stringify({ ...snapshotPayload, club_name: clubName, semester, snapshot_id: snapshot?.id, treasurer_name: treasurerName, president_name: presidentName, reviewer_name: reviewerName, opening_balance: openingBalance, expected_closing_balance: expectedClosingBalance, row_capacity: 40 }) }); setJob(created); const finished = await waitForJob(created.job_id); const pkg = await request<any>(`/packages/${created.package_id}`); setPackageData(pkg); return finished; }); }}><FileArchive size={17} /> 패키지 생성</button><button className="secondary" disabled={packageData?.status !== "draft" || !!busy} onClick={async () => { const result = await run("검토 요청", () => request(`/packages/${packageData.id}/submit-review`, { method: "POST" })); if (result) setPackageData(result); }}>검토 요청</button><button className="approve" disabled={packageData?.status !== "pending_review" || !!busy} onClick={async () => { const result = await run("패키지 승인", () => request(`/packages/${packageData.id}/approve`, { method: "POST", body: JSON.stringify({ reason: "검토 완료" }) })); if (result) setPackageData(result); }}><CheckCircle2 size={17} /> 승인</button><button className="secondary" disabled={!packageData?.zip_path} onClick={downloadPackage}><Download size={17} /> ZIP 다운로드</button></div>
            {packageData?.zip_sha256 && <section className="integrity"><ShieldCheck size={20} /><div><strong>ZIP 무결성</strong><code>{packageData.zip_sha256}</code></div></section>}
          </>}

          {activeTab === "public" && <>
            <section className="section-head"><div><p className="eyebrow">MEMBER DISCLOSURE</p><h2>월간 회원 공개</h2><p>긴 난수 토큰을 사용하며 링크를 즉시 폐기하거나 재발급할 수 있습니다.</p></div>{report && <StatusBadge value={report.status || "active"} />}</section>
            <section className="workspace-grid"><div className="panel"><h3>공개 설정</h3><div className="form-grid"><label>공개 월<input value={month} onChange={(e) => setMonth(e.target.value)} /></label><label>만료일<input type="datetime-local" id="report-expiry" /></label></div></div><div className="panel"><h3>공개 범위</h3><ul className="privacy-list"><li>거래 상대방 및 계좌번호 제외</li><li>증빙 ID·원본 경로 제외</li><li>내부 비고 기본 비공개</li><li>검색엔진 색인 차단</li></ul></div></section>
            <div className="action-bar"><button disabled={!jsonValid || !!busy} onClick={async () => { const expiry = (document.getElementById("report-expiry") as HTMLInputElement)?.value; const result: any = await run("월간 공개 생성", () => request("/monthly-reports", { method: "POST", body: JSON.stringify({ club_name: clubName, month, snapshot_id: snapshot?.id, opening_balance: openingBalance, transactions, evidence, visible_notes: false, expires_at: expiry ? new Date(expiry).toISOString() : null, allow_download: false }) })); if (result) setReport({ ...result, status: "active" }); }}><Link2 size={17} /> 공개 페이지 생성</button><button className="secondary" disabled={!report?.public_url} onClick={() => window.open(report.public_url, "_blank", "noopener,noreferrer")}><ExternalLink size={17} /> 페이지 열기</button><button className="secondary danger" disabled={!report?.report_id || report?.status === "revoked"} onClick={async () => { const result: any = await run("링크 폐기", () => request(`/monthly-reports/${report.report_id}/revoke`, { method: "POST" })); if (result) setReport({ ...report, status: "revoked" }); }}><Unlink size={17} /> 링크 폐기</button><button className="secondary" disabled={!report?.report_id} onClick={async () => { const result: any = await run("링크 재발급", () => request(`/monthly-reports/${report.report_id}/regenerate-link`, { method: "POST" })); if (result) setReport({ ...report, ...result }); }}><RefreshCw size={17} /> 재발급</button></div>
            {report?.public_url && <div className="link-output"><Link2 size={17} /><a href={report.public_url} target="_blank" rel="noreferrer">{report.public_url}</a></div>}
          </>}

          {activeTab === "discord" && <>
            <section className="section-head"><div><p className="eyebrow">APPROVED DELIVERY</p><h2>Discord 공지</h2><p>Webhook은 암호화 저장되며 미리보기와 승인을 분리합니다.</p></div>{message && <StatusBadge value={message.status} />}</section>
            <section className="workspace-grid"><div className="panel"><h3>Webhook</h3><div className="form-grid single"><label>이름<input value={webhookName} onChange={(e) => setWebhookName(e.target.value)} /></label><label>Webhook URL<input type="password" value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} placeholder="화면과 로그에 원문을 남기지 않습니다" /></label></div>{webhook && <p className="secret-confirmed"><ShieldCheck size={16} /> {webhook.masked_url}</p>}</div><div className="panel"><h3>승인 상태</h3><div className="approval-flow"><span className={message ? "done" : ""}>미리보기</span><i /><span className={message?.status === "approved" || message?.status === "sent" ? "done" : ""}>승인</span><i /><span className={message?.status === "sent" ? "done" : ""}>전송</span></div>{message?.preview && <pre className="message-preview">{message.preview}</pre>}</div></section>
            <div className="action-bar"><button disabled={!webhookUrl || !!busy} onClick={async () => { const result = await run("Webhook 저장", () => request("/discord/webhooks", { method: "POST", body: JSON.stringify({ name: webhookName, webhook_url: webhookUrl }) })); if (result) { setWebhook(result); setWebhookUrl(""); } }}><ShieldCheck size={17} /> Webhook 저장</button><button className="secondary" disabled={!report?.share_id || !webhook?.id || !!busy} onClick={async () => { const result = await run("메시지 미리보기", () => request("/discord/messages/preview", { method: "POST", body: JSON.stringify({ share_id: report.share_id, webhook_id: webhook.id }) })); if (result) setMessage(result); }}>미리보기</button><button className="approve" disabled={message?.status !== "pending_approval" || !!busy} onClick={async () => { const result = await run("메시지 승인", () => request(`/discord/messages/${message.message_id}/approve`, { method: "POST" })); if (result) setMessage(result); }}><CheckCircle2 size={17} /> 승인</button><button disabled={!(["approved", "failed"].includes(message?.status)) || !!busy} onClick={async () => { const result = await run("Discord 전송", () => request(`/discord/messages/${message.message_id}/send`, { method: "POST" })); if (result) setMessage(result); }}><Send size={17} /> 전송</button></div>
          </>}

          {activeTab === "history" && <>
            <section className="section-head"><div><p className="eyebrow">AUDIT TRAIL</p><h2>감사 로그</h2><p>앞선 이벤트 해시를 포함하는 체인으로 변경 여부를 검증합니다.</p></div>{auditData?.chain && <StatusBadge value={auditData.chain.valid ? "CHAIN VALID" : "CHAIN INVALID"} />}</section>
            <div className="action-bar"><button onClick={async () => { const result = await run("감사 로그 조회", () => request("/audit-logs")); if (result) setAuditData(result); }}><History size={17} /> 로그 새로고침</button></div>
            <section className="audit-list">{auditData?.events?.map((event: any) => <article key={event.id}><div><strong>{event.action}</strong><span>{event.actor} · {event.actor_role}</span></div><div><code>{event.target_type}:{event.target_id || "-"}</code><time>{new Date(event.created_at).toLocaleString("ko-KR")}</time></div></article>) || <div className="empty-inline">감사 로그를 조회해주세요.</div>}</section>
          </>}

          {(error || output) && <aside className="result-drawer"><div><h3>작업 결과</h3>{busy && <span className="busy"><RefreshCw className="spin" size={14} /> {busy}</span>}</div>{error && <pre className="error-box">{error}</pre>}{output && <pre className="result-box">{JSON.stringify(output, null, 2)}</pre>}</aside>}
        </>
      )}
    </main>
  );
}

const root = createRoot(document.getElementById("root")!);
root.render(window.location.pathname.startsWith("/public/monthly/") ? <PublicReport /> : <App />);
