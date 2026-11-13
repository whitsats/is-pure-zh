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
OUTPUT_SHA256 = '526178792dfec7746948e6b98bff28718da03d8ea68bde8509c9b55947fe05c1'
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
    output = source.with_name(source.stem + '-汉化版-v7.4.iso')
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


def report_error(title, text):
    """窗口程序没有控制台，出错必须让用户看得见，同时留一份日志。"""
    log = None
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).with_suffix('.错误.log'))
    candidates.append(Path(tempfile.gettempdir()) / 'is-pure-patcher-error.log')
    for candidate in candidates:
        try:
            candidate.write_text(text, encoding='utf-8')
            log = candidate
            break
        except OSError:
            continue
    body = text + (f'\n\n已写入日志：\n{log}' if log else '')
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, body)
        root.destroy()
    except Exception:                                   # noqa: BLE001 弹不出来也不能崩
        pass


def output_for(source):
    """与原盘同目录、同名的输出路径。"""
    return Path(source).with_name(Path(source).stem + '-汉化版-v7.4.iso')


def gui(source=None):
    root = tk.Tk()
    root.title('I’s Pure 汉化一键打盘 v7.4')
    root.resizable(False, False)

    src_var = tk.StringVar(value=str(source) if source else '')
    out_var = tk.StringVar()

    def refresh_out(*_):
        text = src_var.get().strip()
        out_var.set(str(output_for(text)) if text else '（选好原版 ISO 后自动生成）')

    src_var.trace_add('write', refresh_out)
    refresh_out()

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)

    ttk.Label(frame, text='原版 ISO').grid(row=0, column=0, sticky='w', pady=4)
    entry = ttk.Entry(frame, textvariable=src_var, width=56)
    entry.grid(row=0, column=1, sticky='we', pady=4)
    ttk.Label(frame, text='把 game-original.iso 拖到本程序上也可以',
              foreground='#666').grid(row=1, column=1, sticky='w')

    ttk.Label(frame, text='输出镜像').grid(row=2, column=0, sticky='w', pady=4)
    out_entry = ttk.Entry(frame, textvariable=out_var, width=56, state='readonly')
    out_entry.grid(row=2, column=1, sticky='we', pady=4)
    ttk.Label(frame, text='与原盘同目录，不会覆盖已有文件',
              foreground='#666').grid(row=3, column=1, sticky='w')

    def pick():
        chosen = filedialog.askopenfilename(
            parent=root, title='选择 I’s Pure 原版 ISO',
            filetypes=[('ISO 镜像', '*.iso'), ('所有文件', '*.*')])
        if chosen:
            src_var.set(chosen)

    browse = ttk.Button(frame, text='浏览…', command=pick)
    browse.grid(row=0, column=2, padx=(6, 0))

    status = ttk.Label(frame, text='准备就绪', foreground='#333')
    status.grid(row=4, column=0, columnspan=3, sticky='w', pady=(14, 4))
    bar = ttk.Progressbar(frame, maximum=100, length=520)
    bar.grid(row=5, column=0, columnspan=3, sticky='we')

    buttons = ttk.Frame(frame)
    buttons.grid(row=6, column=0, columnspan=3, sticky='e', pady=(14, 0))
    start = ttk.Button(buttons, text='开始打盘')
    start.pack(side='left')

    ttk.Label(frame, text='只把四个文件替换进原盘，原版 ISO 不会被修改；'
                          '补丁载荷已内含 v7.1/v7.2 的显示修复、v7.3 的译文润色与 v7.4 的字库补充。',
              foreground='#666').grid(row=7, column=0, columnspan=3, sticky='w', pady=(12, 0))

    events = queue.Queue()
    busy = {'value': False}

    def work():
        try:
            output = build(src_var.get().strip(),
                           lambda text, value: events.put(('progress', text, value)))
            events.put(('success', str(output)))
        except Exception as exc:                        # noqa: BLE001 报给用户看
            events.put(('error', str(exc)))

    def on_start():
        if busy['value']:
            return
        text = src_var.get().strip()
        if not text:
            messagebox.showerror('无法开始', '请先选择原版 ISO。', parent=root)
            return
        if not Path(text).is_file():
            messagebox.showerror('无法开始', f'找不到这个文件：\n{text}', parent=root)
            return
        if output_for(text).exists():
            messagebox.showerror(
                '输出已存在',
                f'{output_for(text)}\n\n请先重命名或移走它，程序不会覆盖已有文件。',
                parent=root)
            return
        busy['value'] = True
        start.config(state='disabled')
        browse.config(state='disabled')
        bar['value'] = 0
        status.config(text='准备中…')
        threading.Thread(target=work, daemon=True).start()

    start.config(command=on_start)
    entry.bind('<Return>', lambda _e: on_start())

    def poll():
        try:
            while True:
                event = events.get_nowait()
                if event[0] == 'progress':
                    status.config(text=event[1])
                    bar['value'] = event[2]
                elif event[0] == 'success':
                    busy['value'] = False
                    bar['value'] = 100
                    status.config(text='完成')
                    start.config(state='normal')
                    browse.config(state='normal')
                    path = Path(event[1])
                    if messagebox.askyesno(
                            '打盘完成',
                            f'汉化镜像已生成：\n{path}\n\n要打开它所在的文件夹吗？',
                            parent=root):
                        try:
                            os.startfile(path.parent)       # noqa: S606 只看文件夹
                        except Exception:                   # noqa: BLE001 打不开就算了
                            pass
                else:
                    busy['value'] = False
                    bar['value'] = 0
                    status.config(text='失败')
                    start.config(state='normal')
                    browse.config(state='normal')
                    report_error('打盘失败', event[1])
        except queue.Empty:
            root.after(100, poll)

    root.protocol('WM_DELETE_WINDOW',
                  lambda: messagebox.showinfo('正在制作', '请等待制作完成后再关闭窗口。',
                                              parent=root) if busy['value'] else root.destroy())

    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
    root.after(100, poll)
    root.mainloop()
    return 0


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--batch':
        try:
            build(sys.argv[2], lambda *_: None)
            return 0
        except Exception:                               # noqa: BLE001 批处理只看退出码
            return 1

    loose = [a for a in sys.argv[1:] if not a.startswith('-')]
    if len(loose) > 1:
        report_error('无法开始', '一次只能拖入一个原版 ISO 文件。\n\n收到的：\n'
                     + '\n'.join(loose))
        return 1
    if loose:
        candidate = Path(loose[0])
        if not candidate.is_file():
            report_error('打不开这个文件', f'找不到：\n{candidate}')
            return 1
        return gui(candidate)
    if sys.argv[1:]:
        report_error('参数不对', '无法识别的参数：\n' + ' '.join(sys.argv[1:]) + '\n\n'
                     '把原版 ISO 拖到本程序上即可；不带参数双击则打开界面。')
        return 1
    return gui()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:                               # noqa: BLE001 别静默退出
        import traceback
        report_error('汉化一键打盘 出错了', traceback.format_exc())
        raise SystemExit(1)
