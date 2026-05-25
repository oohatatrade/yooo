const form = document.querySelector("#searchForm");
const statusBox = document.querySelector("#status");
const runButton = document.querySelector("#runButton");
const resultBar = document.querySelector("#resultBar");
const countText = document.querySelector("#countText");
const downloadLink = document.querySelector("#downloadLink");
const previewBody = document.querySelector("#previewBody");
const cancelButton = document.querySelector("#cancelButton");
const infoType = document.querySelector("#infoType");
const sourceLink = document.querySelector("#sourceLink");
const idHeader = document.querySelector("#idHeader");
const dateHeader = document.querySelector("#dateHeader");
const partyHeader = document.querySelector("#partyHeader");
const amountHeader = document.querySelector("#amountHeader");

let currentController = null;
let timeoutId = null;

function formToPayload(formElement) {
  const data = new FormData(formElement);
  return Object.fromEntries(data.entries());
}

function setBusy(isBusy) {
  runButton.disabled = isBusy;
  cancelButton.hidden = !isBusy;
  runButton.textContent = isBusy ? "取得中..." : "取得してExcel作成";
}

function currentMode() {
  return infoType.value === "order" ? "order" : "contract";
}

function updateTableLabels() {
  if (currentMode() === "order") {
    sourceLink.href = "https://cals05.pref.akita.lg.jp/ecydeen/do/PPI/koukoku";
    idHeader.textContent = "公開日";
    dateHeader.textContent = "入札方式";
    partyHeader.textContent = "入札執行課所";
    amountHeader.textContent = "予定価格";
  } else {
    sourceLink.href = "https://cals05.pref.akita.lg.jp/ecydeen/do/PPI/keiyaku";
    idHeader.textContent = "契約公表番号";
    dateHeader.textContent = "契約日";
    partyHeader.textContent = "請負者";
    amountHeader.textContent = "契約金額";
  }
}

function renderRows(rows) {
  previewBody.innerHTML = "";
  if (!rows.length) {
    const label = currentMode() === "order" ? "発注情報" : "契約結果";
    previewBody.innerHTML = `<tr><td colspan="7" class="empty">該当する${label}はありませんでした。</td></tr>`;
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    const cells = currentMode() === "order"
      ? [
          row.published_date,
          row.bidding_method,
          row.project_name,
          row.location,
          row.department,
          row.estimated_price,
          row.procurement_category,
        ]
      : [
          row.contract_no,
          row.contract_date,
          row.project_name,
          row.location,
          row.contractor,
          row.contract_amount,
          row.procurement_category,
        ];
    for (const value of cells) {
      const td = document.createElement("td");
      td.textContent = value || "";
      tr.appendChild(td);
    }
    previewBody.appendChild(tr);
  }
}

infoType.addEventListener("change", () => {
  updateTableLabels();
  renderRows([]);
  resultBar.hidden = true;
  statusBox.textContent = currentMode() === "order"
    ? "発注情報を取得します。条件を指定して取得を開始してください。"
    : "契約結果情報を取得します。条件を指定して取得を開始してください。";
});

function resetRequestState() {
  if (timeoutId) {
    clearTimeout(timeoutId);
    timeoutId = null;
  }
  currentController = null;
  setBusy(false);
}

cancelButton.addEventListener("click", () => {
  if (currentController) {
    currentController.abort();
  }
  statusBox.textContent = "取得をキャンセルしました。条件を変更して再実行できます。";
  resultBar.hidden = true;
  resetRequestState();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (currentController) {
    currentController.abort();
  }

  currentController = new AbortController();
  timeoutId = setTimeout(() => {
    if (currentController) {
      currentController.abort();
    }
  }, 90000);

  setBusy(true);
  resultBar.hidden = true;
  statusBox.textContent = "秋田県電子入札システムに接続して検索しています。件数が多い場合は少し時間がかかります。";

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formToPayload(form)),
      signal: currentController.signal,
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "取得に失敗しました。");
    }
    countText.textContent = `${result.count}件`;
    downloadLink.href = result.downloadUrl;
    downloadLink.download = result.fileName;
    resultBar.hidden = false;
    statusBox.textContent = result.count === 0
      ? `検索結果は0件でした。Excelファイル ${result.fileName} を作成しました。`
      : `Excelファイル ${result.fileName} を作成しました。プレビューは先頭30件です。`;
    renderRows(result.rows || []);
  } catch (error) {
    if (error.name === "AbortError") {
      statusBox.textContent = "取得を中断しました。検索条件を変更して再実行できます。";
    } else {
      statusBox.textContent = error.message;
    }
    renderRows([]);
  } finally {
    resetRequestState();
  }
});

updateTableLabels();
