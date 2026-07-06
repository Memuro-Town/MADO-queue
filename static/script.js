// 印刷はサーバー側（app.py の print_ticket）で処理します。
// ブラウザ側での印刷コードは不要です。

let selectedStaffCount = null;
const ISSUE_BUTTON_LOCK_MS = 2000;

function selectStaff(count) {
    selectedStaffCount = count;
    document.querySelectorAll('.staff-btn').forEach((btn, idx) => {
        if (idx + 1 === count) {
            btn.classList.remove('btn-outline-dark');
            btn.classList.add('btn-dark');
        } else {
            btn.classList.remove('btn-dark');
            btn.classList.add('btn-outline-dark');
        }
    });
    document.getElementById('staffCountDisplay').textContent = `現在：${count}人`;
}

function setIssueButtonLocked(element) {
    element.disabled = true;
    setTimeout(() => {
        element.disabled = false;
    }, ISSUE_BUTTON_LOCK_MS);
}

function flashIssueButton(element, className) {
    element.classList.add(className);
    setTimeout(() => {
        element.classList.remove(className);
    }, ISSUE_BUTTON_LOCK_MS);
}

function updateTicketMessage(category, message, className) {
    const numberElement = document.getElementById(`number${category}`);
    numberElement.innerText = message;
    numberElement.classList.remove('text-success', 'text-warning', 'text-danger');
    numberElement.classList.add(className);
    setTimeout(() => {
        numberElement.classList.remove(className);
    }, ISSUE_BUTTON_LOCK_MS);
}

function issueTicket(element, buttonText) {
    if (element.disabled) {
        return;
    }

    setIssueButtonLocked(element);

    const category = element.getAttribute('data-category');
    const now = new Date();

    const japanTimeFormatter = new Intl.DateTimeFormat('ja-JP', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: 'Asia/Tokyo',
        hour12: false
    });

    if ('vibrate' in navigator) {
        navigator.vibrate(100);
    }

    element.classList.add('active');
    setTimeout(() => element.classList.remove('active'), 500);

    const formattedJapanTime = japanTimeFormatter.format(now);
    const timestamp = formattedJapanTime
        .replace(/\//g, '-')
        .replace(/\s/g, 'T')
        .replace(/(\d{2}):(\d{2}):(\d{2})$/, '$1:$2:$3+09:00');

    fetch('/get_next_number', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            category: category,
            buttonText: buttonText,
            timestamp: timestamp,
            staffCount: selectedStaffCount
        })
    })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                updateTicketMessage(category, `発券できませんでした: ${data.error}`, 'text-danger');
                flashIssueButton(element, 'ticket-feedback-error');
            } else if (data.print_ok === false) {
                updateTicketMessage(
                    category,
                    `番号 ${data.next_number} を発券しました。印刷されていない可能性があります。`,
                    'text-warning'
                );
                flashIssueButton(element, 'ticket-feedback-warning');
            } else {
                updateTicketMessage(category, `番号 ${data.next_number} を発券しました`, 'text-success');
                flashIssueButton(element, 'ticket-feedback-success');
            }
        })
        .catch(error => {
            console.error('There was an error!', error);
            updateTicketMessage(category, '通信エラーのため発券結果を確認できませんでした', 'text-danger');
            flashIssueButton(element, 'ticket-feedback-error');
        });
}
