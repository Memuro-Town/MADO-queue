"""
printer.py — レシートプリンターモジュール

ESC/POSバイト列の構築と印刷を担当する。
app.py から分離し、保守性を向上させる。
"""

from datetime import datetime
import os
import sys

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

PRINTER_NAME = os.environ.get('PRINTER_NAME', 'POS-80C (copy 1)')
PRINTER_VID = int(os.environ.get('PRINTER_VID', '0x04b8'), 16)
PRINTER_PID = int(os.environ.get('PRINTER_PID', '0x0e20'), 16)


# ---------------------------------------------------------------------------
# ESC/POS データ構築
# ---------------------------------------------------------------------------

def _build_escpos_data(category, button_text, number, timestamp_str, encoding='cp932'):
    """ESC/POSバイト列を組み立てる。プリンター側の既定コードページ(cp932/Shift_JIS)に合わせる。"""
    ESC = b'\x1b'
    GS = b'\x1d'

    def s(text):
        return text.encode(encoding, errors='replace')

    try:
        dt = datetime.fromisoformat(timestamp_str)
        formatted_time = dt.strftime('%m.%d-%H:%M:%S')
    except Exception:
        formatted_time = timestamp_str or ''

    data = ESC + b'@'            # 初期化
    data += ESC + b'a\x01'        # 中央揃え
    data += GS + b'!\x01'        # 縦2倍
    data += s(f'カテゴリ: {category}\n')
    data += s(f'用途: {button_text}\n\n')
    data += s(f'日時: {formatted_time}\n\n')
    data += GS + b'!\x33'        # 縦横4倍
    data += s(f'番号: {number}\n\n')
    data += GS + b'!\x00'        # 通常サイズに戻す
    if category != 'A':
        data += s('カテゴリAの方を先に\nご案内する場合があります\n')
    data += GS + b'V\x41\x30'     # 48ドット送ってからカット
    return data


# ---------------------------------------------------------------------------
# Windows 印刷
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Linux 印刷
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# メインエントリ
# ---------------------------------------------------------------------------

def print_ticket(category, button_text, number, timestamp_str):
    """レシートプリンターにチケットを印刷する。カテゴリDは印刷せず成功扱いにする。"""
    if category == 'D':
        return True
    try:
        # プリンター本体がcp932(Shift_JIS)を前提としているため、OSに関わらずcp932を使う
        data = _build_escpos_data(category, button_text or '', number, timestamp_str or '', 'cp932')
        if sys.platform == 'win32':
            _print_windows(data)
        else:
            _print_linux(data)
        print(f'[print_ticket] 印刷完了: カテゴリ={category} 番号={number}')
        return True
    except Exception as e:
        print(f'[print_ticket] error: {e}')
        return False
