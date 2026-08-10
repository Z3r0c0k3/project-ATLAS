import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BookOpenCheck,
  Check,
  CheckCircle2,
  Download,
  ExternalLink,
  FileArchive,
  FileSpreadsheet,
  History,
  Link2,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Trash2,
  Upload,
  UserPlus,
  X,
} from "lucide-react";
import "./styles.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "");
const CURRENT_YEAR = new Date().getFullYear();
const PERIOD_START = `${CURRENT_YEAR}-01-01`;
const PERIOD_END = `${CURRENT_YEAR}-12-31`;
const JOB_MAX_WAIT_MS = 30 * 60 * 1000;

type AccountId = "primary" | "dues_intake";
type RouteId = "package" | "ledger" | "snapshots" | "public-report" | "settings";
type ToastState = { kind: "loading" | "success" | "error"; title: string; detail?: string };
type Runner = <T>(label: string, action: () => Promise<T>) => Promise<T | undefined>;
type Role = "admin" | "accountant" | "president" | "reviewer";
type Session = { token: string; username: string; email: string; role: Role; expires_at: string };

type Transaction = {
  transaction_id?: string;
  account_id?: string;
  number: number;
  date: string;
  description: string;
  income: number;
  expense: number;
  balance: number;
  category?: string;
  processing_method?: string;
  details?: string;
  evidence_ids?: string[];
};

type EvidenceFile = {
  id: string;
  filename: string;
  mime_type?: string;
  preview_available?: boolean;
};

type EvidencePreview = EvidenceFile & { url: string };
type ReconciliationResult = {
  status: "PASS" | "ERROR";
  cutoff_date: string;
  ledger_transaction_count: number;
  bank_transaction_count: number;
  matched_ledger_count: number;
  unmatched_ledger_count: number;
  unmatched_bank_count: number;
  balance_delta: number | null;
  bank_continuity_failure_count: number;
  unmatched_ledger?: Array<{
    transaction_id?: string;
    number: number;
    date: string;
    description: string;
    amount: number;
    reason?: "AMOUNT_MISMATCH" | "DATE_MISMATCH" | "BANK_TRANSACTION_NOT_FOUND";
    candidate?: { occurred_at?: string; date?: string; description: string; amount: number } | null;
  }>;
  unmatched_bank?: Array<{
    bank_transaction_id: string;
    occurred_at?: string;
    date?: string;
    description: string;
    amount: number;
  }>;
};

const ACCOUNT_LABELS: Record<AccountId, string> = {
  primary: "동아리운영계좌(토스뱅크)",
  dues_intake: "회비입금계좌(IBK기업은행)",
};
const ROLE_LABELS: Record<Role, string> = {
  admin: "관리자",
  president: "회장",
  accountant: "총무",
  reviewer: "검토자",
};

function routeFromPath(): RouteId {
  const segment = window.location.pathname.split("/").filter(Boolean)[0];
  if (segment === "monthly") return "public-report";
  return segment === "package" || segment === "snapshots" || segment === "public-report" || segment === "settings" ? segment : "ledger";
}

function previousMonthValue(): string {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function previousMonthLabel(): string {
  const [year, month] = previousMonthValue().split("-");
  return `${year}년 ${Number(month)}월`;
}

function money(value: number): string {
  return `${Number(value || 0).toLocaleString("ko-KR")}원`;
}

async function parseApiError(response: Response): Promise<Error> {
  const raw = await response.text();
  if ((response.headers.get("content-type") || "").includes("text/html") || raw.trimStart().startsWith("<!DOCTYPE html")) {
    return new Error(`서버 연결에 실패했습니다 (${response.status}).`);
  }
  try {
    const parsed = JSON.parse(raw);
    return new Error(parsed.detail || parsed.message || response.statusText);
  } catch {
    return new Error(raw || response.statusText);
  }
}

async function api<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (token) headers.set("X-ATLAS-Token", token);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) throw await parseApiError(response);
  return response.json() as Promise<T>;
}

async function apiBlob(path: string, token: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { "X-ATLAS-Token": token } });
  if (!response.ok) throw await parseApiError(response);
  return response.blob();
}

function storedSession(): Session | null {
  try {
    const session = JSON.parse(sessionStorage.getItem("atlas_session") || "null") as Session | null;
    const expiresAt = Date.parse(session?.expires_at || "");
    if (!session?.token || !session.email || !session.role || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) return null;
    return session;
  } catch {
    return null;
  }
}

function Toast({ toast, onClose }: { toast: ToastState | null; onClose: () => void }) {
  if (!toast) return null;
  const Icon = toast.kind === "loading" ? LoaderCircle : toast.kind === "success" ? Check : X;
  return (
    <div className={`toast toast-${toast.kind}`} role="status">
      <Icon className={toast.kind === "loading" ? "spin" : ""} size={18} />
      <div><strong>{toast.title}</strong>{toast.detail && <span>{toast.detail}</span>}</div>
      {toast.kind !== "loading" && <button className="toast-close" aria-label="알림 닫기" onClick={onClose}><X size={16} /></button>}
    </div>
  );
}

function StatusBadge({ value }: { value: string }) {
  return <span className={`badge badge-${value.toLowerCase().split(" ").join("-")}`}>{value}</span>;
}

