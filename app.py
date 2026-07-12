"""
MADO-Queue — 窓口番号発券・呼び出し管理システム

画面構成:
  /           発券画面   (タブレット設置。来庁者が番号を取る)
  /processing 処理画面   (職員用。呼び出し・対応開始・完了を操作)
  /display    案内表示   (ロビーのモニター用。呼び出し番号を大画面表示)

カテゴリ番号帯: A=001-499, B=500-799, C=800- (config.py 参照)
"""

from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import os
import sqlite3

from flask import Flask, jsonify, request, render_template
from flask_cors import CORS

from config import CATEGORY_START

app = Flask(__name__)
_cors_origins = os.environ.get('CORS_ORIGINS', 'http://localhost:8000').split(',')
CORS(app, origins=_cors_origins)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DB_PATH', os.path.join(BASE_DIR, 'numbers.db'))

# ---------------------------------------------------------------------------
# レシートプリンター
# ---------------------------------------------------------------------------

PRINTER_NAME   = os.environ.get('PRINTER_NAME',   'POS-80C (copy 1)')
PRINTER_VID    = int(os.environ.get('PRINTER_VID', '0x04b8'), 16)
PRINTER_PID    = int(os.environ.get('PRINTER_PID', '0x0e20'), 16)


def _build_escpos_data(category, button_text, number, timestamp_str, encoding='utf-8'):
    """ESC/POSバイト列を組み立てる。Windows(win32print)はcp932、Linux(pyusb)はutf-8。"""
    ESC = b'\x1b'
    GS  = b'\x1d'

    def s(text):
        return text.encode(encoding, errors='replace')

    try:
        dt = datetime.fromisoformat(timestamp_str)
        formatted_time = dt.strftime('%m.%d-%H:%M:%S')
    except Exception:
        formatted_time = timestamp_str or ''

    data  = ESC + b'@'            # 初期化
    data += ESC + b'a\x01'        # 中央揃え
    data += GS  + b'!\x01'        # 縦2倍
    data += s(f'カテゴリ: {category}\n')
    data += s(f'用途: {button_text}\n\n')
    data += s(f'日時: {formatted_time}\n\n')
    data += GS  + b'!\x33'        # 縦横4倍
    data += s(f'番号: {number}\n\n')
    data += GS  + b'!\x00'        # 通常サイズに戻す
    if category != 'A':
        data += s('カテゴリAの方を先に\nご案内する場合があります\n')
    data += GS + b'V\x41\x30'     # 48ドット送ってからカット
    return data


def _print_windows(data):
    """Windows: win32print でRAW送信（2枚）"""
    import win32print
    for copy in range(2):
        h = win32print.OpenPrinter(PRINTER_NAME)
        try:
            win32print.StartDocPrinter(h, 1, (f'ticket-{copy+1}', None, 'RAW'))
            try:
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
            finally:
                win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)


_usb_dev = None  # USB デバイスのシングルトン（起動時に一度だけ初期化）


def _get_usb_dev():
    """USB プリンターデバイスを返す。初回のみ find + set_configuration() を実行する。"""
    global _usb_dev
    if _usb_dev is None:
        import usb.core
        dev = usb.core.find(idVendor=PRINTER_VID, idProduct=PRINTER_PID)
        if dev is None:
            raise RuntimeError(
                f'プリンターが見つかりません (VID={PRINTER_VID:#06x} PID={PRINTER_PID:#06x})'
            )
        dev.set_configuration()  # 初回のみ実行（毎回呼ぶとUSBリセットが発生する）
        _usb_dev = dev
    return _usb_dev


def _print_linux(data):
    """Linux: pyusb でUSB直接送信（2枚）"""
    dev = _get_usb_dev()
    for _ in range(2):
        dev.write(1, data)

def print_ticket(category, button_text, number, timestamp_str):
    """レシートプリンターにチケットを印刷する。カテゴリDは印刷せず成功扱いにする。"""
    if category == 'D':
        return True
    try:
        import sys
        encoding = 'cp932' if sys.platform == 'win32' else 'utf-8'
        data = _build_escpos_data(category, button_text or '', number, timestamp_str or '', encoding)
        if sys.platform == 'win32':
            _print_windows(data)
        else:
            _print_linux(data)
        print(f'[print_ticket] 印刷完了: カテゴリ={category} 番号={number}')
        return True
    except Exception as e:
        print(f'[print_ticket] error: {e}')
        return False


