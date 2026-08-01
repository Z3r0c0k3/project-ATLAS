import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type TransactionInput = {
  number: number;
  date: string;
  description: string;
  income: number;
  expense: number;
  balance: number;
  note?: string;
  evidence_id?: string;
};

type EvidenceInput = {
  id: string;
  transaction_number?: number;
  filename: string;
  kind: "receipt" | "explanation" | "account_capture" | "other";
  url?: string;
};

const initialTransactions: TransactionInput[] = [
  {
    number: 1,
    date: "2026-03-01",
    description: "3월 동아리 회비",
    income: 340000,
    expense: 0,
    balance: 1340000,
    note: "20,000 * 17명",
  },
  {
    number: 2,
    date: "2026-03-04",
    description: "동아리 홍보용 X배너",
    income: 0,
    expense: 22000,
    balance: 1318000,
    evidence_id: "ev-banner",
  },
  {
    number: 3,
    date: "2026-03-12",
    description: "동아리 행사 굿즈",
    income: 0,
    expense: 237600,
    balance: 1080400,
    evidence_id: "ev-goods",
  },
];

const initialEvidence: EvidenceInput[] = [
  { id: "ev-banner", transaction_number: 2, filename: "banner_receipt.png", kind: "receipt" },
  { id: "ev-goods", transaction_number: 3, filename: "goods_receipt.pdf", kind: "receipt" },
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

function money(value: number): string {
  return `${value.toLocaleString("ko-KR")}원`;
}

function PublicReport() {
  const shareId = window.location.pathname.split("/").pop() ?? "";
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<any>(`/public/monthly/${shareId}`)
      .then(setReport)
      .catch((err) => setError(err.message));
  }, [shareId]);

  if (error) return <main className="public-shell"><p>{error}</p></main>;
  if (!report) return <main className="public-shell"><p>공개 자료를 불러오는 중입니다.</p></main>;

  return (
    <main className="public-shell">
      <section className="public-heading">
        <p>{report.club_name}</p>
        <h1>{report.month} 회계 투명성 자료</h1>
      </section>
      <section className="metric-grid">
        <Metric label="수입" value={money(report.summary.total_income)} />
        <Metric label="지출" value={money(report.summary.total_expense)} />
        <Metric label="잔액" value={money(report.summary.closing_balance)} />
        <Metric label="거래 수" value={`${report.summary.transaction_count}건`} />
      </section>
      <section className="table-wrap">
        <h2>거래 내역</h2>
        <TransactionTable rows={report.transactions} />
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TransactionTable({ rows }: { rows: TransactionInput[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>번호</th>
          <th>날짜</th>
          <th>내용</th>
          <th>수입</th>
          <th>지출</th>
          <th>잔액</th>
          <th>비고</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.number}>
            <td>{row.number}</td>
            <td>{row.date}</td>
            <td>{row.description}</td>
            <td>{row.income ? money(row.income) : "-"}</td>
            <td>{row.expense ? money(row.expense) : "-"}</td>
            <td>{money(row.balance)}</td>
            <td>{row.note || "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function App() {
  const [username, setUsername] = useState("aegis");
  const [role, setRole] = useState("accountant");
  const [authToken, setAuthToken] = useState("");
  const [clubName, setClubName] = useState("Aegis");
  const [semester, setSemester] = useState("2026년 1학기");
  const [month, setMonth] = useState("2026년 3월");
  const [openingBalance, setOpeningBalance] = useState(1000000);
  const [expectedClosingBalance, setExpectedClosingBalance] = useState(1080400);
  const [treasurerName, setTreasurerName] = useState("회계담당자");
  const [presidentName, setPresidentName] = useState("회장");
  const [reviewerName, setReviewerName] = useState("검토자");
  const [transactionsText, setTransactionsText] = useState(JSON.stringify(initialTransactions, null, 2));
  const [evidenceText, setEvidenceText] = useState(JSON.stringify(initialEvidence, null, 2));
  const [webhookName, setWebhookName] = useState("Aegis 회계 공지");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookId, setWebhookId] = useState("");
  const [shareId, setShareId] = useState("");
  const [publicUrl, setPublicUrl] = useState("");
  const [packageDownloadUrl, setPackageDownloadUrl] = useState("");
  const [messageId, setMessageId] = useState("");
  const [output, setOutput] = useState<any>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const transactions = useMemo(() => JSON.parse(transactionsText) as TransactionInput[], [transactionsText]);
  const evidence = useMemo(() => JSON.parse(evidenceText) as EvidenceInput[], [evidenceText]);

  const totalIncome = transactions.reduce((sum, row) => sum + Number(row.income || 0), 0);
  const totalExpense = transactions.reduce((sum, row) => sum + Number(row.expense || 0), 0);
  const computedClosing = openingBalance + totalIncome - totalExpense;

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    return api<T>(path, {
      ...init,
      headers: {
        ...(authToken ? { "X-ATLAS-Token": authToken } : {}),
        ...(init?.headers ?? {}),
      },
    });
  }

  async function run<T>(label: string, action: () => Promise<T>) {
    setBusy(label);
    setError("");
    try {
      const result = await action();
      setOutput(result);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : "요청 처리 중 오류가 발생했습니다.");
    } finally {
      setBusy("");
    }
  }

  async function downloadPackage() {
    if (!packageDownloadUrl || !authToken) return;
    setBusy("제출 ZIP 다운로드");
    setError("");
    try {
      const response = await fetch(`${API_BASE}${packageDownloadUrl}`, {
        headers: { "X-ATLAS-Token": authToken },
      });
      if (!response.ok) throw new Error(await response.text());
      const blobUrl = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = blobUrl;
      anchor.download = "ATLAS_동연_제출_패키지.zip";
      anchor.click();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ZIP 다운로드 중 오류가 발생했습니다.");
    } finally {
      setBusy("");
    }
  }

  const basePayload = {
    club_name: clubName,
    semester,
    treasurer_name: treasurerName,
    president_name: presidentName,
    reviewer_name: reviewerName,
    opening_balance: openingBalance,
    expected_closing_balance: expectedClosingBalance,
    row_capacity: 40,
    transactions,
    evidence,
  };

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p>ATLAS</p>
          <h1>Aegis 회계 자동화 콘솔</h1>
        </div>
        <div className="status-pill">{authToken ? `${role} 로그인` : busy || "로그인 필요"}</div>
      </header>

      <section className="panel login-panel">
        <h2>로그인 및 역할</h2>
        <div className="form-grid login-grid">
          <label>사용자<input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label>
            역할
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="admin">관리자</option>
              <option value="accountant">회계담당자</option>
              <option value="president">회장</option>
              <option value="reviewer">검토자</option>
            </select>
          </label>
          <button
            onClick={async () => {
              const session: any = await run("로그인", () =>
                api("/auth/login", {
                  method: "POST",
                  body: JSON.stringify({ username, role }),
                }),
              );
              if (session?.token) setAuthToken(session.token);
            }}
          >
            로그인
          </button>
        </div>
      </section>

      <section className="metric-grid">
        <Metric label="수입총액" value={money(totalIncome)} />
        <Metric label="지출총액" value={money(totalExpense)} />
        <Metric label="계산잔액" value={money(computedClosing)} />
        <Metric label="기대잔액" value={money(expectedClosingBalance)} />
      </section>

      <section className="workspace-grid">
        <div className="panel">
          <h2>기본 정보</h2>
          <div className="form-grid">
            <label>동아리명<input value={clubName} onChange={(e) => setClubName(e.target.value)} /></label>
            <label>학기<input value={semester} onChange={(e) => setSemester(e.target.value)} /></label>
            <label>공개 월<input value={month} onChange={(e) => setMonth(e.target.value)} /></label>
            <label>이전 잔액<input type="number" value={openingBalance} onChange={(e) => setOpeningBalance(Number(e.target.value))} /></label>
            <label>최종 잔액<input type="number" value={expectedClosingBalance} onChange={(e) => setExpectedClosingBalance(Number(e.target.value))} /></label>
            <label>회계담당자<input value={treasurerName} onChange={(e) => setTreasurerName(e.target.value)} /></label>
            <label>회장<input value={presidentName} onChange={(e) => setPresidentName(e.target.value)} /></label>
            <label>검토자<input value={reviewerName} onChange={(e) => setReviewerName(e.target.value)} /></label>
          </div>
        </div>

        <div className="panel">
          <h2>Google 연결</h2>
          <div className="button-row">
            <button onClick={() => run("Google Sheets 확인", () => request("/google/sheets"))}>Sheets</button>
            <button onClick={() => run("Google Drive 확인", () => request("/google/drive/files"))}>Drive</button>
          </div>
        </div>
      </section>

      <section className="editor-grid">
        <label className="editor-block">거래 데이터 JSON<textarea value={transactionsText} onChange={(e) => setTransactionsText(e.target.value)} /></label>
        <label className="editor-block">증빙 데이터 JSON<textarea value={evidenceText} onChange={(e) => setEvidenceText(e.target.value)} /></label>
      </section>

      <section className="action-band">
        <button
          onClick={async () => {
            const packageResult: any = await run("동연 제출 패키지 생성", () =>
              request("/packages/submission", {
                method: "POST",
                body: JSON.stringify(basePayload),
              }),
            );
            if (packageResult?.download_url) setPackageDownloadUrl(packageResult.download_url);
          }}
        >
          제출 패키지 생성
        </button>
        <button disabled={!packageDownloadUrl} onClick={downloadPackage}>
          제출 ZIP 다운로드
        </button>
        <button
          onClick={async () => {
            const report: any = await run("월간 공개 페이지 생성", () =>
              request("/monthly-reports", {
                method: "POST",
                body: JSON.stringify({
                  club_name: clubName,
                  month,
                  opening_balance: openingBalance,
                  transactions,
                  visible_notes: false,
                }),
              }),
            );
            if (report?.share_id) {
              setShareId(report.share_id);
              setPublicUrl(report.public_url);
            }
          }}
        >
          월간 공개 생성
        </button>
        <button
          disabled={!publicUrl}
          onClick={() => window.open(publicUrl, "_blank", "noopener,noreferrer")}
        >
          공개 페이지 열기
        </button>
      </section>

      <section className="workspace-grid">
        <div className="panel">
          <h2>Discord Webhook</h2>
          <div className="form-grid single">
            <label>이름<input value={webhookName} onChange={(e) => setWebhookName(e.target.value)} /></label>
            <label>Webhook URL<input value={webhookUrl} onChange={(e) => setWebhookUrl(e.target.value)} /></label>
          </div>
          <div className="button-row">
            <button
              onClick={async () => {
                const webhook: any = await run("Webhook 저장", () =>
                  request("/discord/webhooks", {
                    method: "POST",
                    body: JSON.stringify({ name: webhookName, webhook_url: webhookUrl }),
                  }),
                );
                if (webhook?.id) setWebhookId(webhook.id);
              }}
            >
              Webhook 저장
            </button>
            <button
              disabled={!shareId || !webhookId}
              onClick={async () => {
                const message: any = await run("Discord 미리보기", () =>
                  request("/discord/messages/preview", {
                    method: "POST",
                    body: JSON.stringify({ share_id: shareId, webhook_id: webhookId }),
                  }),
                );
                if (message?.message_id) setMessageId(message.message_id);
              }}
            >
              메시지 미리보기
            </button>
            <button
              disabled={!messageId}
              onClick={() => run("Discord 승인 전송", () => request(`/discord/messages/${messageId}/send`, { method: "POST" }))}
            >
              승인 전송
            </button>
          </div>
        </div>

        <div className="panel">
          <h2>작업 결과</h2>
          {error && <pre className="error-box">{error}</pre>}
          {output && <pre className="result-box">{JSON.stringify(output, null, 2)}</pre>}
        </div>
      </section>
    </main>
  );
}

const root = createRoot(document.getElementById("root")!);
root.render(window.location.pathname.startsWith("/public/monthly/") ? <PublicReport /> : <App />);