function TransactionTable({ rows, accountFilter = "all", evidenceById = {}, onPreviewEvidence }: { rows: Transaction[]; accountFilter?: AccountId | "all"; evidenceById?: Record<string, EvidenceFile>; onPreviewEvidence?: (items: EvidenceFile[]) => void }) {
  const visible = rows.filter((row) => accountFilter === "all" || (row.account_id || "primary") === accountFilter);
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>No</th><th>날짜</th><th>계좌</th><th>내용</th><th>수입</th><th>지출</th><th>잔액</th><th>처리방식</th><th>상세정보</th><th>증빙</th></tr></thead>
        <tbody>
          {visible.map((row) => {
            const accountId = row.account_id === "dues_intake" ? "dues_intake" : "primary";
            const linkedEvidence = (row.evidence_ids || []).map((id) => evidenceById[id]).filter((item): item is EvidenceFile => Boolean(item?.preview_available));
            return <tr key={`${accountId}:${row.transaction_id || row.number}`}><td>{row.number}</td><td>{row.date}</td><td><span className={`account-tag ${accountId}`}>{accountId === "primary" ? "운영" : "회비"}</span></td><td>{row.description}</td><td>{row.income ? money(row.income) : "-"}</td><td>{row.expense ? money(row.expense) : "-"}</td><td>{money(row.balance)}</td><td>{row.processing_method || "-"}</td><td>{row.details || "-"}</td><td><span className="evidence-cell"><span>{linkedEvidence.length}</span>{linkedEvidence.length > 0 && onPreviewEvidence && <button className="icon-button" title="증빙 미리보기" aria-label={`${row.number}번 거래 증빙 미리보기`} onClick={() => onPreviewEvidence(linkedEvidence)}><Search size={15} /></button>}</span></td></tr>;
          })}
          {!visible.length && <tr><td className="empty-row" colSpan={10}>표시할 거래가 없습니다.</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function useWorkspace(token: string, run: Runner) {
  const [primarySnapshot, setPrimarySnapshot] = useState<any>(null);
  const [duesSnapshot, setDuesSnapshot] = useState<any>(null);
  const [googleConnection, setGoogleConnection] = useState<any>(null);
  const [primarySource, setPrimarySource] = useState("");
  const [duesSource, setDuesSource] = useState("");
  const [monthlyDestination, setMonthlyDestination] = useState("");
  const [range, setRange] = useState("B:I");

  const applySnapshot = useCallback((snapshot: any) => {
    if (!snapshot) return;
    if (snapshot.account_id === "dues_intake") setDuesSnapshot(snapshot);
    else setPrimarySnapshot(snapshot);
  }, []);

  const loadLatest = useCallback(async () => {
    const summaries = await api<any[]>("/ledger-snapshots", token);
    const latestPrimary = summaries.find((item) => item.account_id === "primary");
    const latestDues = summaries.find((item) => item.account_id === "dues_intake");
    const details = await Promise.all([
      latestPrimary ? api<any>(`/ledger-snapshots/${latestPrimary.id}`, token) : null,
      latestDues ? api<any>(`/ledger-snapshots/${latestDues.id}`, token) : null,
    ]);
    if (details[0]) setPrimarySnapshot(details[0]);
    if (details[1]) setDuesSnapshot(details[1]);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    loadLatest().catch(() => undefined);
    api<any>("/config/defaults", token).then((defaults) => {
      setPrimarySource(defaults.default_ledger_sheet_url || "");
      setDuesSource(defaults.default_dues_ledger_sheet_url || "");
      setMonthlyDestination(defaults.default_monthly_public_sheet_url || "");
    }).catch(() => undefined);
    api<any>("/auth/google/status", token).then(setGoogleConnection).catch(() => undefined);
  }, [loadLatest, token]);

  useEffect(() => {
    if (!token) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) return;
    if (sessionStorage.getItem("atlas_oauth_flow") !== "connection") return;
    const redirectUri = `${window.location.origin}/`;
    run("Google 계정 연결", () => api<any>("/auth/google/connect", token, {
      method: "POST",
      body: JSON.stringify({ authorization_code: code, state, redirect_uri: redirectUri }),
    })).then((result) => {
      if (result) setGoogleConnection(result);
      const returnPath = sessionStorage.getItem("atlas_google_return_path") || "/ledger";
      sessionStorage.removeItem("atlas_google_return_path");
      sessionStorage.removeItem("atlas_oauth_flow");
      window.location.replace(returnPath);
    });
  }, [run, token]);

  async function connectGoogle() {
    const redirectUri = `${window.location.origin}/`;
    sessionStorage.setItem("atlas_google_return_path", window.location.pathname);
    sessionStorage.setItem("atlas_oauth_flow", "connection");
    const result = await run("Google 연결 준비", () => api<any>(`/auth/google/authorize-url?redirect_uri=${encodeURIComponent(redirectUri)}`, token));
    if (result?.authorization_url) window.location.assign(result.authorization_url);
  }

  async function disconnectGoogle() {
    const result = await run("Google 연결 해제", () => api<any>("/auth/google/disconnect", token, { method: "POST" }));
    if (result) setGoogleConnection(result);
  }

  async function importGoogle(accountId: AccountId, periodStart: string, periodEnd: string) {
    const source = accountId === "primary" ? primarySource : duesSource;
    if (!source.trim()) {
      return run(`${ACCOUNT_LABELS[accountId]} 장부 연결`, async () => {
        throw new Error("Google Sheets URL 또는 ID를 입력해주세요.");
      });
    }
    const result = await run(`${ACCOUNT_LABELS[accountId]} 장부 연결`, () => api<any>("/google/sheets/snapshot", token, {
      method: "POST",
      body: JSON.stringify({
        spreadsheet_url_or_id: source.trim(),
        range: range.trim() || "B:I",
        period: `${CURRENT_YEAR}년`,
        period_start: periodStart,
        period_end: periodEnd,
        opening_balance: 0,
        organization_id: "aegis",
        account_id: accountId,
      }),
    }));
    if (result) applySnapshot(result);
    return result;
  }

  return {
    primarySnapshot, duesSnapshot, applySnapshot, loadLatest,
    googleConnection, connectGoogle, disconnectGoogle, importGoogle,
    primarySource, setPrimarySource, duesSource, setDuesSource,
    monthlyDestination, setMonthlyDestination, range, setRange,
  };
}

function GooglePanel({ workspace, fixedStart = false }: { workspace: ReturnType<typeof useWorkspace>; fixedStart?: boolean }) {
  const connected = Boolean(workspace.googleConnection?.connected);
  return (
    <section className="panel google-panel">
      <div className="panel-heading"><div><p className="eyebrow">GOOGLE SHEETS</p><h3>Google 자료 연결</h3></div><StatusBadge value={connected ? "CONNECTED" : "DISCONNECTED"} /></div>
      <p className="muted">{connected ? workspace.googleConnection.account_email : "Aegis Google 계정을 연결해주세요."}</p>
      <div className="google-fields">
        <label>{ACCOUNT_LABELS.primary}<input value={workspace.primarySource} onChange={(event) => workspace.setPrimarySource(event.target.value)} placeholder="Google Sheets URL 또는 ID" /></label>
        <label>{ACCOUNT_LABELS.dues_intake}<input value={workspace.duesSource} onChange={(event) => workspace.setDuesSource(event.target.value)} placeholder="Google Sheets URL 또는 ID" /></label>
        <label>범위<input value={workspace.range} onChange={(event) => workspace.setRange(event.target.value)} placeholder="B:I" /></label>
      </div>
      <div className="button-row">
        {connected ? <button className="secondary danger" onClick={workspace.disconnectGoogle}><LogOut size={16} /> 연결 해제</button> : <button onClick={workspace.connectGoogle}><Link2 size={16} /> 계정 연결</button>}
        <button className="secondary" disabled={!connected} onClick={() => workspace.importGoogle("primary", fixedStart ? PERIOD_START : PERIOD_START, PERIOD_END)}><FileSpreadsheet size={16} /> 운영 장부 연결</button>
        <button className="secondary" disabled={!connected} onClick={() => workspace.importGoogle("dues_intake", fixedStart ? PERIOD_START : PERIOD_START, PERIOD_END)}><FileSpreadsheet size={16} /> 회비 장부 연결</button>
      </div>
    </section>
  );
}

function LedgerPage({ token, run }: { token: string; run: Runner }) {
  const workspace = useWorkspace(token, run);
  const [periodStart, setPeriodStart] = useState(PERIOD_START);
  const [periodEnd, setPeriodEnd] = useState(PERIOD_END);
  const [accountFilter, setAccountFilter] = useState<AccountId | "all">("all");
  const [uploadAccount, setUploadAccount] = useState<AccountId>("primary");
  const [evidenceAccount, setEvidenceAccount] = useState<AccountId | "auto">("auto");
  const [evidenceNumber, setEvidenceNumber] = useState("");
  const [previewFiles, setPreviewFiles] = useState<EvidencePreview[] | null>(null);
  const rows = useMemo(() => [...(workspace.primarySnapshot?.transactions || []), ...(workspace.duesSnapshot?.transactions || [])], [workspace.primarySnapshot, workspace.duesSnapshot]);
  const evidenceById = useMemo(() => Object.fromEntries(
    [...(workspace.primarySnapshot?.evidence || []), ...(workspace.duesSnapshot?.evidence || [])]
      .filter((item: EvidenceFile) => item.preview_available)
      .map((item: EvidenceFile) => [item.id, item]),
  ), [workspace.primarySnapshot, workspace.duesSnapshot]);

  useEffect(() => () => previewFiles?.forEach((item) => URL.revokeObjectURL(item.url)), [previewFiles]);

  async function importLedger(accountId: AccountId) {
    await workspace.importGoogle(accountId, periodStart, periodEnd);
  }

  async function uploadBank(file: File) {
    const snapshot = uploadAccount === "primary" ? workspace.primarySnapshot : workspace.duesSnapshot;
    if (!snapshot?.id) {
      await run("계좌 거래내역 연결", async () => { throw new Error(`${ACCOUNT_LABELS[uploadAccount]} 장부를 먼저 연결해주세요.`); });
      return;
    }
    const form = new FormData();
    form.append("file", file);
    const upload = await run("계좌 거래내역 업로드", () => api<any>("/imports/upload", token, { method: "POST", body: form }));
    if (!upload) return;
    const revision = await run("계좌 거래내역 연결", () => api<any>(`/ledger-snapshots/${snapshot.id}/bank-transactions`, token, { method: "POST", body: JSON.stringify({ upload_id: upload.id }) }));
    if (revision) workspace.applySnapshot(revision);
  }

  async function uploadEvidence(files: FileList) {
    const uploaded = await run("영수증·소명·캡처 업로드", async () => {
      const results = [];
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        form.append("kind", "auto");
        if (evidenceAccount !== "auto") form.append("account_id", evidenceAccount);
        if (evidenceNumber) form.append("transaction_number", evidenceNumber);
        results.push(await api<any>("/evidence/upload", token, { method: "POST", body: form }));
      }
      return results;
    });
    if (!uploaded?.length) return;
    for (const accountId of ["primary", "dues_intake"] as AccountId[]) {
      const snapshot = accountId === "primary" ? workspace.primarySnapshot : workspace.duesSnapshot;
      const ids = uploaded.filter((item: any) => item.account_id === accountId).map((item: any) => item.id);
      if (!snapshot?.id || !ids.length) continue;
      const revision = await run(`${ACCOUNT_LABELS[accountId]} 증빙 연결`, () => api<any>(`/ledger-snapshots/${snapshot.id}/evidence`, token, { method: "POST", body: JSON.stringify({ evidence_ids: ids }) }));
      if (revision) workspace.applySnapshot(revision);
    }
  }

  async function openEvidencePreview(items: EvidenceFile[]) {
    const loaded = await run("증빙 미리보기", async () => Promise.all(items.map(async (item) => {
      const blob = await apiBlob(`/evidence/${item.id}/file`, token);
      return { ...item, mime_type: blob.type || item.mime_type, url: URL.createObjectURL(blob) };
    })));
    if (loaded) setPreviewFiles(loaded);
  }

  return <>
    <PageHeading eyebrow="LEDGER & EVIDENCE" title="장부/증빙" description="원본 장부를 연결하고 계좌 거래내역과 증빙을 매칭합니다." />
    <section className="period-strip">
      <label>시작일<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} /></label>
      <label>종료일<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} /></label>
    </section>
    <GooglePanel workspace={{ ...workspace, importGoogle: (accountId) => workspace.importGoogle(accountId, periodStart, periodEnd) }} />
    <section className="panel compact-import">
      <div className="panel-heading"><div><p className="eyebrow">FILES</p><h3>실제 파일 가져오기</h3></div></div>
      <div className="file-controls">
        <div className="file-control">
          <label>계좌<select value={uploadAccount} onChange={(event) => setUploadAccount(event.target.value as AccountId)}><option value="primary">{ACCOUNT_LABELS.primary}</option><option value="dues_intake">{ACCOUNT_LABELS.dues_intake}</option></select></label>
          <label className="file-button"><Upload size={16} /> 계좌 거래내역<input type="file" accept=".xlsx,.xlsm,.pdf" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadBank(file).catch(() => undefined); event.currentTarget.value = ""; }} /></label>
        </div>
        <div className="file-control evidence-control">
          <label>계좌 분류<select value={evidenceAccount} onChange={(event) => setEvidenceAccount(event.target.value as AccountId | "auto")}><option value="auto">파일명 자동 분류</option><option value="primary">{ACCOUNT_LABELS.primary}</option><option value="dues_intake">{ACCOUNT_LABELS.dues_intake}</option></select></label>
          <label>장부 ID<input type="number" min="1" value={evidenceNumber} onChange={(event) => setEvidenceNumber(event.target.value)} placeholder="파일명에 없을 때" /></label>
          <label className="file-button"><ReceiptText size={16} /> 영수증·소명·캡처<input type="file" multiple accept="image/*,.heic,.heif,.pdf,.docx" onChange={(event) => { if (event.target.files?.length) uploadEvidence(event.target.files); event.currentTarget.value = ""; }} /></label>
        </div>
      </div>
    </section>
    <ReconciliationPanel token={token} run={run} primary={workspace.primarySnapshot} dues={workspace.duesSnapshot} />
    <section className="panel transaction-panel">
      <div className="panel-heading"><div><p className="eyebrow">TRANSACTIONS</p><h3>거래 목록</h3></div><select className="inline-select" value={accountFilter} onChange={(event) => setAccountFilter(event.target.value as AccountId | "all")}><option value="all">전체 계좌</option><option value="primary">{ACCOUNT_LABELS.primary}</option><option value="dues_intake">{ACCOUNT_LABELS.dues_intake}</option></select></div>
      <TransactionTable rows={rows} accountFilter={accountFilter} evidenceById={evidenceById} onPreviewEvidence={(items) => openEvidencePreview(items).catch(() => undefined)} />
    </section>
    {previewFiles && <div className="modal-backdrop" onMouseDown={() => setPreviewFiles(null)}><section className="preview-dialog" role="dialog" aria-modal="true" aria-label="증빙 미리보기" onMouseDown={(event) => event.stopPropagation()}><header><div><p className="eyebrow">EVIDENCE</p><h3>증빙 미리보기</h3></div><button className="icon-button" aria-label="미리보기 닫기" onClick={() => setPreviewFiles(null)}><X size={18} /></button></header><div className="preview-list">{previewFiles.map((item) => <article key={item.id}><div className="preview-file-head"><strong>{item.filename}</strong><a href={item.url} download={item.filename}>원본 다운로드</a></div>{item.mime_type?.startsWith("image/") ? <img src={item.url} alt={item.filename} /> : item.mime_type === "application/pdf" ? <iframe src={item.url} title={item.filename} /> : <div className="unsupported-preview"><ReceiptText size={24} /><p>브라우저 미리보기를 지원하지 않는 형식입니다.</p></div>}</article>)}</div></section></div>}
  </>;
}