# ---------------------------------------------------------------------------
# DB ヘルパー
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    """SQLite 接続を提供するコンテキストマネージャ。例外時は自動ロールバック。"""
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 入力検証ヘルパー
# ---------------------------------------------------------------------------

def _parse_int(value):
    """int に変換して返す。変換できない場合は None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_valid_category(category):
    """category が定義済みカテゴリ（A/B/C/D）かどうか。"""
    return category in CATEGORY_START


# ---------------------------------------------------------------------------
# 共通 SQL
# ---------------------------------------------------------------------------

# 本日の未処理チケット一覧を返す SELECT。
# event_log_id が存在する新形式と、旧形式（ticket_number + category）の両方に対応する。
# 旧形式との互換性のため OR 条件が必要。
_WAITING_LIST_SQL = """
    SELECT id, current_number, button_text, timestamp, category
    FROM event_logs
    WHERE DATE(timestamp, 'localtime') = DATE('now', 'localtime')
    AND category != 'D'
    AND NOT EXISTS (
        SELECT 1 FROM processing_logs pl
        WHERE (
            (pl.event_log_id IS NOT NULL AND pl.event_log_id = event_logs.id)
            OR
            (pl.event_log_id IS NULL
             AND pl.ticket_number = event_logs.current_number
             AND pl.category = event_logs.category)
        )
        AND DATE(pl.created_at, 'localtime') = DATE('now', 'localtime')
    )
    ORDER BY timestamp ASC
