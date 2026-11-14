from pathlib import Path
import json
import shutil

root = Path(__file__).resolve().parent
project = root / 'RenPy文本格式样例' / 'game'
project.mkdir(parents=True, exist_ok=True)
source = next((root.parent / '汉化包-v3' / '对照').glob('IS01*'))
lines = []
for row in source.read_text(encoding='utf-8-sig').splitlines():
    fields = row.split('\t')
    if len(fields) >= 3 and fields[0].startswith('No.'):
        lines.append(fields[2])
    if len(lines) == 10:
        break
assert len(lines) == 10
shutil.copyfile(root / '开场高清2x.png', project / 'sample.png')
script = ['# 技术样例：图片与台词未经原游戏事件关联，仅验证格式。',
          'label start:',
          '    scene expression "sample.png"',
          '    "技术样例：以下文字和背景并非对应原游戏场景。"']
script += ['    ' + json.dumps(line, ensure_ascii=False) for line in lines]
script += ['    return', '']
(project / 'script.rpy').write_text('\n'.join(script), encoding='utf-8')
print('Generated:', project / 'script.rpy', 'dialogue lines:', len(lines))