function PackagePage({ token, run }: { token: string; run: Runner }) {
  const workspace = useWorkspace(token, run);
  const [clubName, setClubName] = useState("Aegis");
  const [semester, setSemester] = useState(`${CURRENT_YEAR}년 1학기`);
  const [treasurerName, setTreasurerName] = useState("회계담당자");
  const [presidentName, setPresidentName] = useState("회장");
  const [reviewerName, setReviewerName] = useState("검토자");
  const [evidenceAccount, setEvidenceAccount] = useState<AccountId | "auto">("auto");
  const [job, setJob] = useState<any>(null);
  const [packageData, setPackageData] = useState<any>(null);
  const primary = workspace.primarySnapshot;
  const dues = workspace.duesSnapshot;
  const primaryHistory = (primary?.evidence || []).filter((item: any) => item.kind === "account_capture").length || Number(Boolean(primary?.source?.bank_transactions?.length));
  const duesHistory = (dues?.evidence || []).filter((item: any) => item.kind === "account_capture").length || Number(Boolean(dues?.source?.bank_transactions?.length));
  const ready = Boolean(primary?.id && dues?.id && primaryHistory && duesHistory);

  async function uploadEvidence(files: FileList) {
    const uploaded = await run("패키지 자료 업로드", async () => {
      const results = [];
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.append("file", file);
        form.append("kind", "auto");
        if (evidenceAccount !== "auto") form.append("account_id", evidenceAccount);
        results.push(await api<any>("/evidence/upload", token, { method: "POST", body: form }));
      }
      return results;
    });
    if (!uploaded?.length) return;
    for (const accountId of ["primary", "dues_intake"] as AccountId[]) {
      const snapshot = accountId === "primary" ? primary : dues;
      const ids = uploaded.filter((item: any) => item.account_id === accountId).map((item: any) => item.id);
      if (!snapshot?.id || !ids.length) continue;
      const revision = await run(`${ACCOUNT_LABELS[accountId]} 자료 연결`, () => api<any>(`/ledger-snapshots/${snapshot.id}/evidence`, token, { method: "POST", body: JSON.stringify({ evidence_ids: ids }) }));
      if (revision) workspace.applySnapshot(revision);
    }
  }

  async function waitForJob(jobId: string, packageId: string) {
    const started = Date.now();
    while (Date.now() - started < JOB_MAX_WAIT_MS) {
      const current = await api<any>(`/jobs/${jobId}`, token);
      setJob(current);
      if (current.status === "completed") return api<any>(`/packages/${packageId}`, token);
      if (current.status === "failed") throw new Error(current.error || "문서 생성에 실패했습니다.");
      await new Promise((resolve) => window.setTimeout(resolve, 1200));
    }
    throw new Error("문서 생성이 30분 이상 진행 중입니다.");
  }

  async function createPackage() {
    if (!ready) throw new Error("두 계좌 장부와 계좌 전체내역을 모두 준비해주세요.");
    const result = await run("동연 패키지 생성", async () => {
      const created = await api<any>("/packages/submission", token, {
        method: "POST",
        body: JSON.stringify({
          club_name: clubName,
          organization_id: "aegis",
          semester,
          period_start: PERIOD_START,
          primary_snapshot_id: primary.id,
          dues_snapshot_id: dues.id,
          treasurer_name: treasurerName,
          president_name: presidentName,
          reviewer_name: reviewerName,
          opening_balance: 0,
          primary_opening_balance: 0,
          primary_expected_closing_balance: Number(primary.transactions?.at(-1)?.balance || 0),
          dues_opening_balance: 0,
          dues_expected_closing_balance: Number(dues.transactions?.at(-1)?.balance || 0),
          row_capacity: 40,
        }),
      });
      setJob(created);
      return waitForJob(created.job_id, created.package_id);
    });
    if (result) setPackageData(result);
  }

  async function downloadPackage() {
    if (!packageData?.id) return;
    const response = await fetch(`${API_BASE}/packages/${packageData.id}/download`, { headers: { "X-ATLAS-Token": token } });
    if (!response.ok) throw await parseApiError(response);
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${clubName}_${semester}_동연제출.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return <>
    <PageHeading eyebrow="SUBMISSION PACKAGE" title="동아리연합회 제출 패키지" description={`${PERIOD_START}부터 두 계좌의 장부와 증빙을 공식 양식에 반영합니다.`} badge={<StatusBadge value={packageData?.status || (ready ? "READY" : "PREPARING")} />} />
    <section className="package-readiness">
      <AccountReadiness accountId="primary" snapshot={primary} historyCount={primaryHistory} />
      <AccountReadiness accountId="dues_intake" snapshot={dues} historyCount={duesHistory} />
    </section>
    <GooglePanel workspace={workspace} fixedStart />
    <section className="package-upload-compact">
      <div><ReceiptText size={18} /><span><strong>영수증·소명·계좌 전체내역</strong><small>#장부ID# 운영계좌 · *장부ID* 회비계좌</small></span></div>
      <select aria-label="업로드 계좌 분류" value={evidenceAccount} onChange={(event) => setEvidenceAccount(event.target.value as AccountId | "auto")}><option value="auto">파일명 자동 분류</option><option value="primary">운영계좌</option><option value="dues_intake">회비계좌</option></select>
      <label className="file-button"><Upload size={16} /> 일괄 등록<input type="file" multiple accept="image/*,.heic,.heif,.pdf,.docx" onChange={(event) => { if (event.target.files?.length) uploadEvidence(event.target.files); event.currentTarget.value = ""; }} /></label>
    </section>
    <ReconciliationPanel token={token} run={run} primary={primary} dues={dues} />
    <section className="workspace-grid package-controls">
      <div className="panel"><div className="panel-heading"><div><p className="eyebrow">DETAILS</p><h3>제출 정보</h3></div></div><div className="form-grid"><label>동아리명<input value={clubName} onChange={(event) => setClubName(event.target.value)} /></label><label>회계 기간<input value={semester} onChange={(event) => setSemester(event.target.value)} /></label><label>회계담당자<input value={treasurerName} onChange={(event) => setTreasurerName(event.target.value)} /></label><label>회장<input value={presidentName} onChange={(event) => setPresidentName(event.target.value)} /></label><label>검토자<input value={reviewerName} onChange={(event) => setReviewerName(event.target.value)} /></label><label>시작일<input value={PERIOD_START} disabled /></label></div></div>
      <div className="panel job-panel"><div className="panel-heading"><div><p className="eyebrow">STATUS</p><h3>현재 작업</h3></div>{job?.status && <StatusBadge value={job.status} />}</div>{packageData?.validation ? <><div className="validation-summary"><StatusBadge value={packageData.validation.status} /><span>오류 {packageData.validation.error_count} · 경고 {packageData.validation.warning_count}</span></div><dl className="coverage"><div><dt>운영 장부</dt><dd>{packageData.document_coverage?.ledger?.accounts?.primary?.transaction_rows || 0}건</dd></div><div><dt>회비 장부</dt><dd>{packageData.document_coverage?.ledger?.accounts?.dues_intake?.transaction_rows || 0}건</dd></div><div><dt>운영 증빙</dt><dd>{packageData.document_coverage?.evidence_documents?.primary?.embedded_files || 0}개</dd></div><div><dt>회비 증빙</dt><dd>{packageData.document_coverage?.evidence_documents?.dues_intake?.embedded_files || 0}개</dd></div></dl></> : <p className="muted">두 계좌의 준비 상태를 확인한 뒤 패키지를 생성합니다.</p>}</div>
    </section>
    <section className="action-bar">
      <button disabled={!ready} onClick={() => createPackage().catch(() => undefined)}><FileArchive size={17} /> 통합 패키지 생성</button>
      <button className="secondary" disabled={packageData?.status !== "draft"} onClick={async () => { const result = await run("검토 요청", () => api<any>(`/packages/${packageData.id}/submit-review`, token, { method: "POST" })); if (result) setPackageData(result); }}><ShieldCheck size={17} /> 검토 요청</button>
      <button className="approve" disabled={packageData?.status !== "pending_review"} onClick={async () => { const result = await run("패키지 승인", () => api<any>(`/packages/${packageData.id}/approve`, token, { method: "POST", body: JSON.stringify({ reason: "검토 완료" }) })); if (result) setPackageData(result); }}><CheckCircle2 size={17} /> 승인</button>
      <button className="secondary" disabled={!packageData?.zip_path} onClick={() => run("ZIP 다운로드", downloadPackage)}><Download size={17} /> ZIP 다운로드</button>
    </section>
  </>;
}