"""


# ---------------------------------------------------------------------------
# ルート
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/get_next_number', methods=['POST'])
def get_next_number():
    category = request.json.get('category')
    if not category:
        return jsonify({'error': 'Category is required'}), 400

    button_text = request.json.get('buttonText')
    staff_count = request.json.get('staffCount')
    # timestamp 未指定でも NOT NULL 制約で失敗しないようサーバー時刻で補完
    timestamp   = request.json.get('timestamp') or datetime.now().astimezone().isoformat()

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # 同時発券による番号重複を防ぐため、SELECT の前に書き込みロックを取得する
            cursor.execute('BEGIN IMMEDIATE')

            cursor.execute(
                'SELECT current_number, timestamp FROM numbers WHERE category = ?',
                (category,)
            )
            result = cursor.fetchone()
            if not result:
                return jsonify({'error': 'Invalid category'}), 404

            current_number, last_updated_date = result
            today_str = datetime.now().date().isoformat()

            # 日付が変わっていてかつ本日のログがまだ 0 件なら番号をリセットする。
            # timestamp だけではなくログ件数も確認するのは、サーバー再起動等で
            # timestamp が更新されないケースを防ぐため。
            if last_updated_date != today_str:
                cursor.execute(
                    "SELECT COUNT(*) FROM event_logs"
                    " WHERE category = ?"
                    " AND DATE(timestamp, 'localtime') = DATE('now', 'localtime')",
                    (category,)
                )
                if cursor.fetchone()[0] == 0:
                    current_number = CATEGORY_START[category]
                    new_number = current_number
                else:
                    new_number = current_number + 1
            else:
                new_number = current_number + 1

            cursor.execute(
                'UPDATE numbers SET current_number = ?, timestamp = ? WHERE category = ?',
                (new_number, today_str, category)
            )
            cursor.execute(
                'INSERT INTO event_logs'
                ' (category, button_text, timestamp, current_number, staff_count)'
                ' VALUES (?, ?, ?, ?, ?)',
                (category, button_text, timestamp, new_number, staff_count)
            )
    except Exception as e:
        print(f"get_next_number error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

    # DB書き込み成功後に印刷（失敗しても発券結果は返す）
    print_ok = print_ticket(category, button_text or '', new_number, timestamp or '')

    return jsonify({
        'category': category,
        'next_number': new_number,
        'print_ok': print_ok,
    })


@app.route('/start_processing', methods=['POST'])
def start_processing():
    data          = request.json
    ticket_number = data.get('ticket_number')
    category      = data.get('category')
    button_text   = data.get('button_text')
    timestamp_str = data.get('timestamp')
    event_log_id  = data.get('event_log_id')

    if not ticket_number:
        return jsonify({'success': False, 'error': 'Ticket number is required'}), 400

    # XSS・不正データ格納防止: 番号は整数、カテゴリは定義済みのものに限定
    ticket_number = _parse_int(ticket_number)
    if ticket_number is None:
        return jsonify({'success': False, 'error': 'Invalid ticket number'}), 400
    if category is not None and not _is_valid_category(category):
        return jsonify({'success': False, 'error': 'Invalid category'}), 400
    if event_log_id is not None:
        event_log_id = _parse_int(event_log_id)
        if event_log_id is None:
            return jsonify({'success': False, 'error': 'Invalid event log id'}), 400

    current_time    = datetime.now()
    start_time_str  = current_time.isoformat()

    try:
        ticket_time = datetime.fromisoformat(timestamp_str) if timestamp_str else current_time
        if ticket_time.tzinfo is not None and current_time.tzinfo is None:
            current_time = current_time.astimezone()
        wait_time_minutes = int((current_time - ticket_time).total_seconds() // 60)
    except Exception as e:
        print(f"wait time calculation error: {e}")
        wait_time_minutes = 0

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # event_log_id がある場合はそちらで直接引く（旧データは ticket_number+category で検索）
            if event_log_id:
                cursor.execute(
                    'SELECT staff_count FROM event_logs WHERE id = ?',
                    (event_log_id,)
                )
            else:
                cursor.execute(
                    'SELECT staff_count FROM event_logs'
                    ' WHERE current_number = ? AND category = ?'
                    ' ORDER BY id DESC LIMIT 1',
                    (ticket_number, category)
                )
            staff_row   = cursor.fetchone()
            staff_count = staff_row[0] if staff_row else None

            cursor.execute(
                'INSERT INTO processing_logs'
                ' (ticket_number, category, button_text, start_time,'
                '  wait_time, status, created_at, staff_count, event_log_id)'
                ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ticket_number, category, button_text, start_time_str,
                 wait_time_minutes, 'processing', start_time_str,
                 staff_count, event_log_id)
            )
    except Exception as e:
        print(f"start_processing error: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'})

    return jsonify({'success': True})


@app.route('/end_processing', methods=['POST'])
def end_processing():
    ticket_number = request.json.get('ticket_number')
    if not ticket_number:
        return jsonify({'success': False, 'error': 'Ticket number is required'}), 400

    ticket_number = _parse_int(ticket_number)
    if ticket_number is None:
        return jsonify({'success': False, 'error': 'Invalid ticket number'}), 400

    current_time = datetime.now()
    end_time_str = current_time.isoformat()

    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # 番号は毎日リセットされるため、過去日の同番号レコードに
            # 作用しないよう本日分に限定する
            cursor.execute(
                'SELECT start_time FROM processing_logs'
                ' WHERE ticket_number = ? AND status = ?'
                " AND DATE(created_at, 'localtime') = DATE('now', 'localtime')",
                (ticket_number, 'processing')
            )
            result = cursor.fetchone()
            if not result:
                return jsonify({'success': False, 'error': 'Processing record not found'}), 404

            start_time = datetime.fromisoformat(result[0])
            if start_time.tzinfo is not None and current_time.tzinfo is None:
                current_time = current_time.astimezone()
            processing_time_seconds = int((current_time - start_time).total_seconds())

            cursor.execute(
                'UPDATE processing_logs'
                ' SET end_time = ?, processing_time = ?, status = ?'
                ' WHERE ticket_number = ? AND status = ?'
                " AND DATE(created_at, 'localtime') = DATE('now', 'localtime')",
                (end_time_str, processing_time_seconds, 'completed',
                 ticket_number, 'processing')
            )
    except Exception as e:
        print(f"end_processing error: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'})

    return jsonify({'success': True})


@app.route('/cancel_processing', methods=['POST'])
def cancel_processing():
    """対応中チケットを待ち行列に戻す（processing_logs レコードを削除してキューに復帰）。"""
    ticket_number = request.json.get('ticket_number')
    if not ticket_number:
        return jsonify({'success': False, 'error': 'Ticket number is required'}), 400

    ticket_number = _parse_int(ticket_number)
    if ticket_number is None:
        return jsonify({'success': False, 'error': 'Invalid ticket number'}), 400

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            # 本日分に限定（過去日の同番号レコードを誤って消さない）
            cursor.execute(
                'DELETE FROM processing_logs WHERE ticket_number = ? AND status = ?'
                " AND DATE(created_at, 'localtime') = DATE('now', 'localtime')",
                (ticket_number, 'processing')
            )
            if cursor.rowcount == 0:
                return jsonify({
                    'success': False,
                    'error': 'Processing record not found or not in processing status'
                }), 404
    except Exception as e:
        print(f"cancel_processing error: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'})

    return jsonify({'success': True})


@app.route('/delete_ticket', methods=['POST'])
def delete_ticket():
    data          = request.json
    ticket_number = data.get('ticket_number')
    category      = data.get('category')
    button_text   = data.get('button_text')
    event_log_id  = data.get('event_log_id')

    if not ticket_number:
        return jsonify({'success': False, 'error': 'Ticket number is required'}), 400

    ticket_number = _parse_int(ticket_number)
    if ticket_number is None:
        return jsonify({'success': False, 'error': 'Invalid ticket number'}), 400
    if category is not None and not _is_valid_category(category):
        return jsonify({'success': False, 'error': 'Invalid category'}), 400
    if event_log_id is not None:
        event_log_id = _parse_int(event_log_id)
        if event_log_id is None:
            return jsonify({'success': False, 'error': 'Invalid event log id'}), 400

    try:
        with get_db() as conn:
            cursor = conn.cursor()
            current_time = datetime.now().isoformat()
            cursor.execute(
                'INSERT INTO processing_logs'
                ' (ticket_number, category, button_text, start_time, end_time,'
                '  wait_time, status, created_at, event_log_id)'
                " VALUES (?, ?, ?, NULL, NULL, 0, 'deleted', ?, ?)",
                (ticket_number, category, button_text, current_time, event_log_id)
            )
    except Exception as e:
        print(f"delete_ticket error: {e}")
        return jsonify({'success': False, 'error': 'Internal server error'})

    return jsonify({'success': True})


@app.template_filter('to_datetime')
def to_datetime(timestamp):
    return datetime.fromisoformat(timestamp).replace(tzinfo=timezone.utc)


@app.route('/processing')
def processing():
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            cursor.execute(_WAITING_LIST_SQL)
            waiting_list = cursor.fetchall()

            cursor.execute(
                'SELECT ticket_number, button_text, start_time, category'
                ' FROM processing_logs'
                " WHERE status = 'processing'"
                " AND DATE(created_at, 'localtime') = DATE('now', 'localtime')"
                ' ORDER BY start_time ASC'
            )
            processing_list = cursor.fetchall()

        current_time = to_datetime(
            datetime.now(timezone.utc)
            .astimezone(timezone(timedelta(hours=9)))
            .isoformat()
        )
    except Exception as e:
        print(f"processing error: {e}")
        waiting_list    = []
        processing_list = []
        current_time    = datetime.now()

    return render_template(
        'syori.html',
        waiting_list=waiting_list,
        processing_list=processing_list,
        current_time=current_time,
    )


@app.route('/display')
def display():
    return render_template('display.html')


@app.route('/display_data')
def display_data():
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            cursor.execute(
                'SELECT ticket_number, category, start_time'
                ' FROM processing_logs'
                " WHERE status = 'processing'"
                " AND DATE(created_at, 'localtime') = DATE('now', 'localtime')"
                ' ORDER BY start_time ASC'
            )
            now     = datetime.now()
            calling = []
            for r in cursor.fetchall():
                try:
                    seconds_since = int((now - datetime.fromisoformat(r[2])).total_seconds())
                except Exception:
                    seconds_since = 999
                calling.append({
                    'number': r[0],
                    'category': r[1],
                    'seconds_since': seconds_since,
                })

            cursor.execute('SELECT COUNT(*) FROM (' + _WAITING_LIST_SQL + ')')
            waiting_count = cursor.fetchone()[0]

    except Exception as e:
        print(f"display_data error: {e}")
        calling       = []
        waiting_count = 0

    return jsonify({'calling': calling, 'waiting_count': waiting_count})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=os.environ.get('FLASK_DEBUG') == '1')
