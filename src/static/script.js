// 印刷はサーバー側（app.py の print_ticket）で処理します。
// ブラウザ側での印刷コードは不要です。

let selectedStaffCount = null;

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

function issueTicket(element, buttonText) {
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
                alert(`Error: ${data.error}`);
            } else {
                document.getElementById(`number${category}`).innerText = `次の番号: ${data.next_number}`;
            }
        })
        .catch(error => {
            console.error('There was an error!', error);
        });
}