function AccountReadiness({ accountId, snapshot, historyCount }: { accountId: AccountId; snapshot: any; historyCount: number }) {
  const ready = Boolean(snapshot?.id && historyCount);
  const evidence = (snapshot?.evidence || []).filter((item: any) => item.kind !== "account_capture" && item.preview_available).length;
  return <article className={ready ? "ready" : ""}><div className="readiness-heading"><div><span className={`account-tag ${accountId}`}>{accountId === "primary" ? "운영" : "회비"}</span><h3>{ACCOUNT_LABELS[accountId]}</h3></div><StatusBadge value={ready ? "READY" : "REQUIRED"} /></div><dl><div><dt>장부</dt><dd>{snapshot?.transactions?.length ? `${snapshot.transactions.length}건` : "미등록"}</dd></div><div><dt>영수증·소명</dt><dd>{evidence}개</dd></div><div><dt>계좌 전체내역</dt><dd>{historyCount ? `${historyCount}개` : "필요"}</dd></div></dl></article>;
}

const RECONCILIATION_REASON_LABELS = {
  AMOUNT_MISMATCH: "금액 불일치",
  DATE_MISMATCH: "결제일 불일치",
  BANK_TRANSACTION_NOT_FOUND: "계좌 거래 없음",
};

function reconciliationReason(reason?: keyof typeof RECONCILIATION_REASON_LABELS): string {
  return reason ? RECONCILIATION_REASON_LABELS[reason] : "거래정보 불일치";
}

