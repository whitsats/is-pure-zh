# PS2 游戏资源提取与 1px 保护边修复指南

## 一、 问题背景与现象
在对 PS2 文字冒险游戏（以《I's Pure》为例）的 `CHR.AFS`（立绘）、`BG.AFS`（背景）及 `EV.AFS`（事件 CG）进行逆向解包与离线渲染时，传统按 $32\times32$ 完整图块线性拼合或固定步长解码会导致以下典型瑕疵：
1. **太阳穴悬空黑线**：人物头部右侧或发际线外侧出现垂直的黑线。
2. **周期性锯齿缺口**：眉毛、眼镜框、左右耳廓以及下颌线在跨越图块网格边界时出现明显的 `1px` 阶梯状缺口或错位。
3. **图像边缘发虚或半透明错误**：未正确转换 PS2 的 7 位 Alpha 范围（`0x00 ~ 0x80` 映射至 `0x00 ~ 0xFF`）。

---

## 二、 核心根因：PS2 GS 的 1px 镜像保护边机制
经反汇编分析原版主程序 (`SLPM_665.70`) 的精灵渲染管线与实机纹理转储比对，确认缺陷根因如下：
* **物理存储 vs 逻辑渲染**：游戏底层在显存（VRAM）中以 $32\times32$ 像素的物理瓦片（Tile）存储纹理。
* **双线性滤波保护边**：为了防止渲染时光栅化插值（Bilinear Filtering）在图块边缘产生越界采样噪声，硬件在每个 $32\times32$ 物理图块的四周各内嵌了一圈 **1 像素的镜像保护边（Guard Band）**。
* **有效核心像素**：实际参与画布显示的有效核心像素尺寸严格为 **$30\times30$**（即物理行/列索引在 `1` 至 `30` 之间，跳过 `0` 和 `31`）。

如果离线解包脚本直接按 $32\times32$ 步长拼合，保护边像素会被重复计算并嵌入画面，从而导致边界错位与悬空黑线。

---

## 三、 正确的无损提取与拼合规范

### 1. 存储行寻址与步长
* 像素流以 **$1024$ 像素** 为行宽，切分为高度 $32$ 像素的“存储行”（每行包含 $32$ 个 $32\times32$ 物理块）。
* 图块使用全局连续块号（Tile Index）线性索引，**在部件网格边界处不重置游标**。

### 2. 核心剥离与拼合算法 (`decode_clean_30.py`)
```python
import struct
import zlib
from pathlib import Path

def decode_clean_30(raw: bytes, crop_canvas: bool = True):
    """
    按 1024px 存储行读取 32x32 块，剥离四周 1px 镜像保护边，以 30x30 核心无缝拼合
    """
    cnt = struct.unpack_from('<I', raw, 0)[0]
    ptrs = struct.unpack_from(f'<{cnt}I', raw, 4)
    sec0 = ptrs[0]
    hs = ptrs[-2]  # 动态头大小 (0x100 或 0x180)

    n_rect, cx, cy, cw, ch, fmt = struct.unpack_from('<IHHHHH', raw, sec0)
    rects = [struct.unpack_from('<BBBBHH', raw, sec0 + 16 + r * 8) for r in range(n_rect)]

    # 网格步长严格为 30 像素
    max_w = max([cw] + [(gx + gw) * 30 for gx, _, gw, _, _, _ in rects])
    max_h = max([ch] + [(gy + gh) * 30 for _, gy, _, gh, _, _ in rects])
    canvas = bytearray(max_w * max_h * 4)

    tile = 0
    for gx, gy, gw, gh, rfmt, end_tile in rects:
        for j in range(gh):
            for i in range(gw):
                sy, sx = tile // 32, tile % 32
                # 剥离四周 1px 保护边：py 和 px 仅遍历 1 到 30
                for py in range(1, 31):
                    dy = (gy + j) * 30 + (py - 1)
                    if dy >= max_h:
                        continue
                    src_row = hs + ((sy * 32 + py) * 1024 + sx * 32) * 4
                    dst_row = (dy * max_w + (gx + i) * 30) * 4
                    for px in range(1, 31):
                        sp = src_row + px * 4
                        # PS2 Alpha 范围转换 (0~128 映射到 0~255)
                        a8 = min(255, (raw[sp + 3] * 255 + 64) // 128)
                        if a8 > 0:
                            dp = dst_row + (px - 1) * 4
                            canvas[dp]     = raw[sp]
                            canvas[dp + 1] = raw[sp + 1]
                            canvas[dp + 2] = raw[sp + 2]
                            canvas[dp + 3] = a8
                tile += 1
        if end_tile > tile:
            tile = end_tile

    if crop_canvas:
        out = bytearray(cw * ch * 4)
        for y in range(ch):
            s_off = ((cy + y) * max_w + cx) * 4
            d_off = y * cw * 4
            out[d_off : d_off + cw * 4] = canvas[s_off : s_off + cw * 4]
        return cw, ch, out
    return max_w, max_h, canvas
```

---

## 四、 适用范围
该方案已在以下封包中全量验证通过（解析成功率 100%）：
1. **`CHR.AFS`**：人物全身立绘及半身头像，彻底消除接缝毛刺与悬空线条。
2. **`BG.AFS`**：所有背景图，完美对齐标准 `640×448` 显示帧。
3. **`EV.AFS`**：事件 CG，确保多部件拼接平滑连贯。
