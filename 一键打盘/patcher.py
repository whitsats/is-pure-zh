from __future__ import annotations

import hashlib
import os
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

SOURCE_SIZE = 1_847_197_696
SOURCE_SHA256 = '00910f6dab053be50e998fe564a25698754d082a6505ce844e547bef1804357b'
OUTPUT_SHA256 = 'b0652b42410c2a15ca0cdfd95c9fdfdd9a4e87511226887130e0721eb890a8b5'
SLOTS = {
    'ETC.AFS': ('etc-v6.afs', 159082, 17889280),
    'MAC.AFS': ('mac-v6.afs', 192346, 1081344),
    'INIT.BIN': ('init-v5-lazy.bin', 823103, 23601),
    'SLPM_665.70': ('SLPM_665.70-patched.elf', 823692, 1514848),
}
CHUNK = 4 * 1024 * 1024


def digest(path, label, start, span, progress):
    h = hashlib.sha256()
    size = path.stat().st_size
    done = 0
    with path.open('rb') as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
            done += len(chunk)
            progress(label, start + span * done / size)
    return h.hexdigest()


def build(source, progress):
    source = Path(source).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != '.iso':
        raise ValueError('请选择原版 ISO 文件。')
    if source.stat().st_size != SOURCE_SIZE:
        raise ValueError('原盘大小不匹配。此工具仅适用于指定版本的 I’s Pure 原版 ISO。')
    output = source.with_name(source.stem + '-汉化版-v7.2.iso')
    if output.exists():
        raise FileExistsError(f'输出文件已存在，请先重命名或移走它：\n{output}')
    if digest(source, '正在校验原版 ISO…', 0, 30, progress) != SOURCE_SHA256:
        raise ValueError('原盘校验不通过。此工具仅适用于指定版本的 I’s Pure 原版 ISO，请勿使用已打补丁或其他版本的镜像。')
    resource_dir = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'patch'
    patches = {}
    for name, (filename, lba, allocation) in SLOTS.items():
        data = (resource_dir / filename).read_bytes()
        if len(data) > allocation:
            raise ValueError(f'补丁文件过大：{filename}')
        patches[name] = data
    temp_path = None
    try:
        fd, name = tempfile.mkstemp(prefix='.is-pure-', suffix='.tmp', dir=source.parent)
        temp_path = Path(name)
        with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
            copied = 0
            while chunk := src.read(CHUNK):
                dst.write(chunk)
                copied += len(chunk)
                progress('正在复制并制作汉化镜像…', 30 + 40 * copied / SOURCE_SIZE)
        with temp_path.open('r+b') as f:
            for name, (_, lba, allocation) in SLOTS.items():
                data = patches[name]
                f.seek(lba * 2048)
                f.write(data)
                if name != 'INIT.BIN':
                    f.write(b'\0' * (allocation - len(data)))
            f.seek(16 * 2048)
            pvd = f.read(2048)
            if pvd[1:6] != b'CD001':
                raise ValueError('无法识别 ISO 文件系统。')
            root = pvd[156:190]
            root_lba = struct.unpack('<I', root[2:6])[0]
            root_size = struct.unpack('<I', root[10:14])[0]
            f.seek(root_lba * 2048)
            directory = bytearray(f.read(root_size))
            offset = 0
            found = False
            while offset < root_size:
                length = directory[offset]
                if not length:
                    break
                record = directory[offset:offset + length]
                name = record[33:33 + record[32]].split(b';')[0]
                if name == b'INIT.BIN':
                    struct.pack_into('<I', directory, offset + 10, len(patches['INIT.BIN']))
                    struct.pack_into('>I', directory, offset + 14, len(patches['INIT.BIN']))
                    found = True
                    break
                offset += length
            if not found:
                raise ValueError('ISO 中未找到 INIT.BIN，无法完成打盘。')
            f.seek(root_lba * 2048)
            f.write(directory)
        if digest(temp_path, '正在校验汉化镜像…', 70, 30, progress) != OUTPUT_SHA256:
            raise ValueError('生成的镜像校验失败，请检查磁盘空间和原盘。')
        # Windows rename fails when the destination already exists.
        os.rename(temp_path, output)
        temp_path = None
        return output
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--batch':
        try:
            build(sys.argv[2], lambda *_: None)
            return 0
        except Exception:
            return 1

    root = tk.Tk()
    root.withdraw()
    root.title('I’s Pure 汉化一键打盘 v7.2')
    if len(sys.argv) > 2:
        messagebox.showerror('无法开始', '请一次只拖入一个原版 ISO 文件。', parent=root)
        root.destroy()
        return 1
    source = sys.argv[1] if len(sys.argv) == 2 else filedialog.askopenfilename(
        parent=root, title='选择 I’s Pure 原版 ISO', filetypes=[('ISO 镜像', '*.iso'), ('所有文件', '*.*')])
    if not source:
        root.destroy()
        return 0
    root.deiconify()
    root.geometry('540x160')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    label = ttk.Label(frame, text='准备中…')
    label.pack(anchor='w', pady=(0, 12))
    progress_bar = ttk.Progressbar(frame, maximum=100)
    progress_bar.pack(fill='x')
    ttk.Label(frame, text='请保持窗口打开；原版 ISO 不会被修改。').pack(anchor='w', pady=(12, 0))
    events = queue.Queue()

    def run():
        try:
            output = build(source, lambda text, value: events.put(('progress', text, value)))
            events.put(('success', str(output)))
        except Exception as exc:
            events.put(('error', str(exc)))

    def poll():
        try:
            while True:
                event = events.get_nowait()
                if event[0] == 'progress':
                    label.config(text=event[1])
                    progress_bar['value'] = event[2]
                elif event[0] == 'success':
                    messagebox.showinfo('制作完成', '汉化 ISO 已生成：\n' + event[1], parent=root)
                    root.destroy()
                    return
                else:
                    messagebox.showerror('制作失败', event[1], parent=root)
                    root.destroy()
                    return
        except queue.Empty:
            root.after(100, poll)

    root.protocol('WM_DELETE_WINDOW', lambda: messagebox.showinfo('正在制作', '请等待制作完成后再关闭窗口。', parent=root))
    threading.Thread(target=run, daemon=True).start()
    root.after(100, poll)
    root.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