function bankDateTime(item: { occurred_at?: string; date?: string }): string {
  return String(item.occurred_at || item.date || "일시 미상").replace("T", " ");
}

function ReconciliationPanel({ token, run, primary, dues }: { token: string; run: Runner; primary: any; dues: any }) {
  const [results, setResults] = useState<Partial<Record<AccountId, ReconciliationResult>>>({});
  const snapshots: Record<AccountId, any> = { primary, dues_intake: dues };

  useEffect(() => {
    setResults({
      primary: primary?.source?.reconciliation,
      dues_intake: dues?.source?.reconciliation,
    });
  }, [primary?.id, dues?.id]);

  async function verify() {
    const available = (Object.entries(snapshots) as [AccountId, any][]).filter(([, snapshot]) => snapshot?.id && snapshot?.source?.bank_transactions?.length);
    const verified = await run("장부·계좌 거래정보 검증", async () => {
      if (!available.length) throw new Error("계좌 거래내역을 먼저 등록해주세요.");
      const entries = await Promise.all(available.map(async ([accountId, snapshot]) => [
        accountId,
        await api<ReconciliationResult>(`/ledger-snapshots/${snapshot.id}/reconciliation`, token),
      ] as const));
      return Object.fromEntries(entries) as Partial<Record<AccountId, ReconciliationResult>>;
    });
    if (verified) setResults((current) => ({ ...current, ...verified }));
  }

  return (
    <section className="panel reconciliation-panel">
      <div className="panel-heading reconciliation-heading">
        <div><p className="eyebrow">RECONCILIATION</p><h3>장부·계좌 거래정보 검증</h3><p className="muted">장부 날짜와 계좌 거래 일시의 날짜, 수입·지출 금액을 계좌별로 대조합니다.</p></div>
        <button className="secondary" onClick={() => verify().catch(() => undefined)}><RefreshCw size={16} /> 다시 검증</button>
      </div>
      <div className="reconciliation-grid">
        {(["primary", "dues_intake"] as AccountId[]).map((accountId) => {
          const snapshot = snapshots[accountId];
          const result = results[accountId];
          const hasBank = Boolean(snapshot?.source?.bank_transactions?.length);
          const ledgerMismatches = result?.unmatched_ledger || [];
          const bankMismatches = result?.unmatched_bank || [];
          return (
            <article key={accountId}>
              <div className="reconciliation-account">
                <div><span className={`account-tag ${accountId}`}>{accountId === "primary" ? "운영" : "회비"}</span><strong>{ACCOUNT_LABELS[accountId]}</strong></div>
                <StatusBadge value={result?.status || (hasBank ? "REQUIRED" : "NOT READY")} />
              </div>
              {!snapshot?.id ? <p className="reconciliation-empty">Google Sheets 장부를 먼저 연결해주세요.</p> : !hasBank ? <p className="reconciliation-empty">이 계좌의 거래내역 파일을 먼저 등록해주세요.</p> : result ? <>
                <dl className="reconciliation-metrics">
                  <div><dt>자동 매칭</dt><dd>{result.matched_ledger_count}/{result.ledger_transaction_count}건</dd></div>
                  <div><dt>장부 불일치</dt><dd className={result.unmatched_ledger_count ? "metric-error" : ""}>{result.unmatched_ledger_count}건</dd></div>
                  <div><dt>장부 미기록</dt><dd className={result.unmatched_bank_count ? "metric-error" : ""}>{result.unmatched_bank_count}건</dd></div>
                  <div><dt>잔액 차이</dt><dd className={result.balance_delta ? "metric-error" : ""}>{result.balance_delta == null ? "확인 불가" : money(result.balance_delta)}</dd></div>
                </dl>
                {ledgerMismatches.slice(0, 4).map((item) => <div className="mismatch-row" key={item.transaction_id || `ledger-${item.number}`}>
                  <div><strong>{item.number}번 · {reconciliationReason(item.reason)}</strong><span>{item.date} · {item.description} · {money(item.amount)}</span></div>
                  {item.candidate && <small>계좌 후보: {bankDateTime(item.candidate)} · {item.candidate.description || "내용 없음"} · {money(item.candidate.amount)}</small>}
                </div>)}
                {bankMismatches.slice(0, 3).map((item) => <div className="mismatch-row bank-only" key={item.bank_transaction_id}>
                  <div><strong>장부 미기록 계좌 거래</strong><span>{bankDateTime(item)} · {item.description || "내용 없음"} · {money(item.amount)}</span></div>
                </div>)}
                {(result.unmatched_ledger_count > 4 || result.unmatched_bank_count > 3) && <p className="reconciliation-more">나머지 불일치는 동연 패키지의 검증 리포트에서 확인할 수 있습니다.</p>}
              </> : <p className="reconciliation-empty">거래정보 검증을 실행해주세요.</p>}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function snapshotSourceLabel(snapshot: any): string {
  const action = snapshot.source?.mutation?.action;
  if (action === "snapshot.checkpoint") return "수동 체크포인트";
  if (action === "snapshot.restore") return "과거 버전 복원";
  if (action === "evidence.attached") return "증빙 연결";
  if (action === "bank_transactions.attached") return "계좌내역 연결";
  if (snapshot.source?.type === "google_sheets") return "Google Sheets";
  if (snapshot.source?.type === "workbook_upload") return "파일 가져오기";
  return "장부 생성";
}

function SnapshotManagementPage({ token, run }: { token: string; run: Runner }) {
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [accountFilter, setAccountFilter] = useState<AccountId | "all">("all");
  const [note, setNote] = useState("");

  const loadSnapshots = useCallback(() => api<any[]>("/ledger-snapshots", token).then(setSnapshots), [token]);
  useEffect(() => { loadSnapshots().catch(() => undefined); }, [loadSnapshots]);

  async function createRevision(snapshot: any, action: "checkpoint" | "restore") {
    const label = action === "checkpoint" ? "스냅샷 생성" : "스냅샷 복원";
    const result = await run(label, () => api<any>(`/ledger-snapshots/${snapshot.id}/revision`, token, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    }));
    if (result) { setNote(""); await loadSnapshots(); }
  }

  const visible = snapshots.filter((item) => accountFilter === "all" || item.account_id === accountFilter);
  const latestByAccount = Object.fromEntries((["primary", "dues_intake"] as AccountId[]).map((accountId) => [accountId, snapshots.find((item) => item.account_id === accountId && item.is_latest)]));

  return <>
    <PageHeading eyebrow="SNAPSHOT HISTORY" title="스냅샷 관리" description="장부 버전을 보존하고 필요한 시점으로 복원합니다." />
    <section className="snapshot-current-grid">
      {(["primary", "dues_intake"] as AccountId[]).map((accountId) => {
        const current = latestByAccount[accountId];
        return <article className="panel" key={accountId}><div className="panel-heading"><div><span className={`account-tag ${accountId}`}>{accountId === "primary" ? "운영" : "회비"}</span><h3>{ACCOUNT_LABELS[accountId]}</h3></div><StatusBadge value={current ? "LATEST" : "EMPTY"} /></div>{current ? <dl className="snapshot-summary"><div><dt>거래</dt><dd>{current.transaction_count}건</dd></div><div><dt>증빙</dt><dd>{current.evidence_count}개</dd></div><div><dt>생성</dt><dd>{new Date(current.created_at).toLocaleString("ko-KR")}</dd></div></dl> : <p className="muted">현재 장부 스냅샷이 없습니다.</p>}<button disabled={!current} onClick={() => createRevision(current, "checkpoint").catch(() => undefined)}><History size={16} /> 현재 상태 스냅샷 생성</button>{!current && <button className="secondary" onClick={() => window.location.assign("/ledger")}><FileSpreadsheet size={16} /> 장부 연결</button>}</article>;
      })}
    </section>
    <section className="panel snapshot-history">
      <div className="panel-heading"><div><p className="eyebrow">VERSIONS</p><h3>스냅샷 이력</h3></div><select className="inline-select" value={accountFilter} onChange={(event) => setAccountFilter(event.target.value as AccountId | "all")}><option value="all">전체 계좌</option><option value="primary">{ACCOUNT_LABELS.primary}</option><option value="dues_intake">{ACCOUNT_LABELS.dues_intake}</option></select></div>
      <label className="snapshot-note">메모<input value={note} maxLength={200} onChange={(event) => setNote(event.target.value)} placeholder="선택 사항" /></label>
      <div className="table-scroll"><table><thead><tr><th>상태</th><th>계좌</th><th>생성 시각</th><th>거래</th><th>증빙</th><th>생성 원인</th><th>메모</th><th>작업</th></tr></thead><tbody>{visible.map((snapshot) => <tr key={snapshot.id}><td>{snapshot.is_latest ? <StatusBadge value="LATEST" /> : "-"}</td><td><span className={`account-tag ${snapshot.account_id}`}>{snapshot.account_id === "dues_intake" ? "회비" : "운영"}</span></td><td>{new Date(snapshot.created_at).toLocaleString("ko-KR")}</td><td>{snapshot.transaction_count}건</td><td>{snapshot.evidence_count}개</td><td>{snapshotSourceLabel(snapshot)}</td><td>{snapshot.source?.mutation?.note || "-"}</td><td><button className="icon-button" disabled={snapshot.is_latest} title="이 버전 복원" aria-label={`${snapshot.id} 복원`} onClick={() => createRevision(snapshot, "restore").catch(() => undefined)}><RotateCcw size={15} /></button></td></tr>)}{!visible.length && <tr><td className="empty-row" colSpan={8}>스냅샷이 없습니다.</td></tr>}</tbody></table></div>
    </section>
  </>;
}

function PublicReportAdminPage({ token, run }: { token: string; run: Runner }) {
  const workspace = useWorkspace(token, run);
  const [month, setMonth] = useState(previousMonthValue());
  const [expiresAt, setExpiresAt] = useState("");
  const [report, setReport] = useState<any>(null);
  const [webhookName, setWebhookName] = useState("Aegis 회계 공지");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhook, setWebhook] = useState<any>(null);
  const [message, setMessage] = useState<any>(null);
  const primary = workspace.primarySnapshot;

  useEffect(() => {
    api<any[]>("/monthly-reports", token).then((rows) => {
      const latest = rows.find((item) => item.month_filter_version === 1 && item.status === "active");
      if (latest) setReport({ ...latest, report_id: latest.id, public_url: `${window.location.origin}/public/monthly/${latest.share_id}` });
    }).catch(() => undefined);
    api<any[]>("/discord/webhooks", token).then((rows) => setWebhook(rows[0] || null)).catch(() => undefined);
  }, [token]);

  async function createReport() {
    if (!primary?.id) return;
    const result = await run("월간 공개 페이지 생성", () => api<any>("/monthly-reports", token, {
      method: "POST",
      body: JSON.stringify({ club_name: "Aegis", month, snapshot_id: primary.id, opening_balance: 0, visible_notes: false, allow_download: false, expires_at: expiresAt ? new Date(expiresAt).toISOString() : null }),
    }));
    if (result) { setReport({ ...result, status: "active" }); setMessage(null); }
  }

  return <>
    <PageHeading eyebrow="MEMBER DISCLOSURE" title="월간 공개" description="선택한 달의 운영계좌 내역을 공개하고 Discord에 전송합니다." badge={(message || report) && <StatusBadge value={message?.status || report?.status || "ACTIVE"} />} />
    <section className="workspace-grid">
      <div className="panel"><div className="panel-heading"><div><p className="eyebrow">PUBLIC LINK</p><h3>공개 설정</h3></div></div><div className="form-grid"><label>공개 월<input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label><label>링크 만료일<input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /></label><label className="wide-field">사용 장부<input value={primary?.id || "동아리운영계좌 장부 미등록"} disabled /></label></div><div className="privacy-panel compact"><p>선택 월의 거래만 공개하며 계좌번호, 증빙 원본, 거래 상대방, 내부 검토 정보는 제외합니다.</p></div>{report?.public_url && <div className="link-output compact"><Link2 size={16} /><a href={report.public_url} target="_blank" rel="noreferrer">{report.public_url}</a>{report.expires_at && <span>{new Date(report.expires_at).toLocaleString("ko-KR")} 만료</span>}</div>}</div>
      <div className="panel"><div className="panel-heading"><div><p className="eyebrow">DISCORD</p><h3>전송 승인</h3></div></div><div className="form-stack"><label>Webhook 이름<input value={webhookName} onChange={(event) => setWebhookName(event.target.value)} /></label><label>Webhook URL<input type="password" value={webhookUrl} onChange={(event) => setWebhookUrl(event.target.value)} placeholder={webhook?.masked_url || "https://discord.com/api/webhooks/..."} /></label></div><div className="approval-flow"><span className={message ? "done" : ""}>미리보기</span><i /><span className={["approved", "sent"].includes(message?.status) ? "done" : ""}>승인</span><i /><span className={message?.status === "sent" ? "done" : ""}>전송</span></div>{message?.preview && <pre className="message-preview">{message.preview}</pre>}</div>
    </section>
    <section className="action-bar">
      <button disabled={!primary?.id || !month} onClick={() => createReport().catch(() => undefined)}><Link2 size={17} /> 공개 페이지 생성</button>
      <button className="secondary" disabled={!report?.public_url} onClick={() => window.open(report.public_url, "_blank", "noopener,noreferrer")}><ExternalLink size={17} /> 페이지 열기</button>
      <button className="secondary" disabled={!webhookUrl} onClick={async () => { const result = await run("Discord Webhook 저장", () => api<any>("/discord/webhooks", token, { method: "POST", body: JSON.stringify({ name: webhookName, webhook_url: webhookUrl }) })); if (result) { setWebhook(result); setWebhookUrl(""); } }}><ShieldCheck size={17} /> Webhook 저장</button>
      <button className="secondary" disabled={!report?.share_id || !webhook?.id} onClick={async () => { const result = await run("Discord 메시지 미리보기", () => api<any>("/discord/messages/preview", token, { method: "POST", body: JSON.stringify({ share_id: report.share_id, webhook_id: webhook.id }) })); if (result) setMessage(result); }}><ReceiptText size={17} /> 미리보기</button>
      <button className="approve" disabled={message?.status !== "pending_approval"} onClick={async () => { const result = await run("Discord 메시지 승인", () => api<any>(`/discord/messages/${message.message_id}/approve`, token, { method: "POST" })); if (result) setMessage(result); }}><CheckCircle2 size={17} /> 승인</button>
      <button disabled={!(["approved", "failed"].includes(message?.status))} onClick={async () => { const result = await run("Discord 메시지 전송", () => api<any>(`/discord/messages/${message.message_id}/send`, token, { method: "POST" })); if (result) setMessage(result); }}><Send size={17} /> 전송</button>
    </section>
  </>;
}

function MonthlyDeliveryPage({ token, run }: { token: string; run: Runner }) {
  const workspace = useWorkspace(token, run);
  const [report, setReport] = useState<any>(null);
  const [webhookName, setWebhookName] = useState("Aegis 회계 공지");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhook, setWebhook] = useState<any>(null);
  const [message, setMessage] = useState<any>(null);
  const googleWritable = Boolean(workspace.googleConnection?.connected && workspace.googleConnection?.write_access);

  useEffect(() => {
    api<any[]>("/monthly-reports", token).then((rows) => setReport(rows.find((item) => item.source_type === "google_sheet") || null)).catch(() => undefined);
    api<any[]>("/discord/webhooks", token).then((rows) => setWebhook(rows[0] || null)).catch(() => undefined);
  }, [token]);

  async function publish() {
    if (!workspace.primarySource.trim() || !workspace.monthlyDestination.trim()) {
      await run("월별 공개 시트 생성", async () => { throw new Error("원본 장부와 공개 대상 Google Sheets를 입력해주세요."); });
      return;
    }
    const result = await run(`${previousMonthLabel()} 공개 시트 생성`, () => api<any>("/monthly-reports/google-sheet", token, {
      method: "POST",
      body: JSON.stringify({ source_spreadsheet_url_or_id: workspace.primarySource, destination_spreadsheet_url_or_id: workspace.monthlyDestination, range: workspace.range, club_name: "Aegis" }),
    }));
    if (result) { setReport(result); setMessage(null); }
  }

  return <>
    <PageHeading eyebrow="MONTHLY DELIVERY" title="월별 내역 전송" description={`${previousMonthLabel()} 동아리운영계좌 내역을 Google Sheets로 공개하고 Discord에 전송합니다.`} badge={message && <StatusBadge value={message.status} />} />
    <section className="workspace-grid">
      <div className="panel"><div className="panel-heading"><div><p className="eyebrow">GOOGLE SHEETS</p><h3>공개 시트</h3></div><StatusBadge value={googleWritable ? "CONNECTED" : workspace.googleConnection?.connected ? "RECONNECT" : "DISCONNECTED"} /></div><div className="form-stack"><label>원본 동아리운영계좌 장부<input value={workspace.primarySource} onChange={(event) => workspace.setPrimarySource(event.target.value)} placeholder="Google Sheets URL 또는 ID" /></label><label>공개 대상 Google Sheets<input value={workspace.monthlyDestination} onChange={(event) => workspace.setMonthlyDestination(event.target.value)} placeholder="새 월별 시트를 추가할 Spreadsheet" /></label><p className="sharing-warning">대상 Spreadsheet 파일 전체가 링크 공개됩니다. 월별 회원 공개 전용 파일을 지정하세요.</p><label>원본 범위<input value={workspace.range} onChange={(event) => workspace.setRange(event.target.value)} /></label></div><div className="button-row">{workspace.googleConnection?.connected ? <button className="secondary danger" onClick={workspace.disconnectGoogle}><LogOut size={16} /> 연결 해제</button> : <button onClick={workspace.connectGoogle}><Link2 size={16} /> Google 계정 연결</button>}<button disabled={!googleWritable} onClick={() => publish().catch(() => undefined)}><FileSpreadsheet size={16} /> {previousMonthLabel()} 시트 생성</button></div>{report?.public_url && <div className="link-output compact"><Link2 size={16} /><a href={report.public_url} target="_blank" rel="noreferrer">{report.sheet_title || report.month}</a></div>}</div>
      <div className="panel"><div className="panel-heading"><div><p className="eyebrow">DISCORD</p><h3>전송 승인</h3></div></div><div className="form-stack"><label>Webhook 이름<input value={webhookName} onChange={(event) => setWebhookName(event.target.value)} /></label><label>Webhook URL<input type="password" value={webhookUrl} onChange={(event) => setWebhookUrl(event.target.value)} placeholder={webhook?.masked_url || "https://discord.com/api/webhooks/..."} /></label></div><div className="approval-flow"><span className={message ? "done" : ""}>미리보기</span><i /><span className={["approved", "sent"].includes(message?.status) ? "done" : ""}>승인</span><i /><span className={message?.status === "sent" ? "done" : ""}>전송</span></div>{message?.preview && <pre className="message-preview">{message.preview}</pre>}</div>
    </section>
    <section className="action-bar">
      <button className="secondary" disabled={!webhookUrl} onClick={async () => { const result = await run("Discord Webhook 저장", () => api<any>("/discord/webhooks", token, { method: "POST", body: JSON.stringify({ name: webhookName, webhook_url: webhookUrl }) })); if (result) { setWebhook(result); setWebhookUrl(""); } }}><ShieldCheck size={17} /> Webhook 저장</button>
      <button className="secondary" disabled={!report?.share_id || !webhook?.id} onClick={async () => { const result = await run("Discord 메시지 미리보기", () => api<any>("/discord/messages/preview", token, { method: "POST", body: JSON.stringify({ share_id: report.share_id, webhook_id: webhook.id }) })); if (result) setMessage(result); }}><ReceiptText size={17} /> 미리보기</button>
      <button className="approve" disabled={message?.status !== "pending_approval"} onClick={async () => { const result = await run("Discord 메시지 승인", () => api<any>(`/discord/messages/${message.message_id}/approve`, token, { method: "POST" })); if (result) setMessage(result); }}><CheckCircle2 size={17} /> 승인</button>
      <button disabled={!(["approved", "failed"].includes(message?.status))} onClick={async () => { const result = await run("Discord 메시지 전송", () => api<any>(`/discord/messages/${message.message_id}/send`, token, { method: "POST" })); if (result) setMessage(result); }}><Send size={17} /> 전송</button>
    </section>
  </>;
}

function PageHeading({ eyebrow, title, description, badge }: { eyebrow: string; title: string; description: string; badge?: React.ReactNode }) {
  return <section className="section-head"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2><p>{description}</p></div>{badge}</section>;
}

function PublicReport() {
  const shareId = window.location.pathname.split("/").pop() || "";
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<any>(`/public/monthly/${shareId}`).then(setReport).catch((err) => setError(err.message)); }, [shareId]);
  if (error) return <main className="public-shell"><div className="empty-state"><LockKeyhole size={28} /><h1>공개 자료를 열 수 없습니다</h1><p>{error}</p></div></main>;
  if (!report) return <main className="public-shell"><div className="empty-state"><LoaderCircle className="spin" size={28} /><p>회계 자료를 확인하고 있습니다.</p></div></main>;
  return <main className="public-shell"><header className="public-heading"><div className="brand"><img src="/aegis-logo.svg" alt="Aegis" /><div><p>{report.club_name}</p><h1>{report.month} 회계 투명성 자료</h1></div></div><span className="verified"><ShieldCheck size={16} /> ATLAS 공개본</span></header><section className="public-metrics"><div><span>수입</span><strong>{money(report.summary.total_income)}</strong></div><div><span>지출</span><strong>{money(report.summary.total_expense)}</strong></div><div><span>잔액</span><strong>{money(report.summary.closing_balance)}</strong></div><div><span>거래</span><strong>{report.summary.transaction_count}건</strong></div></section><section className="panel transaction-panel"><div className="panel-heading"><h3>거래 내역</h3></div><TransactionTable rows={report.transactions} /></section></main>;
}

function SettingsPage({ token, run }: { token: string; run: Runner }) {
  const [members, setMembers] = useState<any[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("reviewer");

  const load = useCallback(() => api<any[]>("/settings/access-members", token).then(setMembers), [token]);
  useEffect(() => { load().catch(() => undefined); }, [load]);

  async function saveMember() {
    const result = await run("접근 권한 저장", () => api<any>("/settings/access-members", token, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }));
    if (result) {
      setEmail("");
      await load();
    }
  }

  async function removeMember(member: any) {
    const result = await run("접근 권한 삭제", () => api<any>(`/settings/access-members/${member.id}`, token, { method: "DELETE" }));
    if (result) await load();
  }

  return <>
    <PageHeading eyebrow="ACCESS CONTROL" title="설정" description="ATLAS에 로그인할 Google 계정과 역할을 관리합니다." />
    <section className="panel access-settings">
      <div className="panel-heading"><div><h3>이메일 화이트리스트</h3><p className="muted">등록된 계정만 Google 로그인 후 권한 범위 안에서 작업할 수 있습니다.</p></div></div>
      <div className="access-add-row">
        <label>Google 계정 이메일<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="member@example.com" /></label>
        <label>역할<select value={role} onChange={(event) => setRole(event.target.value as Role)}>{Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <button disabled={!email.trim()} onClick={() => saveMember().catch(() => undefined)}><UserPlus size={16} /> 추가 또는 변경</button>
      </div>
      <div className="table-scroll"><table><thead><tr><th>이메일</th><th>역할</th><th>관리 방식</th><th>작업</th></tr></thead><tbody>{members.map((member) => <tr key={member.id}><td>{member.email}</td><td>{ROLE_LABELS[member.role as Role] || member.role}</td><td>{member.source === "environment" ? ".env 최초 관리자" : "웹 설정"}</td><td><button className="icon-button" disabled={member.source === "environment"} title="화이트리스트에서 삭제" aria-label={`${member.email} 권한 삭제`} onClick={() => removeMember(member).catch(() => undefined)}><Trash2 size={15} /></button></td></tr>)}{!members.length && <tr><td className="empty-row" colSpan={4}>등록된 계정이 없습니다.</td></tr>}</tbody></table></div>
    </section>
  </>;
}

function App() {
  const route = routeFromPath();
  const [session, setSession] = useState<Session | null>(() => storedSession());
  const [token, setToken] = useState(() => session?.token || sessionStorage.getItem("atlas_token") || "");
  const [authReady, setAuthReady] = useState(() => Boolean(session));
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    if (!toast || toast.kind === "loading") return;
    const timeout = window.setTimeout(() => setToast(null), 4500);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const run = useCallback<Runner>(async (label, action) => {
    setToast({ kind: "loading", title: label });
    try {
      const result = await action();
      setToast({ kind: "success", title: `${label} 완료` });
      return result;
    } catch (error) {
      setToast({ kind: "error", title: `${label} 실패`, detail: error instanceof Error ? error.message : "요청을 처리하지 못했습니다." });
      return undefined;
    }
  }, []);

  const storeSession = useCallback((next: Session) => {
    sessionStorage.setItem("atlas_token", next.token);
    sessionStorage.setItem("atlas_session", JSON.stringify(next));
    setToken(next.token);
    setSession(next);
  }, []);

  const clearSession = useCallback(() => {
    sessionStorage.removeItem("atlas_token");
    sessionStorage.removeItem("atlas_session");
    sessionStorage.removeItem("atlas_oauth_flow");
    setToken("");
    setSession(null);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (token && session) {
      setAuthReady(true);
      return;
    }
    if (token) {
      api<Session>("/auth/me", token).then(storeSession).catch((error) => {
        clearSession();
        setToast({ kind: "error", title: "로그인 세션 확인 실패", detail: error instanceof Error ? error.message : "다시 로그인해주세요." });
      }).finally(() => setAuthReady(true));
      return;
    }
    if (code && state && sessionStorage.getItem("atlas_oauth_flow") === "login") {
      const redirectUri = `${window.location.origin}/`;
      run("Google 로그인", () => api<Session>("/auth/google/login", undefined, {
        method: "POST",
        body: JSON.stringify({ authorization_code: code, state, redirect_uri: redirectUri }),
      })).then((next) => {
        if (!next) {
          setAuthReady(true);
          return;
        }
        sessionStorage.removeItem("atlas_oauth_flow");
        storeSession(next);
        window.location.replace("/ledger");
      });
      return;
    }
    setAuthReady(true);
  }, [clearSession, run, session, storeSession, token]);

  const redirectToLogin = authReady && (!token || !session) && window.location.pathname !== "/";
  useEffect(() => {
    if (redirectToLogin) window.location.replace("/");
  }, [redirectToLogin]);

  async function beginLogin() {
    const redirectUri = `${window.location.origin}/`;
    sessionStorage.setItem("atlas_oauth_flow", "login");
    const result = await run("Google 로그인 준비", () => api<any>(`/auth/google/login-url?redirect_uri=${encodeURIComponent(redirectUri)}`));
    if (result?.authorization_url) window.location.assign(result.authorization_url);
  }

  async function logout() {
    if (token) await api("/auth/logout", token, { method: "POST" }).catch(() => undefined);
    clearSession();
    window.location.replace("/");
  }

  const tabs: Array<{ id: RouteId; href: string; label: string; icon: React.ReactNode }> = [
    { id: "ledger", href: "/ledger", label: "장부/증빙", icon: <BookOpenCheck size={17} /> },
    { id: "package", href: "/package", label: "동연 패키지", icon: <FileArchive size={17} /> },
    { id: "public-report", href: "/public-report", label: "월간 공개", icon: <Link2 size={17} /> },
    { id: "snapshots", href: "/snapshots", label: "스냅샷 관리", icon: <History size={17} /> },
  ];
  if (session?.role === "admin") tabs.push({ id: "settings", href: "/settings", label: "설정", icon: <Settings size={17} /> });

  if (!authReady || redirectToLogin) return <main className="login-page"><LoaderCircle className="spin" size={28} /></main>;
  if (!token || !session) return <main className="login-page"><Toast toast={toast} onClose={() => setToast(null)} /><section className="login-card"><img src="/aegis-logo.svg" alt="Aegis" /><h1>Aegis ATLAS 로그인</h1><p>권한이 부여된 Aegis 운영 계정만 접근할 수 있습니다.</p><button onClick={() => beginLogin().catch(() => undefined)}><ExternalLink size={16} /> Google 계정으로 로그인</button></section></main>;
  const activeRoute = route === "settings" && session.role !== "admin" ? "ledger" : route;
  return <main className="app-shell"><Toast toast={toast} onClose={() => setToast(null)} /><header className="topbar"><a className="brand" href="/ledger"><img src="/aegis-logo.svg" alt="Aegis" /><div><p>Aegis ATLAS</p><h1>Aegis Transaction Ledger &amp; Accounting System</h1></div></a><div className="session-state"><span><span className="dot online" />{session.email} · {ROLE_LABELS[session.role]}</span><button className="icon-button" title="로그아웃" aria-label="로그아웃" onClick={() => logout().catch(() => undefined)}><LogOut size={15} /></button></div></header><nav className="tabs" aria-label="ATLAS 메뉴">{tabs.map((tab) => <a key={tab.id} href={tab.href} className={activeRoute === tab.id ? "active" : ""}>{tab.icon}{tab.label}</a>)}</nav><div className="page-content">{activeRoute === "ledger" ? <LedgerPage token={token} run={run} /> : activeRoute === "snapshots" ? <SnapshotManagementPage token={token} run={run} /> : activeRoute === "public-report" ? <PublicReportAdminPage token={token} run={run} /> : activeRoute === "settings" ? <SettingsPage token={token} run={run} /> : <PackagePage token={token} run={run} />}</div></main>;
}

class AppErrorBoundary extends React.Component<{ children: React.ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <main className="login-page"><section className="login-card"><img src="/aegis-logo.svg" alt="Aegis" /><h1>페이지를 불러오지 못했습니다</h1><p>화면 데이터 형식이 변경되었거나 일시적인 오류가 발생했습니다.</p><button onClick={() => window.location.reload()}><RefreshCw size={16} /> 다시 불러오기</button></section></main>;
    }
    return this.props.children;
  }
}

const root = createRoot(document.getElementById("root")!);
root.render(<AppErrorBoundary>{window.location.pathname.startsWith("/public/monthly/") ? <PublicReport /> : <App />}</AppErrorBoundary>);
